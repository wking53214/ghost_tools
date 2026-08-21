# ghost_tools -- v0.3

Two tools, one shared finding format, built to work in tandem: `ghost_buster`
hunts down structural problems in code; `ghost_writer` turns the ones a human
decides are worth documenting (not fixing) into accurate docs.

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
```

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

### Usage

```bash
python -m ghost_writer.cli findings.json --title "Known Structural Ghosts"
python -m ghost_writer.cli findings.json --out ARCHITECTURE_GHOSTS.md
```

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

47 tests, 0 network calls, 0 API key required -- the semantic-layer tests
verify the real parsing/fail-closed/injection-fencing logic via
`StubModelClient`, the same technique `sentinel_os`'s own `interpretation/`
package uses for its model-client tests.

## Changelog

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
