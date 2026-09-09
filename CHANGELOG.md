# Changelog

## 0.10.0 (2026-09-09)

### ghost_buster
- **New repository-level check `--secrets`** (`ghost_buster/secrets.py`,
  detector `committed_secret`, category `COMMITTED_SECRET`): shells out to
  gitleaks against the checked-out branch's git history and reports every
  committed credential as `Severity.CRITICAL`. gitleaks must be installed
  separately -- nothing here installs it, and a missing binary reports
  "did not run" with an install pointer rather than a clean scan.
  `--secrets-binary` points at a non-PATH install; `--secrets-timeout`
  bounds the run (default 300s).
- **History, not the working tree.** A secret "removed" by deleting the
  line in a later commit is still in history and still readable by anyone
  who can clone the repo. Scanning current file content the way every
  mechanical.py detector does would pass that repository clean.
- **The secret value never reaches a finding.** gitleaks runs with
  `--redact` (confirmed: its `Secret` and `Match` fields come back as the
  literal text `REDACTED`), and this module never reads either field
  anyway -- only rule id, description, file, line, column, commit and
  fingerprint. This is load-bearing, not caution: `--accept` writes
  findings into `.ghost_baseline.json`, which is meant to be committed, so
  a secret in a finding would mean committing the leak a second time
  inside the file whose purpose is to make findings inert.
- **A non-git directory is a hard stop, not a clean scan.** Measured
  directly: gitleaks given a directory with no `.git` logs an error to
  stderr but still exits 0 and writes an empty report, indistinguishable
  by exit code or content from a real clean scan. `scan()` runs `git
  rev-parse --git-dir` itself before ever invoking gitleaks. Genuine
  gitleaks failures (bad path, bad flag, unwritable report path) were
  confirmed to still exit non-zero even with `--exit-code 0` in effect,
  and are reported as "did not run" with gitleaks' own stderr.
- **A real bug the dogfood run caught, fixed before shipping.** The first
  pass passed gitleaks `--source <root>` while also setting the
  subprocess's own working directory to `root`, so a relative root
  resolved twice (`root/root`) and the scan failed outright on five
  repositories. Fixed by resolving the root once at the top of `scan()`
  and dropping the redundant `cwd`; `Tests/test_secrets.py` pins it with a
  relative-root regression test.
- **Library sweep, 33 repositories.** 31 scanned (two transcript-archive
  repos exceeded the ad hoc 180-second timeout used for the sweep; the
  shipped default is 300). 25 clean. 33 findings across 6 repositories:
  31 `generic-api-key` matches, almost all inside test fixtures and a
  training corpus, and 2 `private-key` matches -- one genuine committed
  TLS private key at `sentinel_os/certs/key.pem`, present in a second
  repository that vendors a copy of it. Placeholder and already-rotated
  fixture values are silenced at the source with a `.gitleaksignore`
  entry, which gitleaks honors before this module ever sees the finding
  (confirmed directly); no suppression logic beyond the shared baseline
  lives here.
- CI installs a pinned gitleaks (8.21.2) so `Tests/test_secrets.py` and
  `Tests/test_secrets_mutants.py` actually run instead of skipping; both
  skip themselves when the binary is absent locally.
- 20 tests and `Tests/test_secrets_mutants.py` (14 mutants, all killed).
  One mutant from the exploratory run is documented rather than forced:
  dropping `--redact` changes nothing observable through `scan()`, since
  no field it touches is ever read into a finding.
- Tests: 353 -> 387.

## 0.9.0 (2026-09-09)

