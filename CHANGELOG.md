# Changelog

## 0.17.13 (2026-09-10)

### Tests
The tree-immutability guard: proof that a scan leaves the tree alone,
instead of a docstring saying so.

"The working tree is never modified" appeared 35 times across this project's
code and documentation and nothing verified it. That is the defect class
ghost_buster exists to find in other people's code, and it went unexamined
here through the version that added `--annotate-names` and the one that
added `--recover-into` -- the first two things in the toolkit that write
anything at all.

`Tests/tree_guard.py` snapshots every path under a root as `mode:sha256`,
and `unchanged(root, may_create=...)` asserts that nothing which already
existed was modified or deleted and that only declared files appeared.
`Tests/test_tree_immutability.py` runs every real entry point against a real
tree under that guard, including the recovery pass against a corpus, which
is a second tree: an exported chat history has to be left exactly as it was
found.

Writing it showed the blanket claim to be too strong, and the docstrings
that made it are corrected. A default scan writes `.ghost_ledger.json`;
`--accept` writes `.ghost_baseline.json`; `--annotate-names` deliberately
edits sources. The invariant that is true and now tested is that nothing
which already existed is modified or deleted, and that every new file was
declared.

The mechanism is a content snapshot rather than a patched `open`. The idea
came from a capability tracer recovered out of a chat history by
`--recover-from`; its mechanism patched `builtins.open`, which would have
caught none of this, because every write here goes through
`Path.write_text`. A snapshot also catches a deletion, a chmod, a stray
directory and a file written and removed again inside one run.

Eleven mutants, three of which break real product code in the exact way the
guard exists to catch: annotating without the flag, writing a reconstruction
beside the original, writing a recovery into the scanned repository.

## 0.17.12 (2026-09-10)

### blackhole_extrapolator
`--recover-from` gets the ORIGINAL of a flattened file back, instead of
proposing one.

`--reconstruct-into` reasons about where the line breaks probably went and
recovered a running program in 0 of 34 cases. This does something
categorically different, because flattening turns out to be a whitespace-only
transform. The 37 flattened files in a 37-repository library fall into
exactly two shapes: one where each newline became a single space and the
indentation survived (space runs of 4n+1), and one where every whitespace
run collapsed to a single space, which is also what an HTML render does.
Neither adds, removes or reorders a non-whitespace character.

So `collapse` -- every whitespace run as one space -- is invariant under
flattening, and a text that collapses to what a flattened file collapses to
IS its original, up to whitespace. Not the most likely original.

Four verdicts. `identical` and `contained` are that test passing and are
written verbatim, with no header, because a byte-faithful original stops
being one the moment something is prepended to it; the provenance goes in a
RECOVERY.md manifest instead. `related` is high identifier similarity
WITHOUT a collapse match -- a different draft of the same system -- and is
named and deliberately not written. Four files scored 100% identifier
overlap against a message that was a different version of the same code,
which is exactly how a plausible file gets committed as a real one.

Three defects found by running it against the real library, each now a test:

  * A plain substring search matched mid-token (`port os` inside `import
    os`), and the span recovered from it started inside an identifier.
    Containment is checked on token boundaries, which after collapse means a
    space or an end.
  * Similarity scored as one-directional coverage rewarded a candidate for
    being large: the derived `raw.csv` holding every message in an export
    scored 100% against eight different files. It is intersection over union
    now.
  * Naming a recovery after the file's stem refused 6 of 27 as already
    existing when nothing was in conflict, because four repositories each
    hold an `artifact_1.py`. The path is in the name.

One repair, gated on proving it helped: an HTML export writes an indent as
`&nbsp;`, so the decoded text carries U+00A0 where the code had ordinary
spaces and Python rejects that outside a string. `nbsp-to-space` is applied
only when it turns a file that does not parse into one that does. The
remaining failures (smart quotes, an arrow, a truncated string) are reported
as not parsing and left exactly as the corpus holds them. Corpus damage is a
fact about the corpus. HTML entity decoding is handled the same way: it only
ADDS a candidate, which still has to pass the same exact collapse test.

Measured against the library with five history corpora (37 flattened files,
15,498 candidates): **29 recovered** -- 8 identical, 21 contained -- of which
25 parse as real Python, 12 after the nbsp repair. 7 related and not written,
1 with no candidate at all.

The definition of a flattened file now lives in one place in the CLI, shared
by the reconstruct pass and the recover pass, so the two cannot disagree
about what they are looking at.

## 0.17.11 (2026-09-10)

### ghost_buster
`--annotate-names` writes each 1:1 name disagreement into the two places
somebody looks: a regenerated table in the README, and a trailing comment
on the signature and on each call site.

This is the only thing in the toolkit that writes into the tree it was
pointed at, and it is fenced for it. Notes are comments, never code. They
are appended to existing lines rather than inserted as lines of their own,
so no line number moves and a re-run can find what the last run wrote. They
are stripped and rewritten whole each run, so they follow a rename instead
of piling up behind one, and neither record carries a timestamp -- a run
that finds nothing new produces no diff at all.

