# ghost_tools -- v0.6

Four commands, one pipeline. `ghost-buster` hunts down structural problems
in code and, with `--mutate`, proves which tests pass without checking
anything; `ghost-triage` records the human decision on each finding;
`ghost-writer` turns the ones worth documenting (not fixing) into accurate
docs; `blackhole-extrapolator` outlines the things that are not there at all.

    ghost-buster              things that are present and wrong
    ghost-buster --mutate     tests that pass with the thing they name broken
    ghost-triage              the human decision, recorded with its reason
    ghost-writer              the ones worth documenting
    blackhole-extrapolator    the ones that went up in smoke

## Install

```bash
python -m pip install "git+https://github.com/wking53214/ghost_tools"
ghost-buster /path/to/repo
```

No dependencies. Python 3.11 or later. `python -m ghost_buster.cli` and the
other module forms keep working for a checkout without an install.

Built from a researched taxonomy of what actually goes wrong in large,
iteratively-built (especially AI-assisted) codebases -- duplication,
parallel unreconciled implementations, dead code, and documentation that
described a system that no longer exists by the time anyone reads it again.

## The pipeline, and the one rule that makes it safe

```
ghost_buster (mechanical + semantic detectors)
        |
        v
   FindingSet (every finding: REASONED or CONFIRMED, never assumed)
        |
        v
   HUMAN TRIAGE  <-- the gate. Nothing skips this.
        |
   +----+----+----------+
   |         |          |
  fix      suppress   document
   |         |          |
(issue    (baseline)    v
 tracker)            ghost_writer
                      (renders ONLY disposition="document" findings)
```

`ghost_writer` never reads `ghost_buster`'s raw output. It only reads
findings a human has explicitly marked `disposition="document"`. A real bug
goes to `fix`, not into a README pretending it's a design decision. This
gate is enforced in code (`ghost_writer/report.py`'s
`dispositioned_for_documentation`), not just convention.

## ghost_buster

Two independent layers, both producing the same `Finding` shape
(`ghost_buster/schema.py`):