### ghost_buster
The duplication heuristics, recalibrated on the first whole-library run
(37 repositories). Every change below was measured on the library before
it was adopted; the numbers are in each detector's docstring and the
README.
- **`intra_function_duplicate_block`**: a single statement now counts as
  repeated only across distinct statement lists (different branch
  bodies), never within one block. 643 of 655 findings on the library
  were runs of similar statements in one block -- an `__init__` assigning
  seven attributes, a dict built one entry per line -- not the six-branch
  shape the detector was built for. The single-statement complexity floor
  is 20, not 15: the original gate.py's four branch returns measured 41,
  26, 33 and 22 nodes, so 20 keeps all four (25 would have lost one).
  1,300 findings became 221, MAJOR 215 became 46. Multi-statement block
  findings are unchanged.
- **New detector `duplicate_file`**: one MAJOR finding per group of
  byte-identical scanned files, with the size in the summary. Sampling
  `near_duplicate_function`'s pairs by hand found this was the dominant
  case -- a module vendored verbatim from a sibling repo, a committed
  `-1`/` (1)` download copy -- reported once per function instead of once
  per file. 31 groups on the library. Empty files never form a group.
- **`near_duplicate_function`**: fingerprints each byte-identical group's
  functions once; default `min_lines` 10 (was 6); a cluster made only of
  test functions is INFORMATIONAL, never MAJOR. 625 findings became 248,
  MAJOR 77 became 27.
- **CLI file collection** collects each real path once (a symlinked file
  was listed under both names, measured on OBSERVE) and skips `build/`,
  `dist/` and `*.egg-info/` (a stray wheel-build `build/` on this repo's
  own checkout produced 113 near-duplicate findings, every module against
  a copy of itself).
- Across the library, all detectors: 1,368 new findings became 570, MAJOR
  193 became 98. `dead_code`, `doc_test_count_drift` and `unmerged_branch`
  counts did not move.
- Baselines: `near_duplicate_function` and `intra_function_duplicate_block`
  finding ids include the occurrence list, so a committed baseline will
  show the recalibrated findings as new and the old ones as stale on the
  first run after upgrading. Re-accept once.
- 12 tests and `Tests/test_duplication_mutants.py` (13 mutants, one per
  rule, each killed only by the test that pins that rule). Two of those
  mutants caught tests that could not discriminate as first written and
  were fixed before this shipped.
- Tests: 328 -> 353.

## 0.8.1 (2026-09-09)

### ghost_buster
Two defects in `--branches`, both found by the first run across the whole
library (37 repositories) and both fixed the same day:
- **A non-UTF-8 diff crashed the scan.** A transcript-dump repo's branch
  diff carried a Windows-1252 smart quote; `git diff` output decoded as
  UTF-8 raised out of the subprocess call, taking every other detector's
  findings for that repo down with it. Git output is now decoded with
  `errors="replace"`, which is deterministic for the same input and so
  still yields a stable patch-id. The exception is also caught as
  defense-in-depth, but note what that alone would have done: an
  unreadable diff would have read as "nothing to compare, absorbed" -- a
  false negative, worse than the crash. The regression test pins the
  branch being *flagged*, not merely the scan not raising.
- **Every clone-shaped checkout counted one phantom branch.** A real
  `git clone` sets `refs/remotes/origin/HEAD`, which `%(refname:short)`
  renders as the bare word `origin`, slipping past an `endswith("/HEAD")`
  filter. It was always an ancestor of base, so it never produced a
  finding, but it was compared on every run (37 of 37 repos reported
  "compared 1 branch" on a checkout with only `main`). Refs are now read
  in full and shortened by the detector itself.
- Three tests added; two mutants added to `Tests/test_branches_mutants.py`,
  one per fix, each confirmed killed only by its new test.
- Tests: 323 -> 328.

## 0.7.0 (2026-09-09)

### ghost_buster
- **New check: unmerged branches** (`ghost_buster/branches.py`,
  `--branches` / `--branches-base REF`). Neither mechanical (no file to
  parse) nor semantic (no judgment call, no API) in the usual sense, but
  deterministic and `Status.CONFIRMED` like the mechanical layer: it flags
  a local or remote-tracking branch whose commits are not reflected in
  the base branch, via read-only `git` plumbing against the checkout as
  it sits. Never fetches, pushes, or writes a ref.