The claim that a note cannot change what a program means is checked, not
promised: every edit is parsed before and after and the syntax trees
compared, one edit at a time. Two cases found this the hard way and are now
tests -- a marker that was really part of a string literal (an earlier
whole-file check cost that file every annotation it should have had), and a
call on a backslash continuation, where a comment cannot follow.

`find_name_disagreements` now returns the pairs with their line numbers,
which is what makes an annotation possible; `detect_name_disagreements`
builds the same findings from it.

Two false-positive generators were found by running this against the
toolkit itself and are now fixed. A call was matched to the FIRST function
of that name anywhere in the scan, so `subprocess.run(cmd)` in one module
took its parameter names from `PytestRunner.run(self, nodeids)` in another
and the two were reported as one value under two names. And any attribute
call counted, which is how a stranger's method got treated as ours. A call
now resolves to a definition in its own file first, then to a library-wide
one only if the name is defined exactly once; a method counts only when it
is reached through `self` or `cls`. Ambiguity is not a tie to be broken.

Measured across the 37-repository library: 63 disagreements (89 before the
fix), 21 of them spanning more than one repository, 179 note lines across
62 files.

## 0.17.10 (2026-09-10)

### blackhole_extrapolator
`reconstruct` rebuilds a flattened Python file -- one whose newlines are
gone and whose whole program sits on a single row -- into an editable
draft, written as a proposal into a directory the caller names, never
beside the original. 34 flattened files library-wide; none recovers as a
running program, all 34 become drafts, median 1 line to 135.

`parses` is not enough to call a reconstruction recovered: a flattened file
whose single line begins with `#` is one comment that parses cleanly and
defines nothing. The check is `bool(tree.body)`.

### ghost_buster
`name_disagreement`: one value carried across a seam under two names,
reported only for a true bijection, because that is the only case where the
two names provably denote one thing and a substitution cannot capture
anything else.

## 0.10.1 (2026-09-10)

### ghost_buster
Precision fix for `doc_test_count_drift` and the connector built on it,
found by running the whole toolkit against ghost_tools itself. All three
of its drift findings, and all three correlations, were false.

- **A number followed by "tests" is not automatically a claim about the
  current suite.** Four shapes read identically to the claim regex and
  mean something else; each of the first three was a real false positive
  on this project's own docs:
  - `"gained 13 tests"` -- a delta, not a total (CHANGELOG.md)
  - `"went from 255 to 272 tests"` -- a recorded transition, true when
    written (PROVENANCE.md)
  - `'claimed "135 tests"'` -- another project's stale count, quoted here
    as the example this detector was built from. The detector was
    flagging the sentence that explains the detector (README.md)
  - an unquoted attribution (`claimed 3 tests`), added for symmetry
  Each pattern must match immediately before the number, which keeps them
  narrow: a live claim rarely has one of these words adjacent to its count.
- **The connector re-checks rather than trusting.**
  `doc_count_contradicted_by_run` does not merely repeat its input, it
  tells a reader to write a specific number into a specific file, and that
  instruction is wrong for a delta or a quotation -- it replaces something
  true with something false. The detector now publishes the claim's
  surrounding text as `claim_context`, and the connector re-runs
  `claim_shape()` on it itself. Two mutants pin that the re-check is
  load-bearing.
