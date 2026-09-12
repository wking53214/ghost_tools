# ghost_tools -- v1.5.0

A scanner that says what it could not see, and a surgeon that heals on a
branch, learns from every cut, and offers the serum only to a candidate.

    ghost-buster              things that are present and wrong
    ghost-buster --operate    the surgeon: heal on a branch, re-examine, learn
    ghost-buster --profile    work the scan did more than once
    ghost-buster --mutate     tests that pass with the thing they name broken
    ghost-triage              the human decision, recorded with its reason
    ghost-writer              the ones worth documenting
    blackhole-extrapolator    the ones that went up in smoke

## Principles

Seven rules, each one written down because a real defect happened without it.

1. **Silence is the defect.** A check that does not run says so on every
   run. A file that will not parse is a finding, not a skip. A scan reports
   what it could not see beside what it saw, because "zero findings" and
   "zero findings, having looked" print identically and only one is
   information.
2. **Fail closed.** A criterion the scan could not assess counts against
   the patient. An unreadable ledger fails the run rather than starting a
   clean history. A non-git directory is a hard stop, not a clean secrets
   scan.
3. **Say what was established, not what is suspected.** A deterministic
   check is `CONFIRMED`; a model's claim is `REASONED` and never promotes
   itself. Severity rates what the rule proved: a provider-issued key prefix
   is CRITICAL, a high-entropy string near the word "key" is MAJOR.
4. **Measured before built.** Every detector was calibrated on real
   repositories before it shipped, every exclusion was a false positive
   first, and the numbers are in `ghost_buster/calibration.json` (one
   record per detector: corpus, date, counts before and after, the named
   exclusions, and the prose account in `CHANGELOG.md`). A record with no
   corpus says so. A check that fires on nothing is not free.
5. **Memory only adds.** The ledger never suppresses a finding, never
   lowers a severity, never tunes a threshold. A self-tuning suppressor
   walks itself to silence.
6. **The tree is not modified except as declared, and that is checked.**
   One writer exists, the surgeon, and it edits comments only, on a branch
   it opened, with every edit verified by syntax-tree identity.
7. **A human decides.** Triage is the gate. Nothing is fixed, suppressed or
   documented without a recorded decision, and a prior is shown beside a
   finding, never used to hide one.

Version history lives in `CHANGELOG.md`. This file describes the tool as it
is at the version in its title.

## The surgeon

The repository is a patient on the table. The surgeon does not know what
is wrong, so the examination comes first and is complete; then diagnosis;
then, with consent, the operation; then re-examination after every cut,
because a cut can reveal the spread. The objective is to leave the patient
whole -- and, if the patient is a candidate, better than whole.

**Workup.** `ghost-buster PATH` runs every detector over one shared corpus
(every file read once, parsed once, under one policy) and reports what it
found. It also reports what it **could not** see: files that would not
parse, checks that could not run. That list is the same for every detector,
which it was not before 0.18.

**Diagnosis.** Readiness is read off the findings: parses completely, tests
run and pass, no committed secrets, not a drifted copy, no
swallowed-everything handlers, no hollow contracts. A criterion the scan
could not assess counts **against** the patient. The gate fails closed.
"No committed secrets" fails on an established credential (a
provider-issued prefix, a private key: CRITICAL); a shape-only candidate
(MAJOR) is reported beside the verdict as something to read, and a
"false" decision recorded in the case file retires it. The pre-flight
sweep found seven repositories failing this criterion on candidates alone,
none of them a credential on the evidence, which is how a gate gets
skimmed.

**Operate.** `--operate` opens a branch from a clean tree, applies every
remedy that carries a verification that can fail, re-examines after each,
commits each cut, and records what healed and what was exposed. The branch
the patient came in on is never written to, and that is checked. A dirty
tree is refused. In 1.0 one remedy qualifies -- `annotate`, whose every
edit is verified by syntax-tree identity. Everything else the toolkit finds
needs a judgement the tree does not contain and is left on the table for
you, with the evidence beside it. A remedy joins the list the day it
carries a check that can fail.

**Learn.** The case file. `ghost-triage --casefile` records each decision;
`ghost-buster --casefile` shows the history beside every finding it applies
to; every cut records its outcome. A prior never hides a finding and never
changes a severity -- it is shown beside the finding, and you decide with
both in view. Point every repository at one file and the surgeon learns
across the library. `--priors` is the view over that file: per kind of
finding, what this team has decided, how often the decision was "false",
and how often it held against what the ledger saw afterwards.

**The serum.** A candidate gets the enhancement pass: `--profile` counts the
work the scan did more than once (that is how the 9.5-parses-per-file
redundancy in this toolkit was found), and the pitstop detectors report
what the tree can see. Enhancement applied to an unhealthy patient
amplifies the rot, which is why candidacy is gated on health. No ceiling
for a candidate, so long as nothing breaks -- and the breaking is what the
checks are for.

## What runs by default

Every check is **on** unless you turn it off, and **every check reports its
state on every run** -- performed, impossible, or declined.

| Check | Default | Turn off with |
|---|---|---|
| the twenty registered detectors | on | (always run) |
| unmerged branches | on | `--no-branches` |
| test status | on, for a trusted repository (`--trust`, once) | `--no-tests` |
| committed secrets | on | `--no-secrets` |
| project checks (CI, deploy artifacts) | on | `--no-project` |
| structural model | on | `--no-structure` |
| correlation | on | `--no-correlate` |
| ledger (memory) | on | `--no-ledger` |
| cross-repository seam | asks, on a terminal; single-repo otherwise | `--join PATH` or `--single-repo` says so outright |
| shared kernel | **off** | opt-in because it needs a path: `--kernel PATH` |
| mutation (`--mutate`) | **off**, and needs a trusted repository | opt-in on cost: one pytest process per mutant |
| semantic layer | **off, and has no flag** | a library (`ghost_buster.semantic`), never wired into the CLI, because every call is paid |

The table above is the source of truth for defaults. Every flag in it exists
in `ghost_buster/cli.py` with the default shown; the `--help` text says "ON
BY DEFAULT" on each one that is.

The half that matters more than the defaults: **a check that does not run
says so.** Until v0.10.1 the repository checks were opt-in and a run that
skipped one printed nothing about it. Measured on a real repository, a scan
with `--branches --secrets` reported 34 findings and exit 1, looked like a
complete audit, and never mentioned that test status had gone unexamined --
where five clinical missed detections were sitting behind skips that
`--tests` rates MAJOR. Silence about a check is the defect; declining one
on purpose is fine, and now leaves a receipt in the output.

Two consequences worth knowing before you point this at an unfamiliar
repository:

- **A default run executes the project's test suite, once you have said
  it may.** That is what `--tests` does. The first run on a repository
  declines the test and mutation scans with a receipt naming the trust
  store; `--trust` records consent once, keyed by the `origin` remote (so
  a fresh clone of a trusted repository is trusted) or by path when there
  is none, in `~/.config/ghost_tools/trust.json` or `$GHOST_TOOLS_TRUST`.
  A file inside the repository would be the stranger's to write, so the
  store is yours. `--no-tests` still declines on purpose, with its own
  receipt, and `GHOST_TOOLS_TRUST=-` trusts everything for a harness that
  scans its own fixtures, printed on the receipt line and never silent.

  **What consent covers, exactly: a name, not a tree.** The grant is
  recorded against the remote, so it holds for every checkout of that
  remote, at any commit, with any contents, until you remove it. Pulling
  a commit does not re-prompt, a second clone inherits the decision, and
  somebody who can change what a trusted remote contains gets their code
  run by your next `--tests`. That is the same question a CI
  configuration answers when it runs a suite, and it is a different
  question from "do I trust this exact code", which would mean consenting
  per commit. If you need the stronger property today, `--no-tests`
  executes nothing regardless of consent. `ghost_buster/trust.py` states
  the model in full.
- **A default run takes minutes, not seconds**, because of that suite.
  `--no-tests` gets the old fast structural pass back.

## What it checks

Every registered detector, by name, with the severity it can reach. Each
one is documented at length further down; this table is the index, and it
is checked against `registered_detectors()` by the test suite.