- **Solves the squash-merge false positive directly**, not by accident:
  an ancestor-only check flags every squash-merged branch as unmerged
  forever, since a squash rewrites a branch's history into one new commit
  on base and the branch tip is never an ancestor of anything again.
  Confirmed against this project's own history before the fix existed:
  four already-squash-merged ghost_tools branches would have been false
  positives. The fix compares the whole branch-to-merge-base diff, as one
  patch-id, against every commit base picked up since -- a squash
  commit's diff is exactly the union of what the branch changed, so its
  patch-id matches.
- **Two blind spots, disclosed rather than fixed**, because fixing either
  means the network access this whole layer of the tool exists to avoid:
  it cannot see a branch's pull-request state (open, rejected, or never
  opened all look identical here), and a remote-tracking ref already
  deleted on GitHub still reads as unmerged until the checkout re-fetches
  with `--prune` -- also measured directly against this project's own
  checkout, where four already-deleted branches, fetched once outside the
  checkout's configured refspec, kept showing up because neither an
  ordinary fetch nor `--prune` touches a ref outside that refspec.
- `Tests/test_branches.py` (15 tests) builds real git repositories in
  `tmp_path`; `ghost-buster --mutate` finds no candidate in it, so
  `Tests/test_branches_mutants.py` breaks the detector twelve ways in a
  scratch copy and requires each to fail a test, naming two mutants from
  its own exploratory run that turned out not to be real gaps (a
  documented-redundant fast path, and a no-op from `git merge-base`'s
  documented argument symmetry) rather than forcing tests for them.
- New `Category.UNMERGED_BRANCH`.
- Tests: 272 -> 300.

## 0.8.0 (2026-09-09)

### ghost_buster
- **New mechanical detector: `merge_conflict_marker`.** Flags an
  unresolved `<<<<<<< / ======= / >>>>>>>` conflict-marker triplet left
  in a committed file. The one detector in `mechanical.py` that
  deliberately does not go through `ast.parse()`: a file with a real,
  unresolved marker in it is almost never valid Python, so an AST-based
  version would find nothing in exactly the files most likely to have
  the problem. Requires the full triplet, in order, not any one marker
  line alone -- a lone `=======` is a real false-positive risk against a
  Setext-style Markdown H1 underline, the same reason the widely-used
  `pre-commit-hooks` project's own check-merge-conflict hook requires the
  same shape. `Severity.CRITICAL`, `Status.CONFIRMED`. New
  `Category.MERGE_CONFLICT_MARKER`.
- Confirmed by running the finished detector against its own module and
  test files: it does not self-flag on its own documentation, which
  discusses the marker strings extensively in prose.
- `Tests/test_ghost_buster.py` gained 13 tests, including one pinning
  that a nested, unresolved second start-marker inside an already-found
  triplet's span is not double-counted, and one for a file that is not
  valid UTF-8. `ghost-buster --mutate` finds no candidate in the new
  tests; `Tests/test_merge_conflict_marker_mutants.py` breaks the
  detector ten ways in a scratch copy and requires each to fail a test,
  naming the one mutant from its own exploratory run that was not a real
  gap (starting a lookup one line earlier than necessary is inert,
  because the two marker patterns it searches are mutually exclusive) --
  though the underlying helper's own off-by-one contract still gets a
  direct, caller-independent test.
- A dogfood scan of the whole repo also surfaced a real, minor
  duplicate-shape finding in the detector's own two next-match lookups;
  extracted into a shared `_next_matching` helper rather than left as
  disclosed noise.
- Tests: 300 -> 323.

## 0.6.3 (2026-09-09)