- **Mechanical** (`ghost_buster/mechanical.py`) -- deterministic, AST-based,
  stdlib only. Every finding is `Status.CONFIRMED`; there's nothing to
  doubt about a deterministic check. Five detectors as of v0.3:
  `dead_code`, `long_function`, `near_duplicate_function`,
  `intra_function_duplicate_block`, `doc_test_count_drift`.

  `dead_code` was calibrated against a real, previously-unseen repo
  (ANVIL) and found two real false-positive classes on the first run:
  `Protocol`/`ABC` interface classes (whose whole purpose is often zero
  in-file references -- external implementers are the intended
  consumers) and string-keyed dynamic dispatch (`registry["Name"]`,
  including a module loaded via `exec()` into a dict and read back by
  string key). Both are now excluded/traced (v0.1.1). Still disclosed and
  not fixed: getattr-by-string and decorator-based registration --
  confirmed live, this tool's own `@register` pattern in `mechanical.py`
  self-flags for exactly that reason when ghost_buster scans itself.

  `intra_function_duplicate_block` (v0.2) closes a gap
  `near_duplicate_function` cannot: duplication that lives INSIDE one
  function rather than across two whole functions -- e.g. several sibling
  if/elif branches that each hand-build the same kind of object.
  Motivated by a real case found by reading code, not by ghost_buster,
  during HERALD triage: `gate.py`'s `submit()` had six verdict branches
  each independently constructing a `GateDecision` with the same
  `authorization_mac=_sign_decision(...)` call -- invisible to
  `near_duplicate_function` because no single branch is a whole function.
  Two comparison units, both required because neither subsumes the
  other (confirmed by a live check against the actual pre-fix `gate.py`,
  which the first design -- statement-count only -- caught nothing on):
  a contiguous run of `min_statements`+ sibling statements, and any
  single statement whose own AST subtree exceeds `min_complexity` nodes
  (a lone `return Decision(...)` with a nested call can be 40+ nodes
  even though it's one statement). Scoped to one function at a time,
  deliberately -- matching a block in function A against one in function
  B is a different, noisier claim, left for later if it turns out to
  matter. In practice, on a real test suite, most of what this flags is
  low-severity (`MINOR`, 2 occurrences) pairs of near-identical
  `assert` lines inside adversarial test scaffolding -- a disclosed,
  expected pattern, the same kind `near_duplicate_function` already
  disclosed for whole functions, not a bug.

  `doc_test_count_drift` (v0.3) is the first detector that reads `.md`
  files (the CLI's file collection now scans `*.md` alongside `*.py`;
  every other detector still only acts on Python and silently skips
  markdown via the same fail-closed `_parse()` every mechanical detector
  already used). Found by doing, by hand, exactly the taxonomy-driven
  scrub this detector now automates: HERALD's README claimed "135 tests
  passing" while the real suite had grown to 321 collected cases across
  15 commits the README was never updated for. This is the same
  "documentation describes a system that no longer exists" failure the
  *semantic* `doc_drift` detector already names (same `Category.DOC_DRIFT`)
  -- but semantic `doc_drift` needs an API call and a human-supplied code
  summary per check; it cannot self-drive a whole-repo scan. A number
  next to the word "test(s)" in a markdown file is instead fully
  mechanical: no API key, no judgment call, `Status.CONFIRMED`. Counts
  the real side via static AST (every `test_*` function across the
  scanned `.py` files) -- a deliberate LOWER BOUND, since
  `@pytest.mark.parametrize` can only push the true collected count
  higher, never lower. Because of that asymmetry the detector is
  one-directional by design: it only flags a documented count the real
  count has grown well past (`min_growth_ratio` AND `min_absolute_growth`
  both required), never a documented count that looks high relative to
  the static floor -- that direction isn't confidently wrong and would
  false-positive on ordinary parametrize use.
- **Semantic** (`ghost_buster/semantic.py`) -- backed by a real Claude API
  call (`AnthropicModelClient`, model `claude-sonnet-5`), for the class of
  ghost no static pass can see: two modules solving the same problem two
  different ways, or a doc claim that no longer matches what the code
  does. Every finding here is `Status.REASONED`, never `CONFIRMED` --
  enforced by `schema.py`, not just a naming convention. It takes a human
  (or a second check) to promote one to `CONFIRMED_BY_REVIEW`.

  Untrusted code/docs are always sent role-separated (system instruction
  vs. user-turn data) and XML-fenced, the same two-layer defense pattern
  used in `sentinel_os`'s own governor integration -- written fresh here,
  not copied, but the same shape for the same reason. Every failure mode
  (no API key, network error, malformed JSON, a response missing the
  required shape) fails closed to an empty finding list plus a
  `SemanticRunReport` explaining why -- never a crash, never a fabricated
  finding.

### Usage

```bash
# scan a directory, show new findings since the last baseline
python -m ghost_buster.cli /path/to/repo

# accept everything currently found into the baseline (stop re-flagging it)
python -m ghost_buster.cli /path/to/repo --accept

# emit machine-readable JSON (feeds the triage step, then ghost_writer)
python -m ghost_buster.cli /path/to/repo --json > findings.json

# skip a repo-specific vendored tree (e.g. a checked-in copy of another repo)
python -m ghost_buster.cli /path/to/repo --exclude some_vendored_dir

# prove vacuous tests by mutation (one pytest process per mutant; the working
# tree is never touched). --mutate-only narrows to test files matching a string.
python -m ghost_buster.cli /path/to/repo --mutate --mutate-verbose
python -m ghost_buster.cli /path/to/repo --mutate --mutate-only test_policy --json > findings.json
```

### `--mutate`: the proof a check is vacuous

The characteristic defect of an iteratively built codebase is a check that
passes without doing its job. Coverage counts it; CI is green; nothing
notices. The only honest proof that a test is vacuous is a broken
implementation the test still passes. Deleting an assertion proves nothing,
because a deleted assertion cannot fail.

`--mutate` does what a careful auditor does by hand:

1. finds candidate tests by shape: every assertion is `is not None` / `> 0`
   / `isinstance` / a bare name; a result assigned from a call and never
   read; assertions behind a bare `if`; a hand-written list of strings
   compared with something derived;
2. resolves what project code each candidate calls, through the test file's
   imports (constructed instances and fixture-injected receivers included,
   when exactly one imported class defines the method);
3. copies the project to a scratch directory (siblings symlinked beside it),
   breaks that code one operator at a time -- `drop_body`, `return_none`,
   `flip_compare`, `bump_constants` -- and runs only that test; for a guard,
   instruments it and fails the test if the guarded assertions never ran;
   for a restated list, adds a member to the enum or collection that defines
   those values;
4. reports a finding ONLY when the test survived, with the mutation named
   as its proof. A killed mutant is not a finding: the test did its job. A
   candidate that does not pass unmutated is reported as unjudged, never as
   a finding.

Findings carry category `vacuous_check`. A guard that holds every assertion
of its test is CRITICAL; one beside unguarded assertions is MAJOR; a
survived code mutation is MAJOR. Validated on real repositories on
2026-09-08: it found the test a hand audit had confirmed the day before, and
one that survives eleven inverted comparisons in the function it names.

The scan always skips virtualenvs (by the `site-packages` component, so the
venv's directory name doesn't matter), `node_modules`, VCS directories, and
tool caches -- a working tree with a venv in it was otherwise reporting
thousands of findings from its dependencies' source. `--exclude DIRNAME`
(repeatable) adds a directory name for the repo-specific cases the built-in
list can't know about, like a vendored copy of a sibling repo.

Exit code is `1` if any new CRITICAL/MAJOR finding exists, `0` otherwise --
usable as a CI gate on the mechanical layer (the semantic layer needs an
API key and isn't wired into the CLI by default; see below).

The semantic layer is a library, used directly:

```python
from ghost_buster.semantic import AnthropicModelClient, detect_parallel_implementations

client = AnthropicModelClient(api_key="...")
findings, report = detect_parallel_implementations(client, {
    "harness_a.py": "...",  # a summary/docstring, not necessarily the full file
    "harness_b.py": "...",
})
```

## ghost_writer

- `ghost_writer/report.py` -- pure templating (no API call). Renders
  `disposition="document"` findings, grouped by category, into a markdown
  section -- including *why* it was documented rather than fixed
  (`disposition_note`), which is exactly the context a stale doc usually
  lacks.
- `ghost_writer/correct.py` -- the judgment-requiring half. Given one
  `doc_drift` finding and a current, accurate code summary, proposes a
  **minimal, targeted replacement** for the one stale claim -- deliberately
  not a full doc regeneration, which risks losing hard-won specificity a
  human wrote for a real reason. Reuses `ghost_buster.semantic`'s client
  protocol and injection-fencing helpers directly rather than
  reimplementing them (exactly the "two implementations of the same thing"
  problem this whole project exists to catch, not repeated here). Returns
  a `CorrectionProposal` -- a suggestion with reasoning and a confidence
  score. **Nothing in this module writes to a file.** Applying a proposal
  is a human decision, always, outside this module.
- `ghost_writer/polish/` -- the quality gate around that one LLM call, the
  only place in `ghost_writer` that generates new text rather than
  templating a human's own decision. Vendored from `content-polish-pipeline`
  (MIT; origin, commit and every change to the copy are recorded in
  `PROVENANCE.md`) when that repo was retired into this one. Three filters
  and one retry loop. Every response is checked before it becomes a
  proposal: no first-person pronoun and no hedging word (`might`, `may`,
  `could`, `probably`, ...) in the replacement or the reasoning, and at
  least one evidence marker (a percentage, `data`, `evidence`, `showed`,
  ...) in the reasoning. The evidence check is scoped to the reasoning on
  purpose: a minimal doc replacement is not an empirical claim, and one
  that happens to carry an evidence word does not excuse a reasoning that
  cites nothing. A rejected response is not discarded silently: its
  violations are appended to the prompt, after the fenced untrusted block
  and never inside it, and the model is asked again, three attempts in
  total by default (`max_attempts`), each one a paid call. Empty,
  malformed and client-failed responses are not retried; they stay the
  single-shot fail-closed paths they were before. When every attempt fails
  the result is the same `(None, report)` every other no-proposal outcome
  produces, with the violations in `report.reason`. `report.py` is not
  gated: it renders a human's own triage note, which is allowed to say
  "I think". The checks are regular expressions over a fixed vocabulary:
  `may` in its permissive sense ("may be repeated") is rejected like any
  other hedge, and the evidence check is satisfied by the vocabulary, not
  by the citation being true. `Tests/test_ghost_writer.py` covers each
  filter against each field, the retry with its feedback placement, the
  attempt ceiling and the untouched fail-closed paths;
  `Tests/test_gate_mutants.py` breaks the gate fourteen ways in a scratch
  copy (each check forced true, the loop cut to one attempt, the feedback
  dropped, the verdict ignored, the patterns emptied) and requires each
  mutant to fail at least one of those tests, and
  `Tests/test_polish_mutants.py` does the same for the vendored code against
  its own ported suite, twenty-eight ways. `ghost-buster --mutate` reports no
  candidate in any of these files: none of them has a shape it mutates.

### Usage

```bash
# the whole pipeline
ghost-buster /path/to/repo --mutate --json > findings.json
ghost-triage findings.json                      # list what is undecided
ghost-triage findings.json --set ghost-1a2b3c=fix:"real bug, issue #12" \
                           --set ghost-4d5e6f=document:"deliberate, see ADR-7"
ghost-writer findings.json --mode triage         # everything, for the person deciding
ghost-writer findings.json --out ARCHITECTURE_GHOSTS.md   # only what was marked document

# module forms, for a checkout without an install
python -m ghost_writer.triage findings.json --set ID=suppress:"accepted"
python -m ghost_writer.cli findings.json --title "Known Structural Ghosts"
```

`ghost-triage` is the human step the pipeline diagram always had and the
code never did: it records `fix` / `suppress` / `document` and a note
against finding ids (a unique prefix is enough), refuses unknown or
ambiguous ids rather than silently doing nothing, and never touches code,
docs or the baseline. `--mode triage` renders every finding, most severe
first, grouped by file, with `vacuous_check` proofs called out and
already-decided findings listed with their decision; it says on its face
that nothing in it has been reviewed. The document mode and its gate are
unchanged.

## Non-goals, stated explicitly (v0.1 and likely beyond)

- **Neither tool ever fixes anything automatically.** `ghost_buster` finds
  and reports; `ghost_writer` documents or proposes a correction. Applying
  either is always a separate, human-initiated act.
- The semantic layer never runs by default (costs real money per call);
  it's opt-in, by design, every time.
- `ghost_writer` never touches a file except via the explicit `--out` flag
  writing a *new* report file -- it does not open and rewrite an existing
  README in place.

## Requirements

Stdlib only for the mechanical layer and the whole `ghost_writer` package.
`anthropic` (already a dependency in this environment) only if you
construct an `AnthropicModelClient` -- everything else is fully testable
via `StubModelClient` with zero network access, which is how the entire
test suite runs.

## Tests

```bash
python -m pytest Tests/ -v
```

255 tests, 0 network calls, 0 API key required -- the semantic-layer tests
verify the real parsing/fail-closed/injection-fencing logic via
`StubModelClient`, the same technique `sentinel_os`'s own `interpretation/`
package uses for its model-client tests. `test_mutation.py`,
`test_gate_mutants.py` and `test_polish_mutants.py` run pytest in
subprocesses against scratch copies of the project; they account for most
of the suite's wall-clock time.

## Changelog

- **v0.3.1** -- CLI file collection now skips virtualenvs / vendored
  `site-packages` / `node_modules` / VCS dirs / tool caches, and takes a
  repeatable `--exclude DIRNAME` for repo-specific vendored trees. Found by
  running the mechanical layer across 18 real repos in one pass: one repo
  with a `.venv` in its working tree reported 3,789 findings, of which 3,702
  were inside `site-packages` (pytest's own source). `site-packages` is the
  match that matters -- it catches an installed-package tree regardless of
  the enclosing venv's directory name.
- **v0.3** -- new mechanical detector `doc_test_count_drift`, the first
  taxonomy-driven scrub of a real target repo (HERALD) done by hand
  against the researched ghost list, then turned into a detector. CLI
  file collection now includes `*.md` alongside `*.py` (every other
  detector is unaffected -- markdown fails `_parse()` and is silently
  skipped, same fail-closed behavior as any other unparseable file).
- **v0.2** -- new mechanical detector `intra_function_duplicate_block`,
  closing the "duplication inside one function" gap surfaced during the
  HERALD dogfood run (see above). Includes a regression test for a real
  bug caught during its own development: an `ast.walk`-based scope
  boundary cannot be pruned at a nested `def`, so an early version leaked
  a nested function's blocks into its enclosing function's comparison
  set. Fixed by recursing through statement lists directly instead of
  `ast.walk`.
- **v0.1.2** -- fixed `near_duplicate_function` silently collapsing two
  distinct same-named occurrences into one label (found via a real run
  against HERALD).
- **v0.1.1** -- fixed two `dead_code` false-positive classes (found via a
  real run against ANVIL): `Protocol`/`ABC` interface classes, and
  string-subscript-key dynamic dispatch.
- **v0.1** -- initial release: `ghost_buster` (mechanical + semantic
  layers) and `ghost_writer`.


---

## blackhole_extrapolator

A black hole is never observed. It is inferred entirely from what it does to
the things around it -- the orbits it bends, the light it lenses -- and its
interior is not recoverable at any resolution, ever. This tool applies that to
missing code: it reconstructs the **shape** of an absence from the marks the
absence left on the code that survived it.

### Not an adapter, and not a seam

Adapter construction and seam building both connect two things that exist. You
can read both sides, run both sides, and test the join against both.

A void has no such luxury. The connector itself went up in smoke -- a flattened
paste that no longer parses, a module three files import and nothing provides,
a name every caller expects and nothing defines. There is nothing to read. The
only evidence is the shape of the hole.

### What it reads

Six kinds of mark an absence leaves, all detected mechanically by AST analysis
-- same input, same output, no model:

| signal | what it tells you |
|---|---|
| dangling reference | the strongest. Callers describe the interface in the act of using it |
| orphaned test | interface **and** expected behaviour |
| missing module | names it directly, and `from x import a, b` enumerates part of its surface |
| unparseable file | something that existed and was destroyed; the bytes survive, the program does not |
| debris structure | a flattened file's `class` and `def` headers in token order, with parameter lists and return annotations: the interface survives, the bodies do not |
| unconsumed output / unsatisfied requirement | one side of a join that is gone |
| shape complementarity | the weakest, and the only one that may mean a useful connection nobody ever made |

### What it produces

A `Void` -- a specification of an absence, carrying two lists that must be
read together:

    inferred        what the surrounding code forces to be true
    undeterminable  what the surrounding code cannot decide

The second is enforced: constructing a `Void` that infers something and admits
nothing raises. An outline presented without its limits reads as a recovery,
and a recovery is the one thing nobody can produce here.

### A worked example

`SYSTEM_GLOBALS` is referenced by four methods in a real GSA-lineage file and
defined nowhere in the ecosystem. From the absence alone:

    must define   current_trajectory_vectors
    must define   emergency_escalation_tier
    must define   integrity_debt_balance
    must define   system_health_index
    invariants    `integrity_debt_balance` is writable and numeric;
                  callers hold it to a floor of 0.0
    invariants    `current_trajectory_vectors` is a mapping;
                  observed keys 'Resource_Scarcity', 'System_Entropy'
    invariants    values in `current_trajectory_vectors` are numeric

    UNDETERMINABLE
      - the implementation -- what the missing code actually did, as opposed
        to what its callers required of it
      - any behaviour no surviving caller exercises
      - internal state, lifecycle, persistence, and thread-safety
      - whether the original was correct
      - what the missing thing did on write to integrity_debt_balance:
        validation, persistence, or notification would all look identical
        from here

Everything above the line is forced by the callers. Nothing below it is
reachable from any amount of further analysis.

### It does not generate code

There is no `--generate`, no `--stub`, no `--fix`, and no code-emitting export
-- asserted by a test. A file that fills the hole while carrying the name of
what was lost is indistinguishable from a recovery and is not one, and the
moment the tool can write one, somebody will commit its output as though the
original had been found.

`render()` is deliberately not valid source in any language. Someone who wants
a stub can write one from the outline in a minute; nobody can paste the
outline into a file and have it pass for what was lost.

### Not here, or not anywhere

Scanned one repository at a time, a multi-repository ecosystem reports every
sibling checkout, declared dependency and git submodule as a void. Measured on
2026-09-08 across eighteen repositories: ninety-odd voids, all true, none a
loss. The reader could not tell "not in this tree" from "not anywhere".

So the tool now classifies. An import that a sibling checkout defines, that
the project declares as a dependency (including optional extras), or that a
declared git submodule would provide is reported as **wiring**, beside the
voids, with the provider named. It is never grouped into a void and never
silenced. An import nothing known provides stays a void; when the tree
declares a submodule that is not initialised, the void says so and tells you
to initialise it and rescan before treating the module as lost.

`--ecosystem PARENT` scans every checkout under a parent directory with all
the others as siblings and reports only what nothing in the ecosystem
provides. On the governance stack that took the spine from five voids to
one, and the one it kept was the real nominal dependency the audit had found
by hand.

### What a flattened file still says

Strip every newline from a module and it stops parsing, but every token is
still there in the order it was written. `class A:` followed by three `def`s
whose first parameter is `self` is class A with three methods, each with the
parameter list and return annotation it had. The tool reads that back and
lists it under `must define`, in token order, beside the callers' evidence.
Measured on TOUCHSTONE's `quorum_state_governance_source.py` (14,162 bytes,
zero newlines): seven classes, seventeen methods and fourteen functions with
full signatures, where the previous version reported the seven class names
and "the evidence constrains no shape".

It is still an outline. Bodies are gone; a `def` inside a docstring example
looks exactly like a live one; and a method is attributed to the class that
precedes it in the text, which is right for ordinary source and wrong for a
paste that interleaved two files. All three are listed as undeterminable on
every such void. When a parsing companion sits beside the flattened file
(`x_source.py` beside `x_adapter.py`), the void says whether the companion
kept any of the class names, so an ancestor of a renamed rewrite is not
mistaken for a lost dependency.

### Sally is now Karen

Every detector above keys on the literal identifier. Rename a function and
miss one caller, or paste an older wrapper beside a newer module, and the
caller's name is a never-built void while the definition sits unrelated a
file away. So the tool also compares each undefined name against every
signature it can still see, on dimensions that do not involve the name: the
keywords the caller passes, how many values it unpacks, where those values
flow next and what type the receiving parameter declares, and which methods
it calls on the result. Two matching dimensions make a rename candidate,
listed in the undefined name's void with the reasons spelled out.

It is a hypothesis and the void says so. A coincidence of shape looks
identical, and a rename that also changed the parameters drops below the
threshold. Nothing is merged on the strength of it.

### Usage

    blackhole-extrapolator <path>
    blackhole-extrapolator <path> --sibling ../CCC --sibling ../AUGUR --show-wiring
    blackhole-extrapolator ~ --ecosystem            # every checkout under ~, each against the rest
    python -m blackhole_extrapolator <path> --json --min-confidence 0.3
    python -m blackhole_extrapolator <path> --json --show-wiring   # {"voids": [...], "wiring": [...]}
    blackhole-extrapolator ~ --ecosystem --json     # {"<checkout>": [...voids...], ...}

`shape_confidence` measures how well the evidence pins down the **outline**.
It is not a claim that a reconstruction would be correct. Those are different
questions, and conflating them turns a confident outline into a confident
forgery.