- **A false negative caught during the fix, worth naming.** The first
  version of the quotation rule included the backtick, so a live claim
  sitting under a ` ```bash ` block -- exactly where this project's README
  states its own count -- was read as quoted and silently suppressed.
  Suppressing a real claim is the one outcome worse than the false
  positives these rules remove. Backtick is out of the quote set, and a
  regression test pins the code-fence case.
- Measured on ghost_tools: 27 findings -> 22, with doc_test_count_drift
  3 -> 0 and doc_count_contradicted_by_run 3 -> 0. No remaining doc
  findings, and no CRITICAL or MAJOR anywhere in the repository.
- **Known blind spot, unchanged.** `doc_count_contradicted_by_run` can
  only fire where `doc_test_count_drift` already fired, so a documented
  count that sits above the static lower bound but below the real
  collected count is caught by neither. That is exactly this README's own
  "519 tests" against a suite now collecting 540; the number is corrected
  here by hand, not by the tool.
- 8 tests and 9 mutants added, all killed. One mutant from the exploratory
  run was a broken no-op (it inserted a disabled rule while leaving the
  real one intact) and was rewritten rather than counted as a survivor.
- Tests: 519 -> 540.

## 0.10.0 (2026-09-09)

### ghost_buster
- **New repository-level check `--tests`** (`ghost_buster/testsuite.py`,
  detector `test_status`, category `TEST_STATUS`): runs the project's
  pytest suite and reports every test that did not pass, classified by
  what the outcome means. Failing (MAJOR); flaky, meaning it fails in the
  suite and passes when rerun alone up to `--tests-reruns` times, default
  3, stopping at the first pass (MAJOR); blocked by a named missing
  dependency, not rerun (MINOR); skipped without a reason naming a
  dependency (MAJOR); skipped for a dependency that is present, probed
  for modules and environment variables only (MAJOR); skipped for an
  absent one (INFORMATIONAL); an `xfail` that passes (MAJOR). Opt-in
  because it executes the project's code. Never installs, starts, or
  sets anything; writes no cache or bytecode into the project.
  `--tests-python` runs the suite with the project's own interpreter;
  `--tests-timeout` bounds each pytest invocation.
- Outcomes are read through a temporary pytest plugin recording one JSON
  line per test phase (node id, phase, outcome, location, text), run with
  `--continue-on-collection-errors` so one uncollectable module does not
  hide the rest of the suite.
- The dependency vocabulary was calibrated on four real suites before
  shipping (herald 390 tests, observe-perceive 565, gsa-815 19 modules,
  sentinel_os 968 in its own virtualenv), each change measured:
  - A failure naming a module that exists as a file inside the scanned
    project is a path defect (MAJOR, with the location), not a missing
    dependency. gsa-815, where 17 of 19 test modules cannot be collected
    for modules with repository-local names, first looked like this case
    and is not: its `DEPENDENCIES.md` lists those modules as owed by a
    sibling repository, so blocked is the correct reading there and the
    rule stays silent. It is pinned by a fixture with a real
    repository-local module.
  - "X checkout not available" and similar name a resource: 47 of
    observe-perceive's 52 skips read as naming nothing before this.
  - A missing executable at an absolute path under a system bin
    directory is a tool: sentinel_os's 18 `test_twin_live.py` setup
    errors on `/usr/local/bin/twin_ensure_services` read as failing
    before this. A missing relative file still reads as failing; that is
    the repository's own defect.
  - Failure text is classified from its error lines only (pytest's `E`
    lines and the final `path:line: Exception` line), never the source
    walked to reach them.
- 54 tests (`Tests/test_testsuite.py`, real pytest projects in
  `tmp_path`) and `Tests/test_testsuite_mutants.py` (22 mutants, all
  killed). The first exploratory mutant run found one survivor, a fixture
  that could not tell whole-traceback classification from error-line
  classification; the discriminating shape was added to the fixture, not
  the mutant dropped.
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
- **New correlation layer `ghost_buster/correlate.py`** (on by default,
  `--no-correlate` opts out): connectors that produce findings only
  visible when two detectors are read together. A connector is a pure
  function over findings a run already produced -- no parsing, no
  subprocess, no file reads -- so it costs nothing and stays silent when
  its inputs are absent. Four ship: `secret_in_duplicated_file` (a leak's
  blast radius across byte-identical copies), `secret_in_multiple_
  repositories` (the same leak, by gitleaks fingerprint, in another
  repository's `--json` output via `--correlate-with [LABEL=]FILE`),
  `conflict_marker_breaks_tests` (one marker as the root cause of N
  unrunnable tests, same-file attribution only), and
  `doc_count_contradicted_by_run` (a documented test count against the
  measured collected/passing numbers).
- **`Finding.attributes`**, a `str -> str` map of machine-readable join
  keys per detector (gitleaks fingerprint, content hash, pytest node id,
  documented count). Connectors join on these, never on summary prose: a
  reworded summary would switch a connector off silently. Deliberately not
  part of the finding id, so adding a key never renumbers a committed
  baseline; round-trips through `--json`.
- Correlations are additive (inputs are kept and named by id in the
  correlation's detail), never recursive (connectors do not read their own
  output), and never built from `REASONED` findings.
- **Two path-portability defects found and fixed while building it.**
  `Evidence.related_files` was written straight from the scan's absolute
  paths while every other path was project-relative, so baselines carried
  a home directory and a leaked file could not be joined against its own
  twin; it is now put through `_portable_path` like `evidence.file`, for
  every detector. `duplicate_file`'s summary named absolute paths too,
  which put the checkout location inside a finding id -- the exact defect
  `_portable_path` exists to prevent. **`duplicate_file` ids change once
  as a result; re-accept the baseline.** A test pins that the same two
  files scanned from two checkout locations now produce the same id.
- Dogfooded on the case that motivated the layer: a committed TLS private
  key in `sentinel_os/certs/key.pem` is also in `observe`, which vendors a
  copy. Previously two unrelated CRITICALs in two separate scans;
  `secret_in_multiple_repositories` now matches them on fingerprint, and
  four `secret_in_duplicated_file` correlations fired within `observe`.
- 35 tests and `Tests/test_correlate_mutants.py` (20 mutants, all killed).
  Three exploratory survivors were investigated rather than assumed: two
  were real gaps (an eligibility rule with no direct seam, and an
  asymmetric `.get()` default that made an empty-fingerprint collision
  unreachable) and were fixed in the code and the tests; the third is a
  cost guard whose removal changes nothing observable, and is documented
  rather than forced.
- Tests: 353 -> 519.

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