| Detector | Reports | Up to |
|---|---|---|
| `unassessable_file` | a file the corpus could not read or parse, so every detector below skipped it | MAJOR |
| `merge_conflict_marker` | an unresolved `<<<<<<<` / `=======` / `>>>>>>>` triplet | CRITICAL |
| `dead_code` | a definition nothing in the scan references | MINOR |
| `dead_end_call` | a definition live code calls whose body does nothing, with no seam declared | MAJOR |
| `long_function` | a function past the length threshold | MAJOR |
| `duplicate_file` | a byte-identical file group, reported once | MAJOR |
| `drifted_copy` | the same file in several places, no longer agreeing | MAJOR |
| `near_duplicate_function` | two functions with the same structural fingerprint | MAJOR |
| `intra_function_duplicate_block` | repeated branch bodies inside one function | MAJOR |
| `swallowed_exception` | a handler that catches something and does nothing | MAJOR |
| `doc_test_count_drift` | a test count in a markdown file the real suite has grown well past | MINOR |
| `name_disagreement` | one value passed under two names, only where it is a bijection | MINOR |
| `vestigial_domain_name` | an identifier carrying a domain this repository no longer has | MINOR |
| `placeholder_name` | `foo`, `tmp`, `data2`: a name that says nothing, where that is decidable | MINOR |
| `sql_injection` | SQL built by interpolation and then executed | CRITICAL |
| `destructive_sql` | `DELETE` or `UPDATE` with no `WHERE`, or `TRUNCATE`, executed | MAJOR |
| `insecure_default` | `DEBUG = True`, wide-open CORS with credentials, `verify=False` | CRITICAL |
| `unauthenticated_route` | a route with no auth while most of its siblings have it | MAJOR |
| `loop_invariant_call` | a call inside a loop whose arguments the loop cannot change (a serum pitstop) | MINOR |
| `list_membership_in_loop` | membership tests against a list literal inside a loop (a serum pitstop) | MINOR |

Beside the detectors, six repository-level checks and two passes over
everything, each with its own section below: unmerged branches, test
status, committed secrets, the project checks (`no_ci_configuration`), the
structural model (`entry point target missing`, `undeclared dependency`),
the seam between repositories (`--join`), the shared kernel (`--kernel`:
`kernel_shadow`, `drifted_contract`), the ledger (`regressed_finding`,
`flapping_finding`, `persistent_finding`, `blind_spot`, trajectory), and
correlation (four connectors). Readiness reads six criteria off the whole
set and gates the surgeon's serum on them.

## What it remembers: the ledger

`.ghost_ledger.json` sits next to the baseline and is committed like it. Each
run in it records a digest of the baseline and the case file as that run
read them, and a link to the run before, so an edited or removed run is
visible: `ghost-buster PATH --verify-chain` recomputes every link and
names the first break. There is no key, so an editor who recomputes the
chain leaves no trace. It detects edits, not adversaries, and
`ghost_buster/attest.py` says so at length.
The baseline answers *"is this present right now"*; the ledger answers
*"what has been true over time"*. Three facts are unsayable in a set of
ids, and all three matter:

| Finding | Fires when | Why a single run cannot see it |
|---|---|---|
| `regressed_finding` | An id was present, went away, and came back | To a set of ids, a return and a first sighting are the same event. Escalates one severity level: a defect that returns means something reintroduced it and nothing stopped that. |
| `flapping_finding` | It has come and gone three or more times | Usually a non-deterministic detector, occasionally a real intermittent defect. Either way, diagnose it rather than baselining it. |
| `persistent_finding` | Open for ten consecutive runs with no decision ever recorded | Not a claim it is wrong. A claim that nobody has said either way, which is how a known problem becomes an unknown one. |
| `blind_spot` | A check has not actually run here in five consecutive runs | **The tool noticing its own coverage gap.** Severity follows the reason: declining a default-on check is a choice someone made and can unmake (MAJOR); an environment that cannot run it is a gap but not a decision (MINOR); a check that is opt-in by design was never promised (INFORMATIONAL). |

Two rules the ledger will not break:

- **It only ever adds.** It never suppresses a finding, never lowers a
  severity, and never tunes a threshold. Memory that removes signal is a
  self-tuning suppressor, and every self-tuning suppressor shares one
  gradient: fewer findings looks like success, so it walks itself to
  silence. A regression is reported *alongside* the defect it is about,
  never instead of it.
- **It records what was found, not what was reported.** Findings enter
  the ledger before the baseline diff, so `--accept` changes what you are
  shown and not what the tool remembers. Otherwise accepting a finding
  would be a way to delete history.

Run history is capped at the most recent 200 runs, with older runs
collapsing into counters, so the file stays flat in git rather than
growing without bound. Writes are atomic; a corrupt or future-schema
ledger fails the run rather than silently starting over, because an empty
history reported as a clean one is the lie this whole feature exists to
prevent.

### `--priors`: what this team has decided, and whether it held

    ghost-buster . --priors                    the view, per detector
    ghost-buster . --priors --json             the same, as data
    ghost-buster . --priors --casefile ../library.json   across the library

A scanner answers "what is here". The case file and the ledger together
answer the question a team actually has: what have we said about things
like this before, and did the world agree? Every decision recorded with
`ghost-triage --casefile` names the finding it was about and the word used
(fix, suppress, document), and the view judges each against the ledger:

| decision | held when | did not hold when |
|---|---|---|
| fix | the finding is gone and has not returned | still present (`open`), or it came back (`returned`) |
| suppress, document | nobody re-decided it | a later decision on the same finding said otherwise (`revisited`) |

A decision recorded before 1.2.0 names no finding and is `unknown`, never
counted as held; so is a fix whose finding the ledger has never seen. The
hold rate is over judged decisions only. Beside the verdicts, the three
most recent reasons, because a reason is what the next person needs.

## An archive is not a patient: `.ghost_archive`

A repository that exists to hold history (a corpus, an export, specimens
kept flattened on purpose) fails "parses completely" forever, and a gate
that keeps saying so is a gate nobody reads. A committed `.ghost_archive`
file at the root, whose text is the reason, makes the scan report findings
as before and stop there: candidacy is not assessed, the surgeon refuses
to operate, and the receipt line names the archive and its reason on every
run, so an archive cannot be mistaken for a repository nobody has looked
at. The marker is a decision recorded in the tree and reviewed like any
other change. Nine repositories in the library carry one (2026-09-11).

## Files that will not parse: `unassessable_file`

`unassessable_file` is borrowed, knowingly, from a pediatric sepsis
engine. `observe-perceive`'s `BayesianFusion` carries this comment,
written after a real defect:

> An engine that returns `abstained=True` is saying "I have no data to
> assess this patient" -- which is fundamentally different from "this
> patient looks stable." Previously, three low-confidence abstentions
> could outvote a single high-confidence septic-shock detection.

ghost_buster had the same bug in different clothes. `_parse()` returns
`None` for a file it cannot read, every AST detector skips that file, and
the run said nothing at all. Measured on three files -- one clean, one
with conflict markers, one with a syntax typo -- the typo file produced
no findings whatsoever, its dead function invisible, while the header
still reported "scanning 3 file(s)". Silence read as all-clear.

Every detector still fails closed on a file it cannot parse, which is
correct. What was wrong is that nobody was told. An abstention is now a
MAJOR finding naming the file and the reason, because a file that will
not parse is usually broken right now, which is the worst possible moment
for every structural check to look away.

## The founder checks

Three checks built from research into what actually bites solo and
early-stage teams. Each is deliberately narrower than its category name,
because a security check people learn to skim is worth less than none.

| Check | Fires when | Severity |
|---|---|---|
| `no_ci_configuration` | a deploy artifact ships this code and no CI runs first | MAJOR |
| | test files exist and no CI runs them | MINOR |
| `insecure_default` | `DEBUG = True`, `run(debug=True)` | CRITICAL |
| | CORS allows every origin **and** credentials | CRITICAL |
| | `ALLOWED_HOSTS = ["*"]`, `verify=False` | MAJOR |
| `unauthenticated_route` | a route has no auth while most of its siblings do | MAJOR |

**What each one refuses to say** is the design:

- **Not "this repo has no CI".** Plenty of repositories are fine without
  it: a scratch pad, a spike, a corpus. The claim is narrower and about
  work already wasted -- you wrote tests and nothing runs them -- or about
  a deploy with no gate in front of it.
- **Not "probably insecure".** Every rule is a construct with essentially
  one meaning, and each is skipped inside test files where being
  permissive is usually the point. Wide-open CORS *without* credentials is
  a normal public API and is not reported. Measured across three real
  repositories: zero findings.
- **Not "routes with no auth".** That version is unusable: a login
  endpoint has no auth by definition, and so do signup, health probes,
  webhooks, OAuth callbacks, and every endpoint of every public API. What
  is reported is the INCONSISTENCY -- a handler whose siblings are nearly
  all protected, meaning the author already decided this router needs a
  caller identity and this one does not say so. A fully public module is
  silent; a fully protected module is silent; auth applied by middleware
  makes every route look unprotected, which drops the module below the
  threshold and reports nothing. It fails quiet, deliberately.

## The structural model: `--structure`

`ghost-buster --structure-report` reconstructs what a repository actually
is, from evidence only: the packaging and distribution boundary, every
importable module, every execution entry point, the import topology split
into internal and external, which external boundaries each module actually
crosses, module-level mutable state, declared public surface, data
representations, test modules, and **an explicit list of what could not be
resolved statically**. `--structure-out FILE` writes the same model as JSON.