### ghost_writer
- **`OscillationDetector`**, a bounded-history repetition check, replaces
  the vendored pipeline's inline `set` of response hashes for detecting a
  repeated proposal within one `propose_correction` call. Adapted from a
  second, previously unmerged branch of `content-polish-pipeline`
  (`claude/ats-oscillation-detection-qs1k74`, never opened as a pull
  request there, found during a branch audit after the repo's retirement
  and archival). `PROVENANCE.md` records the source commit and the one
  deliberate deviation: the source's detector lowercased its input before
  comparing, and this copy does not -- the vendored pipeline already
  normalizes a response before any duplicate check sees it, and stacking
  a second, case-insensitive normalization on top would treat two
  proposals differing only in capitalization as the same output, a real
  behavior change nothing asked for.
- Every `ContentPolishPipeline.execute()` result now carries an
  `oscillation_detected` field. The "Duplicate generation detected"
  violation text, `correct.py`'s consumption of the result, and
  `CorrectionProposal`'s shape are all unchanged.
- `Tests/test_polish.py` gained a unit-test class for `OscillationDetector`
  and two pipeline tests for the new field, including one that would fail
  if `execute()` reset only its own `oscillation_detected` flag and not
  the detector's own history between calls.
  `Tests/test_polish_mutants.py` gained eight mutants for the new class
  and the rewired pipeline code, replacing the one mutant that targeted
  the now-removed inline hash set; all are killed. `ghost-buster --mutate`
  now reports one candidate in `test_polish.py` (a list-literal assertion
  in the new detector tests) and reports it unjudged, not a finding.
- Tests: 255 -> 272.

## 0.6.2 (2026-09-09)

### Tests
- The three mutants 0.6.1 recorded as surviving `Tests/test_polish.py` are
  killed and in `Tests/test_polish_mutants.py` (now 28), one test added per
  gap:
  - **The signature did not have to use the key.** The stability test
    compared two runs sharing one key, so replacing the key with an empty
    one changed nothing. A second test signs the same validated content
    under two different secrets and requires the signatures to differ.
  - **The retry prompt was never read.** No test looked at what the second
    call received, so dropping the recalibration feedback was invisible.
    A test now asserts the first prompt carries no feedback, and the retry
    names both the violation that rejected attempt one and the caller's
    original prompt.
  - **Whitespace normalization was uncovered** (recorded as such since the
    source repo's own provenance). A test feeds runs of spaces, newlines
    and a tab, and requires the validated content to come back collapsed to
    single spaces.
- No mutant written for `ghost_writer/polish` is now held back as a known
  survivor.

## 0.6.1 (2026-09-09)

### Tests
- `Tests/test_polish_mutants.py`: 25 hand-made mutants of
  `ghost_writer/polish` (each filter's pattern emptied, `passes()` forced
  true, `violations()` unsorted, the empirical contract inverted, the retry
  loop cut to one attempt, duplicate detection disabled, the gateway
  exception uncaught, the `max_attempts` check removed, the result dict's
  status, attempt count, content and violations falsified, the signature
  hash downgraded), each required to fail a test in `Tests/test_polish.py`.
  `ghost-buster --mutate --mutate-only test_polish.py` reports zero
  candidates in that file, as it does for `test_ghost_writer.py`: no test in
  either has a shape it mutates, so these suites are the complement.
- The scratch-copy harness both mutant suites use is one module,
  `Tests/mutant_harness.py`; `test_gate_mutants.py` no longer carries its
  own copy.
- Three mutants survived the ported `test_polish.py` as received: the
  speculation filter's `is_clean` alias had no alias test (the other two
  filters did), and no pipeline fixture tripped the pronoun check or the
  speculation check alone, so forcing either to pass changed nothing.
  Three tests added, one per gap; the three mutants are in the suite.
- Three mutants `test_polish.py` still does not kill are recorded in the
  new file's docstring and left out of it rather than papered over: the
  signature's dependence on the key, the recalibration feedback text
  (covered by `test_ghost_writer.py`), and whitespace normalization.

## 0.6.0 (2026-09-09)

