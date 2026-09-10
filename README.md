# ghost_tools -- v0.10

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
ghost-buster --version          # what you are running
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

Two independent layers, three repository-level checks, and a correlation
pass over all of them, every one producing the same `Finding` shape
(`ghost_buster/schema.py`):

- **Mechanical** (`ghost_buster/mechanical.py`) -- deterministic, AST-based,
  stdlib only. Every finding is `Status.CONFIRMED`; there's nothing to
  doubt about a deterministic check. Seven detectors as of v0.9:
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
  words for it. Opt-in, because it executes the project's code; it never
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

# flag branches with commits not reflected in the base branch (read-only git
# plumbing; never fetches). Defaults to the first of origin/main, origin/master,
# main, master that resolves; --branches-base overrides.
python -m ghost_buster.cli /path/to/repo --branches
python -m ghost_buster.cli /path/to/repo --branches --branches-base origin/develop

# run the project's pytest suite and classify every test that did not pass
# (failing / flaky / blocked by a named dependency / skipped without cause /
# stale skip). Executes the project's tests; never installs or starts anything.
python -m ghost_buster.cli /path/to/repo --tests
python -m ghost_buster.cli /path/to/repo --tests --tests-python /path/to/repo/.venv/bin/python --tests-reruns 5

# scan the checked-out branch's git history for committed secrets with
# gitleaks (must be installed separately; never installed by this tool).
# Read-only: never rewrites history, rotates a credential, or writes into
# the target repository.
python -m ghost_buster.cli /path/to/repo --secrets
python -m ghost_buster.cli /path/to/repo --secrets --secrets-binary /opt/gitleaks/gitleaks

# correlation runs by default and needs no flag. To let the cross-repository
# connectors fire, hand it another repo's --json output; LABEL= names it in
# the report. --no-correlate skips the pass entirely.
python -m ghost_buster.cli /path/to/other --secrets --json > /tmp/other.json
python -m ghost_buster.cli /path/to/repo --secrets --correlate-with other=/tmp/other.json
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

540 tests, 0 network calls, 0 API key required -- the semantic-layer
tests verify the real parsing/fail-closed/injection-fencing logic via
`StubModelClient`, the same technique `sentinel_os`'s own `interpretation/`
package uses for its model-client tests. `test_branches.py`,
`test_secrets.py` and `test_testsuite.py` build real, local git
repositories and pytest projects in `tmp_path` instead, the only honest way
to test a ref-graph, git-history or suite-execution check (the secrets
suite against a real gitleaks binary, skipped if one is not on PATH).
`test_mutation.py`, `test_gate_mutants.py`, `test_polish_mutants.py`,
`test_branches_mutants.py`, `test_duplication_mutants.py`,
`test_testsuite_mutants.py`, `test_secrets_mutants.py` and
`test_correlate_mutants.py` run pytest in subprocesses against scratch
copies of the project; they account for most of the suite's wall-clock
time.

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