Two findings fall out of it, and each is a contradiction between two
observed facts rather than a judgement:

| Finding | Fires when |
|---|---|
| `entry point target missing` | a console script points at a module or symbol that does not exist |
| `undeclared dependency` | a package is imported, resolvable to a distribution, and declared nowhere |

### What it refuses to say

The specification this implements forbids inferring an architectural
boundary from a conventional directory name -- `services/`, `adapters/`,
`core/`, `utils/`. That rules out the only mechanical route to one. So the
model does not claim which modules are domain logic, orchestration,
infrastructure or presentation, and the report says so in as many words.
A name is a claim its author made, not a fact about the code, and it is
precisely the thing worth checking this model against.

### Two measurements that changed the design

**A bare `pathlib` import is not a filesystem boundary.** 37 of this
project's 68 modules import it and most only manipulate paths. Boundary
detection is call-based where the import is noisy (`read_text`, `open`,
`os.environ`) and import-based only where it is unambiguous (`socket`,
`subprocess`, `sqlite3`).

**An import name is not a distribution name.** `yaml` ships in PyYAML,
`PIL` in pillow, `ccc` in cognitive-continuity-constitution. Comparing
import names directly against declarations reported six packages as
undeclared on a real repository that declares every one of them. Imports
are now mapped through installed distribution metadata, and an import that
cannot be mapped goes to `unresolved` rather than becoming a finding --
because a missing declaration and an ordinary alias look identical.

## The seam between two repositories: `--join`

A cross-repo boundary is the one place both sides are blind. The importing
repository guards the import and skips its tests when the other is absent,
so its CI never runs the seam. The providing repository has never heard of
the importer. The contract is verified at exactly one moment: when
somebody joins them.

    ghost-buster . --join ../CCC --join ../Conservation_Kernel

| Finding | Fires when | Severity |
|---|---|---|
| `cross repo import unresolved` | A imports a name B does not export | CRITICAL |
| `boundary symbol untested` | a symbol crosses the seam and **no test in either repo mentions it** | MAJOR |
| `boundary provider absent` | A reaches for a package nothing in the join provides | MINOR |
| `dormant boundary test` | inventory of tests waiting for the other side | INFORMATIONAL |

`boundary symbol untested` is the mechanical form of **"is a new test
needed here"**. A dormant test counts as coverage: a test written for the
seam and guarded the same way the import is lies dormant alone and runs on
join, which is exactly right and strictly better than no test.

### Single repo or joined

`--join PATH` says so outright, and `--single-repo` says so outright. With
neither, it **asks** -- but only when stdin is a terminal. A prompt in CI
hangs the build forever, and a tool that hangs a build gets removed from
the build, so a non-interactive run scans one repository and says on the
receipt line that it did.

A single-repo scan that is looking at half a system says so:

    this repository reaches for 6 package(s) it does not provide
    (augur, ccc, conservation_kernel, fortress_unified, gems ...) and holds
    8 dormant test(s). Those seams are UNCHECKED in a single-repo scan --
    re-run with --join <path-to-each> to verify them.

### What it cannot check

Duck-typed contracts. One real adapter states its own: "CCC's intake is
structural: anything carrying .conclusion, .method, .source_material ...
can be recorded." No static analysis resolves that, and pretending
otherwise would be inventing evidence, so those go to `unresolved`, named.

## The shared kernel: `--kernel`

When a library extracts the contracts its repositories agree on into one
package, the repositories that still carry their own copy are the
migration's remaining work, and no single-repository scan can see them:
`drifted_copy` compares files inside one tree, and the kernel lives in
another.

    ghost-buster . --kernel ../cns

Every top-level class in the kernel is hashed by structure with its
docstrings stripped (the `ast.dump` hash `drifted_copy` uses, so a comment
or a reformat does not register and a changed condition does). A class in
the scanned tree with the same name is one of three things:

| shape | finding | severity |
|---|---|---|
| identical | `kernel_shadow`: import it instead | MAJOR |
| same name, most members shared, different structure | `drifted_contract` | MAJOR |
| same name, little else | nothing, and counted on the receipt line | |

The third row is the calibration. The overlap gate compares method names
when the kernel class has any, and class-level names (an Enum's members, a
dataclass's fields) when it has none, so an enum with a member added is a
drifted contract and a `Node` in a tree-drawing module is not a copy of a
graph kernel's `Node`. A kernel checkout sitting inside the scanned tree (a
vendored copy, a submodule) is skipped: a kernel that shadows itself is the
tool reporting its own argument. Disclosed scope: a member-less class with
a different base (`class ValidationError(Exception)` beside the kernel's
`class ValidationError(GovernanceError)`) has nothing to compare and is
counted as a coincidence.

**Measured before it shipped**, with a 24-class kernel against 37
repositories: 64 shadows (34 in one repository that vendors the kernel's
source of origin, 16 in another), 30 drifted contracts, 10 same-name
classes left silent. The method-or-members gate came from that run: on
methods alone, four `Graph` copies that declare their fields in `__init__`
read as coincidences; on members alone, an enum family read as
coincidences instead.

## What AI-written code gets wrong

Three checks built from 2026 research into AI-generated code, where 45%
of output carries a security flaw and agency audits find 8 to 14 issues
per vibe-coded app.

| Check | Fires when | Severity |
|---|---|---|
| `sql_injection` | SQL built by f-string, concatenation, %-formatting or .format() **and then executed** | CRITICAL |
| `destructive_sql` | `DELETE`/`UPDATE` with no `WHERE`, or `TRUNCATE`, in an executed literal | MAJOR |
| `unresolvable dependency` | a package imported unguarded that refers to nothing findable | MAJOR |

### SQL injection is unusually clean to detect

The safe form and the unsafe form are different AST **shapes**, not
different values:

    execute(f"SELECT * FROM t WHERE id = {uid}")     # one argument, built
    execute("SELECT * FROM t WHERE id = ?", (uid,))  # two, parameterised

No threshold, no heuristic, no guessing at intent. A literal is fine
however it is written; interpolation into a statement that is executed is
the finding. `execute` is not a database-only method name, so a task
runner's `task.execute(f"step {n}")` stays silent -- the string has to
open with a SQL statement keyword.

### The slopsquat surface