### ghost_writer
- **Quality gate on `correct.py`.** The one LLM call in `ghost_writer` that
  generates new text is now wrapped in a retry loop that rejects a response
  containing a first-person pronoun or a hedging word in either the
  proposed replacement or the reasoning, or no evidence marker in the
  reasoning, feeds the violations back into the prompt (after the fenced
  untrusted block) and asks again, three attempts by default
  (`propose_correction(..., max_attempts=3)`). Exhausting the attempts
  yields the existing `(None, report)` outcome with the violations in
  `report.reason`; empty, malformed and client-failed responses are not
  retried and behave as before. `CorrectionProposal` is unchanged.
  `report.py` is not gated.
- **`ghost_writer/polish/`**, vendored from `content-polish-pipeline` at
  commit `44bf225` (MIT, notice kept beside the files) when that repo was
  retired into this one. The copy differs from the source in an unused
  `asyncio` import removed (ruff gate), the standalone import fallback
  removed, and the logger renamed to `ghost_writer.polish`; `PROVENANCE.md`
  records it. Its 23 tests are ported as `Tests/test_polish.py`.
- `Tests/test_gate_mutants.py`: fourteen hand-made mutants of the gate, each
  required to fail a gate test. `ghost-buster --mutate` finds no candidate
  in the gate's tests (none has a shape it mutates), so this is the proof
  that they are not vacuous.
- The `correct.py` happy-path fixture's reasoning changed from `why` to a
  sentence that names its evidence, the one existing test the gate
  rejects as written. No caller changed.
- Setuptools now lists `ghost_writer.polish`; `pip install .` was not
  installing subpackages by discovery.

## 0.5.2 (2026-09-08)

### blackhole_extrapolator
Three defects from the first full-library run (18 checkouts):
- A directory with Python anywhere beneath it is an importable namespace
  package, not only one with `.py` files directly inside. ecology's `src/`
  was reported missing 38 times.
- Requirements files are found anywhere in the tree, and `-r` / `--requirement`
  includes are followed relative to the including file, with a cycle guard.
  sentinel_os keeps its requirements one directory down; GSA-815's file is a
  single include into a submodule.
- The debris scanner no longer reads `{"ok": True,` as a type annotation:
  an annotation must follow a parameter name, and `True`, `False`, `None`
  are never dangling types.
- A declared distribution provides the import name it plausibly maps to:
  its first name token (`psycopg2-binary` gives `psycopg2`,
  `opentelemetry-api` gives `opentelemetry`) plus a short alias table
  (`PyYAML` gives `yaml`). sentinel_os declared every dependency it uses and
  three still read as voids.
- A requirements line starting with `http` is skipped only when it is a
  URL. `httpx<0.28` was being skipped as one.

## 0.5.1 (2026-09-08)

### blackhole_extrapolator
- **Rename candidates.** A name nothing defines is compared, by shape and
  never by name, against every signature the tree still has: parsing files
  and the headers read back from flattened ones. Dimensions: a keyword the
  caller passes is a parameter of the candidate; the caller unpacks N values
  and the candidate returns an N-tuple; an unpacked value is passed on to
  another known signature whose parameter carries the same annotation as the
  tuple element; a method used on the result is one the candidate class
  defines; the two names share a word. Arity compatibility is a gate. Two
  matching dimensions, at least one of them not the name, make a
  `rename_candidate` evidence item in the undefined name's own void, and the
  void lists the hypothesis as undeterminable. Nothing is merged. Found on
  TOUCHSTONE: `initialize_hybrid_cluster` is `initialize_network_cluster` on
  five dimensions, and `UnifiedGovernanceKernel` is `GovernanceKernel` on its
  four keyword parameters, in a flattened file the callers never name.

## 0.5.0 (2026-09-08)

The release that makes the toolkit shippable and closes the pipeline.