The 2026 attack. A model asked for working code emits an import for a
package it invented; [USENIX tested 16 models over 576,000 samples](https://socket.dev/blog/slopsquatting-how-ai-hallucinations-are-fueling-a-new-class-of-supply-chain-attacks)
and found 38% of hallucinated names are conflations of two real packages,
13% typo variants, 51% pure fabrication. Because the names are
predictable, attackers register them and wait. In January 2026 a
hallucinated npm package spread through 237 repositories with nobody
planting it.

**The discriminator is the guard.** A hallucinated package is imported
*unguarded*, because the model believes it is real. A genuinely optional
dependency is wrapped in `try/except ImportError` by an author who knew it
might be absent -- and `--join` already reports those as
`boundary provider absent`. Without this distinction, three of one real
repository's sibling packages were reported as invented names.

Measured across five real repositories: **zero findings**, while the
canonical `express_mongoose` conflation still fires.

## Install

```bash
python -m pip install ghost-tools                                   # a released version, from PyPI
python -m pip install "git+https://github.com/wking53214/ghost_tools"  # main, as it sits
ghost-buster /path/to/repo      # every check, on by default
ghost-buster --version          # what you are running
```

Releases are version tags (`v1.0.7`); a tag publishes to PyPI through the
`publish` workflow with no stored token, and the tag has to name the
version `pyproject.toml` declares or the workflow refuses.

This repository scans itself on every push (the `self-scan` job). The
committed baseline holds MAJOR findings only, two of them as of 1.2.2, each with its
reason in `.ghost_casefile.json`; everything MINOR is reported on every run
and gates nothing, and a test fails if a baseline entry goes stale.

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

### Gathering and presenting are two modules

`ghost_buster/pipeline.py` gathers; `ghost_buster/cli.py` presents.
`gather(args)` runs every check the arguments ask for and returns an
`Evidence` record: the files read, the findings, the state of each check,
and the reports the human output renders. Everything after that call in
`main()` is interface -- the baseline diff, what to print, and what to
exit with.

The split exists because `cli.py` had grown to 795 lines around a
285-line `main()` that did all of it, which the tool's own
`long_function` detector rated MAJOR on its own source. `gather` reports
through an injected `say`, so nothing in the gathering stage can put
prose on stdout, where `--json` is read. It is a sequence of five named
stages in the order they run:

| stage | what it does |
| --- | --- |
| `_run_opt_in_analyses` | `--mutate` and `--kernel`, the two checks that cost enough to be off by default |
| `_run_model_checks` | `--join` (the cross-repository boundary) and `--structure` |
| `_run_repository_checks` | `--branches`, `--tests`, `--secrets` |
| `_correlate` | connects findings to each other and to prior runs; reads, never scans |
| `_record_in_ledger` | folds the run into the history, then derives what the history says |

## ghost_buster

Two layers, six repository-level checks, a ledger, and a correlation pass
over all of them, every one producing the same `Finding` shape
(`ghost_buster/schema.py`). The full inventory is the table under **What it
checks** above; what follows is the reasoning behind each, in the order it
was built.

- **Mechanical** (`ghost_buster/mechanical.py` and the modules beside it)
  -- deterministic, AST-based, stdlib only. Every finding is
  `Status.CONFIRMED`; there's nothing to doubt about a deterministic check.
  The first seven, and what calibrating each on a real repository taught:
  `dead_code`, `long_function`, `near_duplicate_function`,
  `intra_function_duplicate_block`, `doc_test_count_drift`,
  `merge_conflict_marker`, `duplicate_file`.

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
  matter. Until v0.9, most of what this flagged was pairs and runs of
  similar statements inside ONE block -- an `__init__` assigning seven
  attributes, a dict built one entry per line, adjacent `assert` lines in
  a test: 643 of 655 findings on the first whole-library run (37
  repositories). That is how code is written, not a ghost, and it is not
  the shape the detector was built for. Two calibrations, each measured
  on the library before adoption: a single statement now counts as
  repeated only across DISTINCT statement lists (different branch
  bodies), and the single-statement complexity floor is 20 nodes rather
  than 15 -- the original gate.py's four branch returns measured 41, 26,
  33 and 22 nodes, so 20 keeps all four where 25 would have lost one.
  Library findings went from 1,300 to 221, MAJOR from 215 to 46;
  multi-statement block findings were unchanged (30 before and after,
  every one a real repeated branch body).

  `near_duplicate_function` was recalibrated on the same run. Sampling
  its pairs by hand found the dominant case was not two similar functions
  but one file present twice -- a module vendored verbatim from a sibling
  repo (sentinel_os and gsa-815 share `queue_staffing_bayes_integration.py`;
  sentinel_os and observe-perceive share `perceive_consolidated.py`), a
  committed `-1` or ` (1)` download copy, or a symlinked file listed under
  both names -- so every function in the file fingerprinted against its
  own twin. Three changes: `duplicate_file` (v0.9) reports a byte-identical
  group ONCE, as the MAJOR finding it is (whichever copy gets the next
  fix, the other won't), and `near_duplicate_function` fingerprints each
  such group's functions once; `min_lines` is 10, not 6 (nothing sampled
  in the dropped band was more than two short functions sharing a shape);
  and a cluster made only of test functions is `INFORMATIONAL`, never
  `MAJOR`, since test functions sharing a setup/assert shape is what a
  suite looks like. Library findings went from 625 to 248, MAJOR from 77
  to 27, plus 31 `duplicate_file` findings that had been hiding inside
  them. Empty files are never a `duplicate_file` group (4 of the first 35
  were pairs of empty `__init__.py`). The CLI also now collects each real
  path once and skips `build/`, `dist/` and `*.egg-info/` -- a stray
  wheel-build `build/` on this repo's own checkout had been producing 113
  near-duplicate findings, every module against a copy of itself.

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

  `merge_conflict_marker` (v0.8) is the one detector here that deliberately
  does NOT go through `ast.parse()`. A file with a genuine, unresolved
  `<<<<<<< / ======= / >>>>>>>` triplet still in it is, in almost every
  case, no longer valid Python -- the marker lines are not legal syntax --
  so an AST-based version of this check would find nothing in exactly the
  files most likely to have the problem. It reads the file as plain text
  instead, `Severity.CRITICAL` on a match, and requires the full triplet
  in order rather than any one marker line alone: a lone `=======` is a
  real false-positive risk against a Setext-style Markdown H1 underline
  (any run of `=`, coincidentally 7 long often enough to matter), the
  same reason the widely-used `pre-commit-hooks` project's own
  check-merge-conflict hook requires the same shape. Confirmed by running
  it against its own module and test files after writing them: it does
  not self-flag on its own documentation, which discusses the marker
  strings in prose throughout.
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
- **Unmerged branches** (`ghost_buster/branches.py`, `--branches`) --
  neither mechanical nor semantic in the file-content sense (there is no
  file to parse and no judgment call to make), but deterministic and
  `Status.CONFIRMED` like the mechanical layer, so it produces the same
  category of finding through a different modality: read-only `git`
  plumbing against the checkout as it sits, never a fetch, a push, or a
  write. Flags a local or remote-tracking branch whose commits are not
  reflected in the base branch.

  The obvious approach -- is the branch an ancestor of base? -- is wrong
  by itself: a squash merge (GitHub's default merge button) rewrites a
  branch's whole history into one new commit on base, so the branch tip
  is never an ancestor of anything again, even though every line it
  changed landed. An ancestor-only check flags every squash-merged branch
  as unmerged forever. Confirmed directly against this project's own
  history before this detector existed: four of ghost_tools' own,
  already-squash-merged branches would have been false positives. The fix
  is a whole-branch patch-id comparison (see the module docstring for the
  exact mechanism) against every commit base picked up since the branch's
  merge-base -- a squash commit's diff is exactly the union of what the
  branch changed, so its patch-id matches.

  Two disclosed blind spots, not fixed because fixing them means the
  network calls this whole layer exists to avoid: it cannot see a
  branch's pull-request state at all (open, rejected, or never opened all
  look identical to a flagged branch here), and a remote-tracking ref
  already deleted on GitHub still reads as unmerged until the checkout
  re-fetches with `--prune` -- measured directly: this project's own four
  already-squash-merged branches, fetched once outside the checkout's
  configured refspec, kept showing up as findings because neither an
  ordinary fetch nor `--prune` touches a ref outside that refspec.
  Findings flow through the same `Finding`/baseline pipeline as every
  other detector, so a long-lived branch someone wants to keep can be
  accepted into the baseline like any other finding. The first run across
  the whole library (37 repositories, v0.8.1) found two defects in this
  check and fixed them the same day: a non-UTF-8 diff crashed the scan,
  and `refs/remotes/origin/HEAD` was counted as a phantom branch on every
  clone-shaped checkout. Both are in the CHANGELOG with the measurement
  that found them.

  `Tests/test_branches.py` builds real git repositories in `tmp_path` (a
  ref-graph check has no honest way to be tested against parsed strings)
  covering fast-forward merges, squash merges, a squash merge with
  further commits on base afterward, a branch that diverges further after
  its own squash landed, a branch whose commits net to zero diff, local
  and remote-tracking copies of the same branch, and an explicit
  `--branches-base` override. `ghost-buster --mutate` finds no candidate
  in it (the same "well-shaped, therefore unexamined" situation the other
  hand-mutant suites exist for); `Tests/test_branches_mutants.py` breaks
  the detector twelve ways in a scratch copy and requires each mutant to
  fail a test, naming the two mutants from its own exploratory run that
  turned out not to be real gaps (a documented-redundant fast path, and a
  no-op from `git merge-base`'s documented argument symmetry) rather than
  forcing tests to exist for them.
- **Test status** (`ghost_buster/testsuite.py`, `--tests`) -- runs the
  project's own pytest suite and reports every test that did not pass,
  classified by what the outcome means rather than by pytest's four
  words for it. On by default, and it executes the project's code, so
  `--no-tests` on a tree you do not trust; it never
  installs a package, starts a service, or sets a variable, and the scan
  itself writes nothing into the project (no cache, no bytecode -- the
  project's tests may still have their own side effects; sentinel_os's
  leave a `fortress_audit.log` behind).

  A test that fails every time is a **failing test** (MAJOR). A test that
  fails in the suite and passes when rerun alone, up to `--tests-reruns`
  times (default 3, stopping at the first pass), is **flaky** (MAJOR):
  order-dependent, polluted by another test, or intermittent, and either
  way not believed when it fails. A test that fails because the
  environment lacks something it needs is **blocked** (MINOR), and the
  finding names what: a service that refused the connection, a module
  that is not installed, an environment variable that is not set, an
  executable that is not on the machine. Blocked tests are not rerun; a
  missing service does not appear between attempts. A skipped test has
  nothing to rerun, so its reason is read instead: a reason naming an
  external dependency is recorded as INFORMATIONAL so the count stays
  visible; a skip with no reason, or a reason like "TODO" or "broken"
  that names nothing the environment could provide, is MAJOR (a test
  switched off, not a test waiting); and a skip whose named module or
  variable is actually present when the scan runs is a **stale skip**,
  MAJOR (the dependency arrived and the test never came back). An
  `xfail` that passes is a stale expectation, MAJOR. A test module that
  cannot be collected is reported like a failing test, or as blocked when
  the import names a missing dependency.

  Outcomes are read through a small pytest plugin (written to a temporary
  directory, loaded with `-p`) that records one JSON line per test
  phase, the same hook pytest's junit writer uses; the terminal summary
  is never parsed and the junit XML does not carry node ids, which the
  reruns need. `--tests-python` points the run at the project's own
  virtualenv so it executes with its own dependencies.

  Whether a failure is "external" is a heuristic over text, and the
  vocabulary was calibrated on four real suites before this shipped,
  each change measured: a named module that exists as a file inside the
  project reads as a **path defect** (MAJOR, with the file's location)
  rather than a missing dependency -- gsa-815's 17 uncollectable test
  modules first looked like that case and turned out not to be (its
  `DEPENDENCIES.md` lists the missing modules as owed by a sibling
  repository, so blocked is the right reading and the rule correctly
  stays silent there; it is pinned by a fixture with a real
  repository-local module instead); observe-perceive's 47 skips of the
  form "AUGUR checkout not available"
  read as naming nothing until a resource pattern existed; sentinel_os's
  18 setup errors on a missing `/usr/local/bin/twin_ensure_services` read
  as failing until an absolute path under a system executable directory
  counted as a tool (a missing relative fixture file still does not: that
  is the repository's own defect). Failure text is classified only from
  its error lines, never the source pytest walked to reach them, because
  a genuine assertion failure in `test_server.py` mentions "server" on
  every line. The remaining blind spots are stated in every finding that
  depends on them: a failure reported as a bare assertion whose real
  cause is a missing service reads as failing, a named service cannot be
  probed for reachability and is not, and a skip condition is not parsed
  (only its reason is read).

  `Tests/test_testsuite.py` builds real pytest projects in `tmp_path`
  covering every shape above, plus the did-not-run cases (no tests, an
  interpreter without pytest, a suite that exceeds `--tests-timeout`) and
  a check that the scan leaves no cache or bytecode behind.
  `Tests/test_testsuite_mutants.py` breaks the scanner twenty-two ways and
  requires each to fail a test; its first exploratory run found one
  survivor (classifying the whole traceback instead of its error lines
  changed nothing the fixture project could see), fixed by adding the
  discriminating shape to the fixture before this shipped.
- **Committed secrets** (`ghost_buster/secrets.py`, `--secrets`) --
  shells out to [gitleaks](https://github.com/gitleaks/gitleaks) (must be
  installed separately; nothing here installs it) against the checked-out
  branch's git history, the same repository-level-check shape as
  `--branches`: no file content to parse on its own terms, but
  deterministic, so `Layer.MECHANICAL` / `Status.CONFIRMED` like every
  other detector here. Every finding is `Severity.CRITICAL`: a leaked
  credential is dangerous the moment it exists, full stop.

  Scans history, not just current file content, on purpose: a secret
  "removed" in a later commit by deleting the line is still sitting in
  the repository's history, readable by anyone who can clone it. Only
  rewriting history (and rotating the credential) removes it; scanning
  current files the way every mechanical.py detector does would pass a
  repository clean that leaked a key three commits ago and "fixed" it by
  deleting the line. Only the checked-out branch's own history is
  scanned, not every branch -- the same read-only, no-fetch scope
  `--branches` already commits to.

  The secret value itself never reaches a finding. gitleaks is run with
  `--redact` (confirmed directly: its `Secret` and `Match` fields come
  back as the literal text `REDACTED`), and this module goes one step
  further and never reads either field at all -- only the rule id,
  description, file, line, column, commit, and gitleaks' own fingerprint
  ever reach a `Finding`. This matters beyond caution: a finding is
  written into `.ghost_baseline.json` the moment someone runs `--accept`,
  and that file is meant to be committed, so a secret reaching a finding
  would mean committing the leak a second time inside the file whose
  whole purpose is to make findings inert.

  A non-git directory is a hard stop, not a clean scan -- measured
  directly: gitleaks itself, given one, logs an error to stderr but still
  exits 0 and writes an empty report, indistinguishable by exit code or
  content from a real clean scan. This module checks `git rev-parse
  --git-dir` itself before ever invoking gitleaks, the same defense
  `branches.py`'s non-UTF-8-diff history exists to demonstrate the need
  for. A repository's own `.gitleaksignore` or `.gitleaks.toml`, if
  either exists, is honored by gitleaks exactly as it would running
  standalone (confirmed directly: a fingerprint listed in
  `.gitleaksignore` drops that finding before this module ever sees it);
  no suppression logic beyond the shared baseline lives here.

  Dogfooded across 33 repositories before shipping. One real defect
  found and fixed the same way: the first pass gave gitleaks `--source
  <root>` while also setting the subprocess's own working directory to
  `root`, so a relative root resolved twice (`root/root`) and the scan
  failed outright for several repos instead of silently misreading them
  -- still a real bug, fixed by resolving the root to an absolute path
  once at the top of `scan()` and dropping the redundant `cwd`. After the
  fix, 31 of the 33 scanned (two transcript archives exceeded the ad hoc
  180-second sweep timeout; the shipped default is 300), 25 were clean and
  6 had findings: 31 `generic-api-key` matches, almost all inside test
  fixtures and a training corpus, and 2 `private-key` matches -- one
  genuine committed TLS private key (`sentinel_os/certs/key.pem`, also
  present in a second repository that vendors a copy of it) -- exactly the
  shape this detector exists to catch, not a hypothetical.

  `Tests/test_secrets.py` builds real git repositories in `tmp_path`
  against the real gitleaks binary (skipped if it is not on PATH; CI
  installs a pinned version) covering a secret still exposed after
  removal from HEAD, deduplication of an untouched line across later
  commits, two distinct commits of the same secret value staying two
  findings, two distinct secrets on one line staying two findings
  (gitleaks' own fingerprint does not include column, so this collided
  without it), `.gitleaksignore` suppression, and the relative-root
  regression above. `Tests/test_secrets_mutants.py` breaks the wrapper
  fourteen ways and requires each to fail a test; one mutant from its own
  exploratory run (dropping `--redact`) is documented, not forced, since
  no field it touches is ever read into a finding regardless.

- **Correlation** (`ghost_buster/correlate.py`, on by default,
  `--no-correlate` opts out) -- connectors: findings that only exist when
  two detectors are read together. Every detector here is deliberately
  independent, which is what makes each one testable and each finding
  traceable to one cause, but it leaves a class of problem whose evidence
  is split across two of them and which neither can state alone.

  A connector is a pure function over the findings a run already produced.
  It parses nothing, runs no subprocess, reads no files, and produces
  nothing when its inputs are absent, so it is free and silent on a
  default scan. Four ship:

  | connector | joins | says what neither input can |
  |---|---|---|
  | `secret_in_duplicated_file` | `committed_secret` + `duplicate_file` | the credential is in N files, so purging one history leaves it live in the rest |
  | `secret_in_multiple_repositories` | `committed_secret` + another repo's `--json` | the same leak, by gitleaks' own fingerprint, in more than one repository |
  | `conflict_marker_breaks_tests` | `merge_conflict_marker` + `test_status` | one unresolved marker is why N tests cannot run, rather than N independent broken tests |
  | `doc_count_contradicted_by_run` | `doc_test_count_drift` + the `--tests` run | the measured collected/passing counts, closing the loop the static detector's own detail says to close by hand |

  Correlations are **additive**: the inputs stay, each independently true
  and independently actionable, and every correlation names the findings
  it was built from by id. They join on `Finding.attributes` -- structured
  keys each detector publishes (a gitleaks fingerprint, a content hash, a
  pytest node id) -- never on summary prose, because a reworded summary
  would switch a connector off silently, and failing quiet is the failure
  mode this project treats as worse than crashing. Only `CONFIRMED`
  findings are eligible (a deterministic fact joined to an unverified LLM
  claim is neither), and connectors never read their own output.

  Building this surfaced a real defect it then fixed: `Evidence.
  related_files` was written straight from the scan's absolute paths while
  every other path was project-relative, so a committed baseline carried a
  home directory and `certs/key.pem` could not be joined against its own
  twin. `duplicate_file`'s summary had the same problem, which put an
  absolute path inside a finding id -- the exact defect `_portable_path`
  exists to prevent. Both are now portable; `duplicate_file` ids change
  once as a result (re-accept the baseline), and a test pins that the same
  two files scanned from two different checkout locations produce the same
  id.

  A finding id hashes the detector, the project-relative path and the
  summary, and deliberately not the line, so an id survives its finding
  moving down a file. The cost of that choice is that two findings which
  agree on all three share an identity, and measurement found it real: on
  the 38-repository library, 8 pairs of findings shared an id, one pair
  two separate committed secrets four lines apart in one fixture. Since
  1.3.0 every scan separates them before the ledger or the baseline sees
  them. The first occurrence keeps the id it always had; a later one at a
  different place takes a `-2` suffix. A finding reported twice from the
  same place is still one finding and keeps one id.

  Dogfooded on the live case that motivated it: a committed TLS private
  key in `sentinel_os/certs/key.pem`, also present in `observe`, which
  vendors a copy. Two separate scans previously reported two unrelated
  CRITICALs with nothing saying they were one credential;
  `secret_in_multiple_repositories` now matches them on gitleaks'
  fingerprint and says so, and four `secret_in_duplicated_file`
  correlations fired within `observe` besides.

  `Tests/test_correlate.py` gives every connector both directions -- it
  fires on the shape it exists for, and stays silent on the near-miss that
  shares part of that shape (a marker in a different file, a secret whose
  file has no twin, a different fingerprint, a suite that never ran).
  `Tests/test_correlate_mutants.py` breaks the layer twenty ways, mostly
  by loosening a join or dropping a guard, and requires each to fail a
  test; one mutant is documented rather than forced, being a cost guard
  whose removal changes nothing observable.

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

# the three repository checks run by default. Unmerged branches: read-only
# git plumbing, never fetches, base is the first of origin/main, origin/master,
# main, master that resolves.
python -m ghost_buster.cli /path/to/repo --branches-base origin/develop
python -m ghost_buster.cli /path/to/repo --no-branches

# test status runs the project's pytest suite and classifies every test that
# did not pass (failing / flaky / blocked by a named dependency / skipped
# without cause / stale skip). It executes the project's tests, so decline it
# on code you do not trust; it never installs or starts anything.
python -m ghost_buster.cli /path/to/repo --tests-python /path/to/repo/.venv/bin/python --tests-reruns 5
python -m ghost_buster.cli /path/to/repo --no-tests

# committed secrets: the checked-out branch's git history, through gitleaks
# (must be installed separately; never installed by this tool). Read-only:
# never rewrites history, rotates a credential, or writes into the target.
python -m ghost_buster.cli /path/to/repo --secrets-binary /opt/gitleaks/gitleaks
python -m ghost_buster.cli /path/to/repo --no-secrets

# the fast structural pass: everything that reads the tree, nothing that
# runs it or shells out
python -m ghost_buster.cli /path/to/repo --no-tests --no-secrets --no-branches

# correlation runs by default and needs no flag. To let the cross-repository
# connectors fire, hand it another repo's --json output; LABEL= names it in
# the report. --no-correlate skips the pass entirely.
python -m ghost_buster.cli /path/to/other --json > /tmp/other.json
python -m ghost_buster.cli /path/to/repo --correlate-with other=/tmp/other.json
```

### `drifted_copy`: the same file in several places, no longer agreeing

`duplicate_file` groups by content hash, so it finds copies that are
byte-identical and nothing else. **It goes quiet at exactly the moment the
problem begins** -- somebody fixes a bug in one copy, the hashes diverge, and
the group vanishes from the report.

Measured across 24 live repositories: **111 file groups share a complete
top-level name set, and 29 of those have drifted.** None of the 29 was
visible to anything in the toolkit.

Two files are "the same file" when their top-level definitions have the same
names, all of them, at least three. Equality rather than overlap, because two
modules sharing three helper names is a coincidence and two sharing all
fourteen is a copy. Drift is measured per definition by structural hash
(`ast.dump` without attributes), so reformatting and comments do not register
and a changed condition does. The split is the finding:

| evidence | category | severity |
|---|---|---|
| every definition structurally identical | `duplication` | MINOR, a tidiness problem |
| some definition differs | `parallel_implementation` | MAJOR, a fix that did not propagate |

That second row filled an empty slot. Until now `parallel_implementation`
had exactly one producer, `semantic.py`, whose findings are REASONED by
construction because an LLM made them. This is the mechanical half, and it
is CONFIRMED because a structural hash either matches or it does not.

What it found immediately:

```
GSA_Governance_Operating_Core_Enterprise.py   3 copies, 97 shared names, 1 differs
ast_graph_extractor.py                        5 copies, 6 shared names, all 6 differ
citadel_v1.1_copy1 / _copy2 / v1.2            3 copies in ONE repo, all 5 differ
cassette_interface.py, cassette_schema.py     drifted between two sentinel_os copies
```

Byte-identical groups are deliberately not repeated here; that is
`duplicate_file`'s finding, for the same reason `duplicate_file` was given a
group of its own in v0.9. And it does not guess intent: a `_v1.1` beside a
`_v1.2` may be a deliberate archive. It says which definitions stopped
matching and leaves the judgement where it belongs.

### `swallowed_exception`: a handler that catches something and does nothing

The same argument `dead_end_call` makes, one level down. Something went
wrong, something caught it, nothing happened, and the operation reports
success:

```python
try:
    publish(decision)
except Exception:
    pass
```

That is not error handling. It is the removal of error handling written in
a shape that looks like error handling, which is why it survives review.

**Breadth sets the severity, because swallowing is sometimes correct.**
`except ImportError: pass` hides one class of failure and is usually the
intended behaviour for an optional dependency. `except Exception: pass`
hides the missing dependency *and* the typo, the None, the failed write, and
the bug introduced next year. So bare `except` and `Exception` /
`BaseException` are MAJOR; a named narrow exception is MINOR.

Measured: **32 in live code, 13 catching bare `Exception`**, in ANVIL, CCC,
Ecology and AUGUR. A further 22 are in test files and are not reported --
best-effort cleanup in a teardown is ordinary, and `is_test_path` is shared
with the naming and dead-end detectors so all three agree on what a test is.

Disclosed scope: only `pass`. A handler whose body is `continue`,
`return None` or a lone `logger.debug(...)` swallows just as thoroughly, and
each needs its own measurement first -- a `continue` in a retry loop is often
exactly right. `contextlib.suppress` is never flagged: it says in its own
name what it does.

### `dead_end_call`: a door somebody opens onto nothing

`dead_code` next door answers the opposite question. It finds a definition
**nobody references**. This one finds the definition everybody references
whose body does nothing, and its whole job is telling that apart from the
thing it most resembles:

> A **seam** is inert on purpose. An abstract method, a Protocol, a plugin
> interface: it has no body because the body arrives from somewhere else,
> and being empty is the design.
>
> A **dead end** is inert because nothing ever arrived. Live code calls it,
> the call returns, and nothing happened.

Both are empty. The difference is not in the body, it is in whether anything
in the world is arranged to fill it, and that is decidable, because a seam
**declares itself**:

| declared by | what that looks like |
|---|---|
| inheritance | an `ABC`, `ABCMeta` or `Protocol` base |
| decorator | `@abstractmethod`, `@abstractproperty` |
| use | a subclass anywhere in the scan that overrides it with a real body |

Anything with none of those, called by non-test code, is reported. The five
empty shapes are `pass`, `...`, docstring-only, `return None`, and
`raise NotImplementedError`.

**Silence is worse than a crash.** A raised `NotImplementedError` reached at
runtime stops and names itself, so it is MINOR. A `pass` reached at runtime
lets the caller believe the work happened, which is the difference between
"the check passed" and "the thing works", so the silent shapes are MAJOR.

**It cannot say "never", and does not.** Nothing static proves never. The
finding says what the evidence supports: nothing in the scanned set provides
a body and nothing declares an intent to. An implementation in a repository
this scan was not pointed at would settle it, which is what
`blackhole-extrapolator --sibling` exists for. It also cannot say which
object a call landed on, the same disclosed limit `dead_code` carries: this
is AST-only with no type resolution, so "something calls `execute`" means
the name is called somewhere.

**Measured before it was built.** Across 24 live repositories and 1,562
files: 162 callables whose body does nothing, 31 with no override in their
own repository, 11 called by live code. Ten of the eleven were deliberate,
so every exclusion below was a false positive first:

| excluded | measured case |
|---|---|
| Null Object and no-op conventions (`Null*`, `NoOp*`, `Fake*`, `Stub*`, `Dummy*`, `Mock*`, on a word boundary) | `NullTelemetrySink.record`, `_NoOpSpan.set_status` |
| definitions in test files, and call sites in test files | `_FakeConn.close`, `NoneReturningDecider.safety_check` |
| an empty `__init__`, `__enter__`, `__exit__`, `__del__` | `AuditReportValidator.__init__` |

What survives, library-wide, is **one** finding: `UniversalAdapter.execute`
raising `NotImplementedError` in a plain class documented as "Base contract
for all domain adapters", with nothing anywhere subclassing it and live code
calling `.execute()`. It appears three times because the file is vendored
into two repositories.

That ratio is the point. A detector that reported all 162 would be telling
you about your Protocols.

### The corpus: one read, one policy, one tree

Every detector used to bring its own parser. Measured on ghost_tools itself:
a single scan of 112 files called `ast.parse` **1,064 times** — 9.5 per file
— and spent **52% of its wall clock** in the parser.

That was the smaller problem. There were six implementations of "turn a file
into a tree," and they disagreed: three decoded with `errors="replace"`,
three with `encoding="utf-8"`. A file with one invalid byte was analysed by
three detectors and invisible to fifteen, and nothing said so. One of the six
let `OSError` escape, so an unreadable file crashed the run there and was
skipped silently everywhere else.

`ghost_buster/corpus.py` is the hammer: every file is read once, parsed once,
under one stated policy, and the tree is handed to every detector read-only.

| | before | after |
|---|---|---|
| parse calls, 112 files | 1,064 | 113 |
| time in `ast.parse` | 2.14s (52%) | 0.54s |
| `run_all` | 4.14s | **2.49s** |

The policy is the interpreter's own: bytes are read, the encoding is what
PEP 263 says (coding cookie, else UTF-8), the bytes are parsed. A file that
can't be read or parsed becomes a **fact about the scan** — `corpus.unparsed()`
— held once, reported once by `unassessable_file`, skipped identically by
everyone. That list is the blind spot, and it is now the same list for every
detector.

Sharing a tree means nobody may mutate it. That is checked, not promised:
`test_no_detector_mutates_the_tree` runs every registered detector and then
compares every cached tree to a fresh parse of the same bytes, on a fixture
and on the real package. The one component that legitimately edits trees in
place — the mutation engine — asks for `corpus.fresh()` and gets its own
uncached copy.

Detectors stay independent in what they **conclude**: none reads another's
findings, so a wrong finding still points at one detector. They are no longer
independent in what they **see**, and that is deliberate.

### `--annotate-names`: one value, two names, written down twice

The complaint this answers is the one every SQL join produces. A column is
`customer_id` on one side and `recipient_id` on the other, the same key
wearing two names, and nothing in either schema saying so. Measured across
a 37-repository library on 2026-09-10, the same thing happens between
repositories: `log_odds_value` is only ever passed `raw_odds`,
`current_state` is only ever passed `current_state_variable`,
`obligation_ids` is only ever passed `needed_ids`. 63 pairs, 21 of them
spanning more than one repository.

**Only a bijection is reported, and that is the whole safety argument.** A
parameter that receives several different variables is not a naming
disagreement, it is a parameter doing its job. A variable passed to several
different parameters is the same. Renaming either would collide with a name
that is legitimately in use somewhere else. A one-to-one correspondence is
the only case where the two names provably denote one thing.

A call resolves to a definition in its own file first, then to a
library-wide one only if that name is defined exactly once, and a method
counts only when it is reached through `self` or `cls`. Ambiguity is not a
tie to be broken. Both rules came from false positives this produced
against ghost_tools itself: `subprocess.run(cmd)` in one module was taking
its parameter names from `PytestRunner.run(self, nodeids)` in another.

Three more exclusions, each an observed false positive in the unfiltered
pass of 271 pairs:

| excluded | why | example |
| --- | --- | --- |
| a CONSTANT | it has a role of its own | `dependencies <- INGRESS_GUARDS` |
| a leading underscore on one side only | privacy is part of the name | `create_fn <- _create` |
| camelCase in a snake_case library | somebody else's API | `parse_all <- parseAll` |

`ghost_buster` reports these by default and changes nothing.
`--annotate-names` is opt-in, and is the only thing in the toolkit that
writes into the tree it was pointed at. It records each disagreement in the
two places somebody actually looks:

- **the README**, as a table regenerated between a pair of HTML-comment
  markers (see the block further down this file, which this tool wrote
  about itself). One sorted list, countable, readable by somebody who is not
  in the code.
- **the code**, as a trailing comment on the signature and on each call
  site. The moment the question actually occurs to a reader is while they
  are looking at one or the other, wondering whether `cust_pub` is the same
  thing as `recipient_pub`.

Four properties, and the last one is checked rather than promised:

1. **Comments only.** Nothing it writes is code.
2. **Trailing, never inserted.** A note appended to an existing line changes
   no line's number, so a second disagreement's recorded line is still
   right and a re-run can find what the last run wrote.
3. **Idempotent.** Notes are stripped and rewritten whole on every run, so
   they follow a rename instead of piling up behind one, and neither record
   carries a timestamp -- a run that finds nothing new produces no diff.
4. **It cannot change what a program means.** Every edit is parsed before
   and after and the two syntax trees compared; if they differ by a single
   node the edit is discarded and the file is left exactly as it was. A
   backslash continuation, a line that turns out to be inside a triple-
   quoted string, a marker that is really part of a string literal: all fail
   closed, one line at a time, so a bad line costs that line and not the
   file.

```bash
# report only -- the default, writes nothing
python -m ghost_buster.cli /path/to/repo

# write both records
python -m ghost_buster.cli /path/to/repo --annotate-names
python -m ghost_buster.cli /path/to/repo --annotate-names --annotate-readme docs/NAMES.md
```

It reports; it does not rename. Which of the two names should win is a
judgement: the parameter is the contract, the variable is the caller's
local, and neither is automatically right.

<!-- ghost_buster:name-disagreements:begin -->
## Name disagreements

One value carried under two names. Every row is a bijection: the
parameter receives that variable and no other, and the variable reaches
that parameter and no other. That is the only case where the two names
provably denote one thing, and the only case where substituting one for
the other cannot capture a name that is legitimately in use elsewhere.

Nothing here has been renamed. Which name should win is a judgement:
the parameter is the contract, the variable is the caller's local, and
neither is automatically right.

| parameter | variable | call sites | files |
| --- | --- | --- | --- |
| `cap` | `max_mutants_per_candidate` | 1 | `ghost_buster/mutation.py` |
| `dist` | `token` | 2 | `blackhole_extrapolator/detect.py` |
| `dotted` | `mod` | 5 | `ghost_buster/mutation.py` |
| `entry` | `e` | 1 | `ghost_buster/secrets.py` |
| `explicit` | `base_branch` | 1 | `ghost_buster/branches.py` |
| `input_text` | `diff_out` | 1 | `ghost_buster/branches.py` |
| `later_cases` | `later` | 1 | `ghost_buster/priors.py` |
| `recovery` | `result` | 1 | `blackhole_extrapolator/cli.py`, `blackhole_extrapolator/recover.py` |
| `summary` | `phase` | 2 | `ghost_buster/testsuite.py` |
| `test_paths` | `tests` | 1 | `blackhole_extrapolator/detect.py` |

10 disagreement(s).

Regenerated by `ghost_buster <path> --annotate-names`, which also writes
the same note inline on each signature and each call. Edit the code, not
this block: it is rewritten whole every run and contains no timestamp, so
a run that changes nothing produces no diff.
<!-- ghost_buster:name-disagreements:end -->
### What a scan may do to your tree, checked rather than promised

"The working tree is never modified" appeared **35 times** across this
project's code and documentation, and nothing verified it. A promise made 35
times and checked zero times is exactly the defect class this toolkit exists
to find in other people's code, and it sat here unexamined through the
version that added `--annotate-names` and the one that added
`--recover-into`, which are the first two things in the toolkit that write
anything at all.

`Tests/test_tree_immutability.py` runs every real entry point against a real
tree and compares a content snapshot taken before and after. Writing it
immediately showed the blanket claim to be **too strong**, so the invariant
is now stated as what is actually true and actually tested:

> Nothing that already existed is modified or deleted, and the only files
> that appear are ones the caller declared it expected.

| entry point | what it may leave behind |
|---|---|
| `ghost-buster PATH` (default) | `.ghost_ledger.json` and nothing else |
| `ghost-buster PATH --accept` | `.ghost_baseline.json` |
| `ghost-buster PATH --annotate-names` | modifies `.py` files and the README, by comment only. The one deliberate exception |
| `ghost-buster PATH --operate` | a new branch `ghost/operate-<stamp>`, one commit per cut, comment-only edits; the branch the patient came in on is never written to, and the tree must be clean to start |
| `ghost-buster PATH --operate --operate-dry-run` | nothing |
| `ghost-buster PATH --json` | `.ghost_ledger.json`, the same as the default; `--no-ledger` leaves nothing |
| `blackhole-extrapolator PATH` | nothing |
| `--reconstruct-into DIR` | writes to `DIR`; the scanned tree untouched |
| `--recover-from CORPUS --recover-into DIR` | writes to `DIR`; **both** the scanned tree and the corpus untouched |

That last row matters most: a corpus is somebody's exported chat history,
and reading it has to leave it exactly as it was found. It is a second tree,
guarded separately.

The mechanism is a content hash of every path, not a patched `open`. The
idea came from a capability tracer recovered out of a chat history, which
patched `builtins.open` and would have caught none of this, because every
write here goes through `Path.write_text`:

```
Path.write_text seen by a builtins.open patch: False
```

A snapshot cannot be sidestepped by which API a writer happens to use, and
it catches a deletion, a `chmod`, a stray directory, and a file written and
removed again within the same run, all of which a patched `open` or a
survivors-only comparison would miss.

Eleven mutants hold the suite to its job. Three of them break **real product
code** in the exact way the guard exists to catch: annotating without the
flag that asks for it, writing a reconstruction beside the original instead
of into the output directory, and writing a recovery into the scanned
repository. Without those three, this would be 35 docstrings and one more
file agreeing with them.

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
API key and is not wired into the CLI at all; see below).

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
  `PROVENANCE.md`) when that repo was retired into this one. Three filters,
  a bounded-history repetition detector, and one retry loop. Every response is checked before it becomes a
  proposal: no first-person pronoun and no hedging word (`might`, `may`,
  `could`, `probably`, ...) in the replacement or the reasoning, and at
  least one evidence marker (a percentage, `data`, `evidence`, `showed`,
  ...) in the reasoning. The evidence check is scoped to the reasoning on
  purpose: a minimal doc replacement is not an empirical claim, and one
  that happens to carry an evidence word does not excuse a reasoning that
  cites nothing. An exact repeat of an earlier attempt in the same call is
  rejected too: `OscillationDetector` (adapted from a second, previously
  unmerged branch of the source repo -- see `PROVENANCE.md`) tracks the
  last 32 attempts and flags a recurrence, surfaced as
  `oscillation_detected` in the result and as the same "Duplicate
  generation detected" violation text the pipeline always used. It
  compares exactly what the pipeline's own whitespace-collapse
  normalization gives it -- no case-folding of its own, unlike the source
  branch, so a correction that differs only in case is not treated as a
  repeat. A rejected response is not discarded silently: its
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
  `Tests/test_polish_mutants.py` does the same for the vendored code
  (including `OscillationDetector`) against its own ported suite,
  thirty-six ways. `ghost-buster --mutate` reports no candidate in
  `Tests/test_ghost_writer.py`, and one unjudged (not a finding) candidate
  in `Tests/test_polish.py` -- a list-literal assertion with no enum to
  extend, so the tool cannot try a mutant against it either.

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

## Non-goals, stated explicitly

- **Nothing changes what a program means.** The surgeon (`--operate`) is
  the one thing in the toolkit that edits a tree: comment-only remedies, on
  a branch it opened, each edit verified by syntax-tree identity, the
  incoming branch never written. `--annotate-names` is the same remedy
  without the branch. Everything else finds, reports, or proposes, and
  applying a proposal is a separate, human-initiated act.
- The semantic layer never runs from the CLI (costs real money per call);
  it is a library you call with your own key, by design, every time.
- `ghost_writer` never touches a file except via the explicit `--out` flag
  writing a *new* report file -- it does not open and rewrite an existing
  README in place.

## Requirements

No dependencies are declared, and none are needed for anything the CLI
runs. The `anthropic` package is needed only if you construct an
`AnthropicModelClient` yourself -- everything else is fully testable
via `StubModelClient` with zero network access, which is how the entire
test suite runs.

## Tests

```bash
python -m pytest Tests/ -v
```

1554 tests (measured 2026-09-11), 0 network calls, 0 API key required -- the semantic-layer
tests verify the real parsing/fail-closed/injection-fencing logic via
`StubModelClient`, the same technique `sentinel_os`'s own `interpretation/`
package uses for its model-client tests. `test_branches.py`,
`test_secrets.py` and `test_testsuite.py` build real, local git
repositories and pytest projects in `tmp_path` instead, the only honest way
to test a ref-graph, git-history or suite-execution check (the secrets
suite against a real gitleaks binary, skipped if one is not on PATH).
`test_mutation.py` and the 45 `Tests/*_mutants.py` files run pytest in
subprocesses against scratch copies of the project, each mutant file
breaking one component a named number of ways and requiring every mutant
to fail a test; they account for most of the suite's wall-clock time. A
mutant whose "before" text no longer matches the source exactly once fails
loudly rather than passing vacuously.

## Changelog

`CHANGELOG.md`, every version, with the measurement that motivated each.

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

### `tools/unflatten.py`: when there is no original to recover

Recovery needs a copy to find. Four files in the library had none: not in
another repository, not in any of the four chat-history exports. For those
the choice is a rebuild or nothing, and `tools/unflatten.py` is the rebuild.

It is the opposite trade from `--reconstruct-into`. That runs over a whole
tree in milliseconds per file and never claims more than it can prove. This
takes one file and minutes of search, and returns something that parses.

Three recoveries, each a different kind of claim. Comments are ended where
code visibly resumes, because a `#` in a flattened file swallows the rest of
it. Statement boundaries are found where two tokens cannot be adjacent
inside one expression, which is close to certain. Indentation is a search
that Python's own parser validates prefix by prefix, ordered by what the
code says about itself: a method taking `self` goes inside a class, a
decorator with what it decorates, an entry-point guard at column 0.

**Every statement, name and literal in the output comes from the input,
unchanged.** The nesting is inferred. The tool counts every block boundary
that had more than one reading the parser accepts, prints that count and
writes it into the file's header, so the reader knows which half to trust.

Measured: one flattened file's original was later found in a Gemini export,
and the rebuild matches it exactly, syntax tree for syntax tree.
`Tests/test_unflatten.py` holds both as fixtures, so that is a test rather
than a claim. On the four files with no original anywhere, all four parse
and no name defined in the flattened source is missing from the rebuild.

```
python tools/unflatten.py FLATTENED.py OUT.py
```

Two absences are marked rather than invented: a block whose body the source
never held gets an Ellipsis saying so, and a line that is not Python in any
scope (a shell cell pasted into the same file) is kept as a marked comment.
Both are counted in the report.

### `--recover-from`: the original itself, not a proposal for one

`--reconstruct-into` rebuilds a flattened file by reasoning about where the
line breaks probably went. Across a 37-repository library it recovered a
running program in **0 of 34** cases. It gets you something editable, not
something correct.

This is a different job with a different guarantee. Flattening is a
**whitespace-only** transform. Measured 2026-09-10, the 37 flattened files
in that library fall into exactly two shapes:

| shape | fingerprint | what did it |
|---|---|---|
| indentation survived | space runs of 4n+1 (5, 9, 13, 17...) | each newline became one space |
| indentation gone | no multi-space run anywhere | every whitespace run became one space, which is also what an HTML render does |

Neither adds, removes or reorders a single non-whitespace character. So
define `collapse(x)` as every whitespace run replaced by one space, and
`collapse` is **invariant under flattening**. If some other text collapses
to exactly what the flattened file collapses to, that text is the original,
up to whitespace. Not the most likely original. The original.

The originals are usually still in a chat-history export. The raw ChatGPT
export checked on 2026-09-10 held 20,919 fenced code blocks, 14,185 of them
carrying real newlines; the only 39 single-line blocks over 200 characters
were **Excel formulas**, which genuinely are one line. The vendor ships code
with its newlines intact. The damage happens after the download, at a paste.

**Four verdicts, and only two of them write anything.**

| verdict | means | written |
|---|---|---|
| `identical` | a candidate collapses to exactly this file's collapse | yes, verbatim |
| `contained` | this file's collapse is a substring of a candidate's, on token boundaries | yes, the located span's real bytes |
| `related` | high identifier similarity, no collapse match | **no** |
| `none` | nothing in the corpus is close | no |

`related` is what keeps this honest. Four files scored 100% identifier
overlap against a message that was a *different version* of the same code.
High overlap is not the same claim as identical bytes, and treating it as
one is how a plausible file gets committed as a real one.

**Three defects this produced against the real library, each now a test:**

- A plain substring search matched **mid-token** (`port os` inside
  `import os`), and the span recovered from it started inside an identifier.
  Containment is now checked on token boundaries, which after collapse means
  a space or an end.
- Similarity scored as one-directional coverage rewarded a candidate for
  being **large**: the derived `raw.csv` holding every message in an export
  scored 100% against eight different files. It is intersection over union
  now.
- Naming a recovery after the file's stem refused 6 of 27 as "already
  exists", when nothing was in conflict: four repositories each hold an
  `artifact_1.py`. The path is in the name.

**One repair, and it has to prove it helped.** An HTML export writes an
indent as `&nbsp;`, so the decoded text carries U+00A0 where the code had
ordinary spaces, and Python rejects that outside a string literal.
`nbsp-to-space` is applied only when it turns a file that does not parse
into one that does; 9 of 11 non-parsing recoveries were fixed by it, and the
rest (smart quotes, a truncated string) are reported as not parsing and left
exactly as the corpus holds them. Damage in the corpus is a fact about the
corpus. A recovery is written with **no header**, because a byte-faithful
original stops being one the moment something is prepended to it; the
provenance goes in a `RECOVERY.md` manifest beside the files.

```bash
# search one or more exports, write recovered originals and a manifest
blackhole-extrapolator /path/to/library \
    --recover-from ~/chatgpt_history --recover-from ~/gemini_history \
    --recover-into /tmp/recovered
```

Nothing is written into the scanned tree, and nothing recovered is fed back
into the analysis. A recovered file becomes real source the day a human
reviews it and commits it.

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