### ghost_buster
- **Mutation mode** (`--mutate`). Finds tests shaped like they check nothing
  (weak assertions only, a computed result never read, assertions behind a
  guard, a hand-written list restating a set the source defines), resolves the
  project code each one calls, breaks that code in a scratch copy one operator
  at a time (`drop_body`, `return_none`, `flip_compare`, `bump_constants`;
  guard instrumentation; enum extension), runs only that test, and reports a
  finding **only when the test survived**, carrying the mutation as its proof.
  The working tree is never modified; siblings are symlinked beside the copy so
  `../sibling` imports resolve. Candidates that do not pass unmutated are
  reported as unjudged, never as findings. New category `vacuous_check`.
  Validated on real repositories: found the test the 2026-09-08 audit had
  confirmed by hand, and a test that survives eleven inverted comparisons.
- Guard semantics are "the guarded assertions never ran", measured by
  instrumentation, not "removing the guard fails the test" (which flags every
  data-dependent guard). An if/else that asserts on both sides is a branch, not
  a guard. A guard holding every assertion of its test is CRITICAL; one beside
  unguarded assertions is MAJOR.

### ghost_writer
- **`ghost-triage`**, the human step the README always drew and never had a
  tool for: records `fix` / `suppress` / `document` decisions with a note
  against finding ids in the FindingSet JSON, refuses unknown or ambiguous ids,
  lists what is still undecided.
- **Triage report mode** (`--mode triage`): every finding, most severe first,
  grouped by file, with a severity and detector summary, `vacuous_check` proofs
  rendered as such, and already-decided findings listed with their decision.
  It states on its face that nothing in it has been reviewed. The document
  mode and its gate are unchanged.

### blackhole_extrapolator
- **Ecosystem awareness.** An import that a sibling checkout defines, that the
  project declares as a dependency (requirements files, pyproject dependencies
  and optional extras), or that a declared git submodule would provide is
  reported as **wiring** with the provider named, beside the voids, never
  grouped into one and never silenced. An uninitialised submodule is attached
  to unresolved imports as a note, not a claim. `--sibling DIR` (repeatable),
  `--ecosystem PARENT` (every checkout under a parent, each against the rest),
  `--show-wiring`. Default JSON shape unchanged; with `--show-wiring` it is
  `{"voids": [...], "wiring": [...]}`. Measured on the governance stack: the
  spine went from five voids to the one real nominal dependency.
- **Debris archaeology.** A flattened file (no newlines, does not parse)
  keeps every `class` and `def` header in token order. New evidence kind
  `debris_structure` reads the interface back, with parameter lists and return
  annotations and methods attributed to the class that precedes them, and the
  void lists it under `must define`. Bodies, docstring examples and
  interleaved pastes are named as undeterminable on every such void. A parsing
  companion (`x_source.py` beside `x_adapter.py`) is checked for shared class
  names so an ancestor of a rewrite is not reported as a lost dependency.
  Measured on TOUCHSTONE's `quorum_state_governance_source.py`: 38 signatures
  recovered where 0.4 reported seven names and no shape.
- **Corpus run fixes** (nine checkouts, 49 voids to 36). A test that imports
  a sibling-provided module is wiring, not an orphaned test (the spine's
  `ccc`, `gems` and `governance_gateway` were being reported twice, once by
  each detector, and only one consulted the providers). A file that parses as
  a single comment is destroyed for the structure detector as it already was
  for the residue detector, and its void is classified destroyed. Callers of a
  name a destroyed file's debris defines join that file's void instead of
  forming a second, never-built one; the void says the join is by name.
  `--json` emits JSON when nothing is missing, and `--ecosystem --json` emits
  one object keyed by checkout instead of prose headers between documents.

### Packaging
- Console scripts: `ghost-buster`, `ghost-writer`, `ghost-triage`,
  `blackhole-extrapolator`. Explicit package list, classifiers, keywords, URLs.
  `pip install git+https://github.com/wking53214/ghost_tools` works from a clean
  environment with no dependencies.

## 0.4 and earlier

See the changelog section at the end of README.md.
