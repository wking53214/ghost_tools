# ghost_tools

Version 1.10.14 (`pyproject.toml`; see CHANGELOG.md). A Python toolkit that scans a code repository for things that are present and wrong: documentation that disagrees with the code, duplicated code, tests that cannot fail, committed secrets and structural leftovers. Assurance loop: **this scanner <- [`SWIZZLE`](https://github.com/wking53214/SWIZZLE) + [`ASSAY`](https://github.com/wking53214/ASSAY) specimens**.

## 1. Pipeline Position & Role

**What this is.** Six command line tools that read a repository and report what they find. `ghost-buster` is the scanner; the other five work from its findings or from the same repositories (the list is in section 2). They report; they do not change the code they read. They sit beside the live decision path of the wider library, not on it: in the circuit (section 7) the Warden is the only part allowed to write, and ghost_tools is the part that observes before and after.

Read sections 4 to 4e before relying on it. They say what is proven, what is not, what is broken today and what was broken before.

## 1b. How to install and run

Python 3.11, 3.12 or 3.13. There are no runtime dependencies. Dated record: on 2026-10-22 (ghost_tools 1.10.8) the commands below were run as written in a fresh virtual environment on Python 3.12, and `pip check` reported no broken requirements. That says nothing about later versions; the `tests` workflow installs the package on every push.

From a checkout (the way to get this version):

```
git clone https://github.com/wking53214/ghost_tools
cd ghost_tools
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
ghost-buster --version
ghost-buster . --no-tests --no-branches --single-repo --no-ledger \
    --baseline .ghost_baseline.json --casefile .ghost_casefile.json
echo $?
```

That last command is what the `self-scan` CI job runs on this repository. It takes about ten seconds, prints its findings, a note for every check it did not run, and exits `0`: nothing new at MAJOR or CRITICAL. The exit codes are in section 6. The secrets check needs the `gitleaks` binary (version 8) on `PATH`; without it the report says that check could not run and, under `--json`, `status` is `"incomplete"`, so an exit of 0 is not then a clean bill of health.

To scan another repository run `ghost-buster /path/to/repo --no-tests`. Without `--no-tests` the tool runs the target's own test suite once you have said it may (`--trust`); read "What a scan reads, runs and writes" in section 6 first.

From the git URL, without a checkout (this installs the repository's default branch):

```
pip install "ghost-tools @ git+https://github.com/wking53214/ghost_tools.git"
```

To run the tests, the linter and the type checker from a checkout (the optional CNS connection is described in section 2b):

```
pip install -e '.[dev,cns]'
python -m pytest -q
python -m ruff check .
python -m mypy
```

Do not install the bare name `ghost-tools` from PyPI. The only release of that name there is 1.6.0 (checked 2026-10-22), an old upload of this project, not this code, and it has no `cns` extra. Do not install the bare name `cns` either: on PyPI that name is a different project. `Tests/test_install_hints.py` fails if a file a user reads tells them to `pip install` a bare name from this stack.

## 2. Full System Scope & Architectural Depth

```
ghost-buster              present-and-wrong
ghost-buster --profile    repeated work
ghost-buster --mutate     tests that pass with the named thing broken
ghost-triage              human decision, recorded
ghost-writer              worth documenting
blackhole-extrapolator    ones that went up in smoke
stack-census              what each repo promises and what pins it (docs/STACK_CENSUS.md)
ghost-rank                findings ranked by severity and by who depends on the code
```

Seven rules the code is written to: silence is the defect; fail-closed; say what was established (`CONFIRMED` vs `REASONED`); measured before built (`ghost_buster/calibration.json`); memory only adds (ledger never suppresses); tree unmodified except declared comment surgery; a human decides.

Defaults, all 27 detectors and the mutant census: [docs/REFERENCE.md](docs/REFERENCE.md), checked by the test suite. Which failure of AI-assisted work each horseman catches, and which none does: [docs/FAILURE_MODES.md](docs/FAILURE_MODES.md).

222 Python files (everything under the repository root except `Tests/fixtures`; `Tests/test_docs_claims.py` recounts them and fails if this number drifts). Stdlib-oriented CLI, no runtime dependencies, Python 3.11 to 3.13. Kernel scan measures duplication/drift against the `CNS` schema ([public](https://github.com/wking53214/CNS)) when present.

## 2b. Optional CNS connection

`ghost_buster.cns_adapter` connects ghost_tools to CNS in both directions. It is
**optional**: ghost_tools imports and runs without CNS, and nothing loads `cns`
until a CNS-backed function is called. Install the pinned package from a checkout
of this repository with `pip install -e '.[cns]'`, or install just CNS with
`pip install "cns @ git+https://github.com/wking53214/CNS.git@v2.3.0"`. Do not ask PyPI
for a `cns` extra of `ghost-tools`: the project of that name there is an older release
(1.6.0) that has none, and it installs the wrong thing. Without CNS, `FindingGate`, `cns_chain` and
`check_report` raise `CnsNotInstalled` (an `ImportError` naming that command),
and `translate_status` returns its advisory record as before. CNS is never
modified by this package.

- `translate_status` maps one finding `Status` to a `cns.gate` outcome through a
  table. With CNS absent it returns `authority=advisory_only` and no digest.
- `FindingGate` is a `cns.gate.Gate` at the **alpha** end. It answers Ghost's own
  question, "is this finding established well enough to act on, before anything
  is drafted for it", and nothing about what a run's result means (that is the
  Judge's). It takes the mapping Ghost writes (`Finding.as_dict()`, the JSON
  object) or a `ghost_buster.schema.Finding`, reads it with
  `cns.finding.Finding.from_dict`, and maps the status through the same table
  `translate_status` uses: `confirmed`, `confirmed_by_review` and `suppressed`
  are PASS, `reasoned` is RETRY, `rejected` is TERMINAL_BREACH. A row that does
  not meet `cns.finding/1`, content that cannot be digested, and a status
  outside the table are TERMINAL_BREACH (the last differs from `translate_status`,
  which reads an unmapped status as RETRY). Every verdict that judged content is
  bound to `cns.gate.subject_digest` of the whole finding, evidence and
  attributes included; a row that could not be read is unbound.
- `cns_chain()` holds the gate in the `alpha` slot of a `cns.gate.GateChain`.
  `complete()` is `False` by design: Ghost reports findings and has no outcome
  end, so a consumer supplies `omega` from a repository that has one.
- `check_report(report)` reads Ghost's own JSON report (the object with a
  `findings` member, or the old bare list; parsed, as text, or as a file path)
  against `cns.finding.Finding` and returns the rows that meet it and one problem
  per finding that does not, so a drifting field fails ghost_tools' own CI
  instead of a reader's. It changes nothing Ghost emits.

The CNS tests (`Tests/test_cns_*.py`) skip where CNS is absent. The tests
workflow installs the same pin as the `cns` extra, so there they run.
`Tests/test_cns_independence.py` runs with `cns` blocked and holds the package,
the CLI and a real scan working without it.

Migration note, version 1.10.8: the pin moved from the tag `v1.9.0` to the tag
`v2.0.0`, which is the annotated tag that points at commit
`b13e5d2f9e0e4291725f82794b89117c3d840ac1`. The same text is in the `cns` extra of
`pyproject.toml`, in `.github/workflows/tests.yml` and as `CNS_PIN` in
`Tests/test_cns_independence.py`; `Tests/test_workflow_pins.py` and that file hold
them together. The CNS adapter and independence tests were run against the
package installed from that tag. The one breaking change CNS lists for 2.0.0,
`cns.stack.StackPin` requiring a full 40 character commit, is not used anywhere
in this repository.

Version 1.10.10 moved the pin again, from the tag `v2.0.0` to the tag `v2.1.0`, which is the annotated tag
that points at commit `fde931ffa89aebec95647742256ad53033bd3d02`. The same three places carry it.

Version 1.10.12 moved the pin to the tag `v2.2.0`, a lightweight tag, so the tag is the commit
`ce6bd05578a7a3e3cafa0cfa1e9a2cca8a5f171f`. CNS 2.2.0 equals 2.1.0 in the `cns` package; it adds the composition layer
beside it. The same three places carry the pin.
As of 2026-10-31 the CNS pin is the tag `v2.3.0` (a lightweight tag: the tag is the commit `41592fb7b6735abe140f745353c09ba3eed8e7a2`), moved from `v2.2.0` so that the circuit installs against one CNS release; no code in this repository changed.

## 3. What It Does NOT Do / Non-Goals

- Does not govern runtime decisions.
- Does not edit the code it scans. Ghost reports; changing a tree is the job of Warden (the governor). Proposing fixes is Drafter's and the final tidy and README are Burnish's, but Drafter and Burnish are not members of the circuit: they are released from the circuit (owner ruling of 2026-10-29), each still works on its own, and Warden seats them only when asked. The old repair mode, the name annotator and the doc-correction drafter were removed (CHANGELOG 1.10.0) so no two repositories do the same job. A scan with `--no-tests` leaves the folder as it found it; the files it can write on request (`--accept` writes the baseline, `--ledger` the ledger) and the one case where it runs the target's own code are listed in section 6. Held by `Tests/test_tree_immutability.py` and `Tests/test_default_scan_writes_nothing.py`.
- Model claims stay `REASONED` and never self-promote. Held by `Tests/test_authoritative_boundary.py`. The model-backed layer (`ghost_buster.semantic`) is a library with no command line flag and no caller in this repository.

## 4. Brutally Honest Current Status & Gaps

Other tools cover parts of this ground (ruff, mutmut, SonarQube). This repository records no comparison against any of them, so it makes no claim of being better. What it is built around is narrower: a check that did not run says so, and a scan does not call something clean that it could not read.

### What works, and what proves it

Each line names the test, the CI job or the command that shows it. A test file named here means every test in the file passes in CI. The CI jobs are in `.github/workflows/tests.yml`. The run for any head is on the repository's Actions page, and the last checked runs are listed in the CNS repository's `docs/STATUS.md`.

| What works | Proof |
|---|---|
| The test suite passes on Python 3.11, 3.12 and 3.13 | CI job `test` (one job per version) |
| `ruff check .` (rules E, F, W, B) and `mypy` report nothing | The "Lint (hard gate)" and "Types (hard gate)" steps of the same job; `Tests/test_docs_claims.py::test_the_static_gates_are_configured_and_run_in_ci`; the tool versions are pinned and held by `Tests/test_workflow_pins.py::test_ci_installs_the_same_ruff_and_mypy_as_the_dev_extra` |
| The scanner scans its own repository on every push and fails on a new MAJOR or CRITICAL finding | CI job `self-scan`; `Tests/test_self_scan.py` |
| A change does not make the scanner worse on SWIZZLE's archived cases or on ASSAY's answer key | CI job `swizzle-gate (pinned siblings)`, which blocks. The `latest siblings, non-blocking` leg only reports drift and gates nothing. |
| The exit codes 0, 1, 2, 3 and 4 mean what section 6 says | `Tests/test_honest_exit_codes.py`, `Tests/test_report_delivery.py` |
| `--json` is one valid JSON document, including when the scan did not start or crashed | `Tests/test_honest_exit_codes.py::test_a_crash_under_json_still_leaves_valid_json_with_an_error` |
| A check that did not run is listed with its reason, and an incomplete scan is not reported as `ok` | `Tests/test_honest_unmeasured.py`, `Tests/test_unassessable.py` |
| A scan with `--no-tests` leaves the scanned folder as it found it | `Tests/test_tree_immutability.py`, `Tests/test_default_scan_writes_nothing.py`, `Tests/test_trusted_scan_writes.py` |
| A finding keeps its id when the folder path is typed differently or when code above it moves | `Tests/test_ids_ignore_how_the_path_was_typed.py`, `Tests/test_identity_under_motion.py`. Not when its file is renamed (section 4b). |
| The tests catch the defects they name | `Tests/test_mutation.py` and the `Tests/*_mutants.py` files break the code one piece at a time in scratch copies and fail if the suite still passes. `Tests/test_mutant_census.py` recounts them. This shows those listed breakages are caught; it does not show that all of the code is covered. |
| The README's Python file count, detector count, version, relative links and flag list match the repository | `Tests/test_docs_claims.py`, `Tests/test_readme_inventory.py` |
| CI fetches what it runs by content: actions at full commit SHAs, gitleaks checked against a sha256, the gate failing when it has no base revision | `Tests/test_workflow_pins.py`, `Tests/test_install_gitleaks.py`, `Tests/test_swizzle_base.py` |
| Every package, data file and console script that `pyproject.toml` lists exists, and no package folder is left out of the list | `Tests/test_packaging.py` |
| ghost_tools imports and scans with `cns` blocked; with the pinned `cns` the adapter tests pass | `Tests/test_cns_independence.py`; `Tests/test_cns_adapter.py`, `Tests/test_cns_finding_gate.py`, `Tests/test_cns_report_check.py` |

### What does not work, or is not proven

- **Precision on other people's code is not measured.** The calibration records (`ghost_buster/calibration.json`) were measured on repositories of the same owner and the findings were read by the same people. No outside review exists. One measured example of a weak detector: in 1.7.0, 65 `doc_test_count_drift` findings that passed the claim-shape filters, across the library, were read one by one and none was a stale claim about the scanned repository's own current suite.
- **Recall is measured only against ASSAY's answer key**, which is also the owner's. Some failure modes in that key need value-range or semantic reasoning and are not attempted (CHANGELOG 1.10.0). `undefined_self_method` abstains on any class it cannot see whole.
- **Only Python repositories have been measured.** The code-level detectors read Python. Nothing here says how the tool does on a JavaScript or Go repository.
- **Only Linux is tested.** CI runs `ubuntu-latest`. Nothing was run on macOS or Windows.
- **Running the target's tests is not sandboxed.** Ghost blocks a few known side effects, but the target's code runs with your permissions (section 6, "Trust limit").
- **The model-backed layer is not exercised.** `ghost_buster.semantic` has no command line flag and no caller; its output would be `REASONED` and never authoritative.
- **No comparison with ruff, mutmut or SonarQube is recorded here.**
- **The `swizzle-gate` runs against a pinned "tested set"** of SWIZZLE and ASSAY commits, which can be behind their branch heads. A green pinned leg says nothing about their newer commits, and nothing here says the pinned commits work with the other repositories' newest ones (that is the CNS `stack` job).

## 4b. Known defects (open)

1. **The `--version` banner contains a vulgar word.** All six commands print `ghost_buster <version> (<backronym>)`, and the backronym (`BACKRONYM` in `ghost_buster/__init__.py`) spells out an expletive. This is the owner's naming decision, and releases 1.10.6, 1.10.7 and 1.10.8 left it as written on purpose; it is listed so nobody finds it by surprise. `Tests/test_version.py::test_version_string_carries_the_version_and_the_backronym` reads the text back from the same constant, so changing the constant does not break that test.
2. **A baseline cannot follow a renamed file.** A baseline is a set of finding ids, and an id includes the file's path. Reproduced on 1.10.7: a module with one unused function, accepted into a baseline with `--accept`, reported the same finding as new after `git mv m.py n.py`. CHANGELOG 1.7.3 recorded this as still open and no later entry closes it. The ledger (opt-in) does follow renames; the baseline does not.
3. **The consent to run a project's tests can be forged by whoever controls the folder.** Consent is recorded against the `origin` URL, and the URL is read from the target's own `.git/config`. Documented in `ghost_buster/trust.py` and in section 6; not closed. `--no-tests` executes nothing whatever the record says.
4. **`doc_test_count_drift` only flags a claim the suite has grown past.** A README that claims more tests than exist is not flagged. This is deliberate (see the docstring in `ghost_buster/mechanical.py`), and it is a blind spot.
5. **`unverified_status_claim` matches a list of phrases.** A paraphrase such as "ready for production" is not found (`ghost_buster/statusclaim.py` lists the phrases).
6. **Findings that share an identity inside one file are told apart by position.** Twelve `Path(...)` calls in one loop, or several repeats inside one function, get ids that change when one of them moves (CHANGELOG 1.10.0 records this as the documented limit).
7. **The self-scan baseline hides one MAJOR finding**: `long_function` on `_build_parser` in `ghost_buster/cli.py`. The reason is in `.ghost_casefile.json`, and `Tests/test_self_scan.py` requires every baselined finding to have one. It is hidden, not fixed, and it has a consequence: in the self-hosting run (section 4d) Warden counted the hidden finding as a gap, the Judge answered INSUFFICIENT, and the run ended ACCEPT_UNVERIFIED instead of ACCEPT. Splitting `_build_parser` is the way out and has not been done.
8. **The full test suite is slow.** Most of it is the mutant suites, each running a test file in a fresh interpreter. The time is in section 6, "Test suite". On a heavily loaded machine a mutant can time out; `GHOST_MUTANT_TIMEOUT` and the load scaling (1.10.3) make that rarer, and `Tests/test_mutant_harness_timeout.py` tests the scaling, not the absence of timeouts.
9. **A local run without `gitleaks` or `cns` skips tests instead of failing.** The secrets tests skip when `gitleaks` is not on `PATH` and the CNS adapter tests skip when `cns` cannot be imported, with a printed reason. CI installs both, so there they run, but a developer's local run without them is greener than CI. No test fails a run for having skipped.
10. **`docs/REFERENCE.md` still describes readiness as gating "the surgeon's serum".** The surgeon (the old repair mode) was removed in 1.10.0, and the words "surgeon" and "serum" remain in code and docs as a metaphor for the readiness report. Not fixed in this change.

## 4c. What broke and how it was fixed

Newest first. Most entries from 1.10.0 on were found by audit rounds, where a reviewer attacks the repository with probes; earlier ones were found by running the tool on real repositories. "Prevented by" names the test that fails if the defect returns; "no test yet" means none exists. Two entries (1.7.2, 1.7.8) are fixes that were first wrong or incomplete.

- **1.10.14 (2026-10-30), a `--join` path that is not there.** `ghost-buster DIR --join /no/such/folder` (or `--join` a plain file) printed "boundary scan joined 2 repositories", filed no unmeasured row and exited 0, so a typo read as a checked seam. Found by the round-8 audit and reproduced before the fix. Now exit 2 with a line naming the path, for every `--join` and for a path typed at the interactive join prompt. Prevented by `Tests/test_boundary.py::test_a_join_path_that_does_not_exist_is_a_usage_error`, `::test_a_join_path_that_is_a_plain_file_is_a_usage_error`, `::test_one_bad_join_among_good_ones_still_refuses`, `::test_a_bad_join_under_json_is_the_usual_error_envelope` and `::test_a_bad_path_typed_at_the_join_prompt_is_refused_the_same_way`.
- **1.10.9 (2026-10-24), a baseline path that does not exist.** `ghost-buster DIR --baseline /no/such/file.json` was read as an empty baseline: exit 0, `baseline.path` null, no row saying so, although the exit table says an unreadable baseline is exit 2. A mistyped path in CI therefore passed on nothing. Found by the round-6 audit (2026-10-23 and 2026-10-24) and reproduced before the fix. Now exit 2 before the scan; `--accept` may still create the file it names. Prevented by `Tests/test_baseline_integrity.py::test_a_baseline_named_with_baseline_that_does_not_exist_is_a_usage_error` and the tests beside it.
- **1.10.9, ids that needed a suffix depended on the folder.** Two findings with the same detector, file and summary get a suffix hashed from their place, and the place included the finding's detail, which can name the file by its absolute path (`loop_invariant_call` does). The same checkout scanned from two folders therefore gave different suffixed ids, so a committed baseline entry that carried a suffix was stale in every other folder, including every throwaway clone a circuit run uses. Found while building ASSAY's baseline against 1.10.8 (two of this repository's own ids differed between two copies). Now the folder is cut out of the detail before it is hashed. A baseline written from the same folder under the old suffix still matches (it stays among the finding's previous ids); one written in another folder never could. This repository's committed baseline holds no suffixed entry, so none of its ids changed. Prevented by `Tests/test_finding_identity.py::test_the_suffix_of_a_colliding_finding_is_the_same_from_two_folders`, `::test_findings_that_need_a_suffix_still_get_distinct_ids` and `::test_the_suffix_an_earlier_version_wrote_in_the_same_folder_still_matches`.
- **1.10.9, false sentences about the pins.** The README and the comments in `tests.yml` called the SWIZZLE pin the head of SWIZZLE's `main` and said ASSAY's `main` had added only a `recovered-originals/` folder; neither was true. The README also gave a CI time per Python version that the next run contradicted, and said no CNS status page existed after one did. Found by the round-6 audit. The pins are described as the last set this repository's CI tested on its own. Prevented, for the pin wording, by `Tests/test_workflow_pins.py::test_no_pin_is_called_the_head_of_a_siblings_main`; the self-hosting numbers are held by `Tests/test_docs_claims.py::test_the_readme_self_hosting_paragraph_states_what_the_record_says`; a CI time is no longer stated.
- **1.10.7 (2026-10-22), report delivery.** `ghost-buster DIR ... | head -c0` printed a `BrokenPipeError` traceback and exited 3 ("internal error"). The other five commands ended in a traceback and exit 1, the code for "findings". A closed standard output vanished and exited 0. Found by an audit probe. Now one plain line on stderr and the earned exit code; a failed delivery turns an exit of 0 into the new code 4. Prevented by `Tests/test_report_delivery.py`.
- **1.10.7, workflow permissions.** `tests.yml` had no `permissions:` block. Now `contents: read` at the top. Prevented by `Tests/test_workflow_pins.py::test_every_workflow_declares_its_permissions` and `::test_the_tests_workflow_is_read_only_at_the_top_and_no_job_widens_it`.
- **1.10.7, install hints.** The README and the runtime message told users to install `ghost-tools[cns]` by that bare name, which fetches the 1.6.0 upload from PyPI. That release has no `cns` extra, so the wrong code was installed and the CNS adapter stayed unusable. Prevented by `Tests/test_install_hints.py`.
- **1.10.6 (2026-10-21), stale pin comments.** The comment on the SWIZZLE ref called its commit the head of a branch, which was no longer true, and two test names still said "full commit" after the CNS pin became a tag. The CNS pin itself had been a full commit of v1.8.0 (1.10.0), a full commit of v1.9.0 (1.10.4) and, from 1.10.5, the tag. Fixed in 1.10.6, and the refs moved again in 1.10.7. `Tests/test_workflow_pins.py` checks that each comment carries a version and that the README names the SHAs. It cannot check that a version comment is true of the sibling's real head; the non-blocking `latest siblings` leg exists to show that drift.
- **1.10.4 (2026-10-21), a flaky test.** `Tests/test_stack_census.py::test_the_census_changes_nothing_on_disk` failed once on CI because git's background maintenance created `.git/objects/maintenance.lock` between its two snapshots. The fixture now commits with `maintenance.auto=false` and `gc.auto=0`. No separate test of the fixture setting.
- **1.10.4, an orphaned pin.** After ASSAY's branch was squash-merged, the pinned ASSAY commit was no longer on ASSAY's `main`. Re-pinned to a commit on `main`. No test yet checks that a pinned sibling commit is reachable from the sibling's `main`.
- **1.10.3 (2026-10-21), wrong-shaped input files.** `ghost-writer` and `ghost-triage` on an empty or non-JSON findings file printed a traceback and exited 1; `ghost-buster --baseline` on valid JSON of the wrong shape crashed with exit 3; `{}` was accepted as a findings payload and reported an empty result with exit 0. All three are now exit 2 with one line naming the file. Prevented by `Tests/test_findings_file_errors.py`.
- **1.10.3, shallow checkout.** `resolve-swizzle-base.sh` read a shallow clone's root as the repository's first commit and skipped the gate, although 1.10.1 said a shallow checkout fails. Prevented by `Tests/test_swizzle_base.py::test_a_shallow_clone_fails_instead_of_reading_its_cut_off_root_as_the_first_commit`.
- **1.10.3, mutant timeout.** The fixed 120 second per-mutant timeout failed four tests under load that pass alone. Now scaled by load, capped at 900 seconds. Tested by `Tests/test_mutant_harness_timeout.py` (see 4b item 8 for what it does not cover).
- **1.10.2 (2026-10-21), CI never ran on this branch.** `tests.yml` ran only on pushes to `main` and on pull requests, so a push to the working branch started no CI. Now `claude/**` too. Prevented by `Tests/test_workflow_pins.py::test_the_workflow_runs_on_main_pushes_pull_requests_and_the_horsemen_branches`. The same release installed numpy and matplotlib in the gate, because ASSAY 0.11.1 exits 1 on a claim that cannot run (`::test_the_gate_installs_the_numpy_and_matplotlib_that_assays_verifier_needs`).
- **1.10.1 (2026-10-17), five audit findings.** A malformed `--casefile` printed a traceback and exited 3 (now exit 2; `Tests/test_casefile_unreadable.py`). Only `ghost-buster` accepted `--version`; the other five exited 2 (`Tests/test_version.py::test_every_console_script_prints_the_version_and_exits_zero`). The workflow ran a downloaded gitleaks unchecked (`Tests/test_install_gitleaks.py`). The swizzle gate passed with a warning when it had no base revision (`Tests/test_swizzle_base.py`). `actions/checkout` was pinned to a SHA that is v4.4.0 under a comment saying v4 (`Tests/test_workflow_pins.py::test_every_action_is_pinned_to_a_full_commit_sha_with_its_tag_in_a_comment` checks the comment's form, not that it names the right release).
- **1.10.0 (2026-10-17), housekeeping the audit forced.** 1.9.1 was declared by `pyproject.toml`, the README and a tag while about 290 lines of changes sat under "Unreleased", so two different programs were both called 1.9.1 (`Tests/test_docs_claims.py::test_the_newest_changelog_release_is_the_declared_version_and_dated`). The README said 199 Python files while the tree held 212 (`::test_the_readme_python_file_count_is_the_actual_one`). The README and STACK.md called CNS private after it was made public (`::test_no_document_calls_cns_private`). A CI comment said the baseline held three MAJOR findings while it held one (`::test_the_ci_comment_about_the_baseline_matches_the_baseline`). `--ledger-path` silently created every missing parent folder (a probe created `/nonexistent/dir`); now exit 2 unless `--create-ledger-dir` (`Tests/test_ledger_path.py`). Two tests failed after `pip install .` because the built `egg-info` answered the version lookup (`Tests/test_version_provenance.py`).
- **1.10.0, packaging.** `ghost_buster/production/` was missing from `packages=` (so no wheel contained it), nothing imported it, and its `signing.py` carried a hardcoded development signing key as a default; it was deleted. Separately, a change had deleted `ghost_writer/polish` but left it in the package list, so every `pip install` from git failed. Prevented by `Tests/test_packaging.py::test_every_listed_package_is_a_real_package_folder` and `::test_every_package_folder_in_the_tree_is_listed_so_it_ships`.
- **1.10.0, static gates.** ruff had run only its defaults, and mypy was not run. Turning mypy on found 103 errors in 24 files, among them real defects: `blackhole_extrapolator --ecosystem --json` passed an argument count its helper does not take, and a branch in `mutation._restated_literals` dereferenced `.attr` on a call whose function was not an attribute. Now hard gates in CI (`Tests/test_docs_claims.py::test_the_static_gates_are_configured_and_run_in_ci`).
- **1.10.0, honest exit codes and JSON.** A crash used to exit 1, the same as "findings found". Fixed so 0 clean, 1 findings, 2 did not start, 3 crashed (`Tests/test_honest_exit_codes.py`). The `--json` output became an object with an `unmeasured` list, which broke readers of the old bare list; this was announced as breaking in CHANGELOG. A default scan used to write `.ghost_ledger.json` into the scanned folder; the ledger is now opt-in (`Tests/test_default_scan_writes_nothing.py`). Found by a red team.
- **1.10.0, a copied integration layer.** 17 modules copied from SWIZZLE had arrived together on 2026-09-18 and nothing imported them. Four of their tests imported `swizzle.integration` and errored at collection without SWIZZLE installed, which made the `tests` job on `main` red, and removing them also cleared 62 `ruff` errors. Deleted, and a `swizzle-gate` job was added in the same change. No test yet; the CI `test` job is what went red.
- **1.10.0, the bytecode test.** Under Warden, which redirects bytecode with `PYTHONPYCACHEPREFIX`, the mutant that deletes the scanner's own `PYTHONDONTWRITEBYTECODE` export survived, so the suite was red. Found when the circuit ran on ghost_tools itself. `Tests/test_testsuite.py::test_scan_writes_nothing_into_the_project` now clears that variable.
- **2026-10-06 to 2026-10-08, before 1.10.0 (no version recorded in CHANGELOG).** An incomplete merge left `mechanical.py`, `structure.py` and `correlate.py` unable to import or finish a scan; restored in three commits (`4370423`, `ded6fcb`, `eb76567`). A commit added eight mutants for the serum module, seven of which named source text that does not exist and the eighth duplicated an existing one; the 12 tests that came with them asserted behaviour the module does not have, so 16 tests failed permanently and the mutant count read 759 against 751 stated. Reverted in `7fe5704`. The change that removed the repair mode (#89) left README flags that no longer existed, fixed in `3beaf55`. Prevented, for the mutants, by the harness assertion `mutation site not found exactly once` (`Tests/mutant_harness.py`) and `Tests/test_mutant_census.py`; for the flags by `Tests/test_readme_inventory.py::test_every_flag_the_ghost_buster_section_mentions_exists`. The merge damage itself: no test yet beyond the CI `test` job failing on import.
- **1.9.1 (2026-09-17), a fixture that could not do its job.** `Tests/fixtures/wizzle` was a repository copied in as static files; pytest collected its own `Tests/` as real tests and errored, so a green suite exited non-zero, and the self-scan reported a MAJOR `unresolvable dependency` against this repository permanently. Deleted; `norecursedirs = ["fixtures"]` in `pyproject.toml` keeps fixtures from being collected. No test of that setting.
- **1.9.1, the lint gate had been red on main since #64.** Nine ruff errors, all in test files, so a step the workflow called a hard gate had failed on every push. Fixed by `ruff --fix` and by hand. Later (2026-10-14) CI was changed to run the pinned ruff as `python -m ruff`, not whatever `ruff` is on `PATH`.
- **1.9.1, two tests that depended on the Python version.** Two of 1.8.0's tests assumed setuptools is installed in a new virtualenv; Python 3.12 stopped doing that. The CI matrix caught it, which no local run on 3.11 could. They now assert on a pure function of `pyproject.toml`.
- **1.8.0 (2026-09-17), three defects walked past on a real repository.** The scan read only `[project]` in `pyproject.toml`, so it reported `setuptools` (declared in `[build-system].requires`) as an undeclared dependency at MAJOR, which was wrong, and missed two real defects in the same files: two files declaring one package with drifted descriptions, and a `testpaths` entry naming a directory that does not exist. Found by pointing the tool at fortress-kernel. Tests in `Tests/test_structure.py` and `Tests/test_project.py`.
- **1.7.8 (2026-09-12), a fix that reasoned wrongly.** 1.7.7 lowered the severity of an enum member that only a test produces. That was the wrong reasoning: a test file is the cheapest thing to add, so one test naming the state still silenced the finding at the cost of one notch. 1.7.8 removed the discount and graded by what the evidence costs to fake. It also retired two false positives this repository had hand-confirmed as true. Prevented by `Tests/test_unreachable_declared_state.py::test_a_test_producing_it_does_not_buy_a_lower_severity`.
- **1.7.1 and 1.7.2 (2026-09-12), a fix reported done that was not.** The old repair mode wrote through a symlinked README to a file outside the repository. 1.7.1 fixed two of the three writers and said the job was done; 1.7.2 found the third (a maintained count block) by testing a case one dimension away. The whole mode, with its tests, was removed in 1.10.0, so no test remains.
- **1.7.3 (2026-09-12), three defects in what the tool certifies.** A suite with a module that failed to import was certified as passing, because `passed == collected` ignores what never collected. Finding ids included a number the run had just measured, so a baseline entry stopped matching when a test was added. Tests depended on the global git configuration of the machine running them (sixty failed at once when a commit signer ran out of file descriptors); `Tests/conftest.py` now isolates git config. Tests: `Tests/test_correlate.py::test_a_suite_with_a_file_that_never_ran_is_not_green`, `Tests/test_finding_identity.py`; the git isolation has no test of its own.
- **1.7.5 to 1.7.6 (2026-09-12), a detector with its own blind spot.** `unreachable_declared_state` counted a member named in a constant set as produced, so on its own repository it missed a member of exactly the shape it was built to find. `dead_code` called every decorated function dead (51 of 85 findings on one repository, all live commands). Tests: `Tests/test_unreachable_declared_state.py::test_membership_of_a_constant_table_is_not_production` and `Tests/test_ghost_buster.py::test_a_decorated_function_is_not_dead`.
- **1.4.0 (2026-09-11), documents that nothing checked.** `__version__` read installed package metadata before the source, so a ledger run could be stamped with a version the running code was not (`Tests/test_version_provenance.py::test_the_running_source_wins_over_installed_metadata`). Four places stated a mutant count of 454 while the suites held 548 (`Tests/test_mutant_census.py`). A release (1.0.2) had shipped with no CHANGELOG heading.
- **1.3.0 (2026-09-11), two defects with one identity.** Two findings that agreed on detector, path and summary shared an id, so accepting one hid the other; measured on 38 repositories, 8 colliding pairs, two of them separate committed secrets four lines apart. Ids now get a `-2`, `-3` suffix (`Tests/test_identity_under_motion.py`).
- **0.17.2 (2026-09-10).** Reading a baseline entry back re-derived its id and so re-identified findings already accepted (17 committed baselines, 2,464 entries). `Tests/test_baseline_id_mutants.py`.
- **0.13.0 (2026-09-09), silence about skipped checks.** The branch, test and secrets checks were opt-in and a run that skipped one printed nothing; a scan reporting 34 findings never said test status had gone unexamined. All three are on by default and every check reports performed, impossible or declined (`Tests/test_honest_unmeasured.py`, `Tests/test_defaults.py`).
- **0.8.1 (2026-09-09).** A non-UTF-8 branch diff crashed the whole scan, and every clone-shaped checkout counted one phantom branch. `Tests/test_branches.py`.
- **0.3.1 (2026-09-02).** One repository with a `.venv` in its working tree reported 3,789 findings, 3,702 of them inside `site-packages`. Virtualenvs, vendored trees, VCS folders and caches are now skipped. No test is named in CHANGELOG for it.

## 4d. Self-hosting

This repository's scanner scans this repository on every push (CI job `self-scan`). That is not the same as the full circuit governing it. The full circuit as it was then (before the owner's ruling of 2026-10-29 released the Drafter, Burnish and WATCHER_MCU from it; the Warden seated the Drafter, Judge and Burnish around this scanner) was run over a fresh clone of this repository at commit `5a9154d3c76670f5bf1f46d845acadfed46d7bc8` (version 1.10.8) on 2026-10-22 and 2026-10-23, one run. The record is `docs/evidence/SELFHOSTING_2026-10-23.md` in the [CNS repository](https://github.com/wking53214/CNS/blob/claude/horsemen-production-status-5wsndb/docs/evidence/SELFHOSTING_2026-10-23.md) (on the CNS branch `claude/horsemen-production-status-5wsndb` until that branch is merged). For ghost_tools it recorded: decision ACCEPT_UNVERIFIED (Warden exit 3), not ACCEPT. The loop converged and the finishing change stood against a green suite (2432 passed, 38 skipped, all skips because `gitleaks` was not installed there), but the committed `.ghost_baseline.json` hides one finding (`long_function` on `_build_parser`, see section 4b item 7), Warden counts that as a gap, and the Judge answered INSUFFICIENT with "these checks never ran: ghost_partial". The finishing change was put back and held. The record lists 7 declined checks in every run (mutate, kernel, structure, tests, project, secrets, correlate), 10 gaps in this one, and 132 Ghost findings still standing at the end.

What the record does not mean: an ACCEPT in that record (other repositories ended ACCEPT) still carries those 7 declined checks as gaps, so it does not mean there are no secrets, no weak tests and no structural problems. The record covers commit 5a9154d, not 1.10.9 or later, and this repository was not re-run after the finisher was fixed (Burnish 0.3.12, which stopped writing suite counts into READMEs; that fix mattered to SWIZZLE and JUDGE, not here). Nothing is claimed about a run on the current commit.

## 4e. Ceilings code cannot fix

- **Young.** The history starts on 2026-08-21 (`git log --reverse`).
- **One human maintainer**, William King. A large share of the commits are authored by an AI assistant (`git shortlog -sn --all` shows the split). Nobody else is recorded as having reviewed the code.
- **No outside users are known.** Nothing in this repository records anyone using it besides the owner.
- **Releases are tagged by the owner**, not by CI and not by a change. Check the repository's tags and releases on GitHub for what exists; this README does not list them.
- **Every pin is a snapshot.** The versions of CNS, SWIZZLE and ASSAY named here were current when this version was cut.

## 5. Core Invariants & Guarantees

Each rule names the test that holds it.

- A check that cannot run is reported, not skipped: a file that cannot be parsed is an `unassessable_file` finding (`Tests/test_unassessable.py`), and any other check that did not run is an `unmeasured` row with a reason (`Tests/test_honest_unmeasured.py`).
- A corrupt ledger fails the run instead of starting over: `Tests/test_ledger.py::test_a_corrupt_ledger_fails_the_run_rather_than_starting_over`.
- A directory that is not a git repository is not reported as a clean secrets scan: `Tests/test_secrets.py::test_non_git_directory_does_not_read_as_a_clean_scan` (needs `gitleaks`).
- The ledger only adds to what is remembered, and accepting a finding into a baseline does not erase its history: `Tests/test_ledger.py::test_the_ledger_only_ever_adds`, `::test_accepting_into_the_baseline_does_not_erase_memory`.
- A person decides what happens to a finding (fix, suppress or document); `ghost-triage` records that decision: `Tests/test_triage.py`.

## 6. Inputs, Outputs & Type Contracts

CLI over a git work tree. Findings: severity, `CONFIRMED`/`REASONED`, evidence. Calibration JSON per detector.

### dead_code facts contract

Each `dead_code` finding carries these attributes so a fixer need not re-derive them. Ghost only reads files to produce them; it measures and never decides.

| attribute | meaning |
|---|---|
| `name` | the function or class name |
| `kind` | `function` or `class` |
| `line_start`, `line_end` | where the definition sits |
| `framework_hook` | `yes` when something outside the Python call graph reaches the name, `no` otherwise. A `yes` means do not act on the finding. |
| `referenced_by` | present only when `framework_hook` is `yes`: a short plain reason, such as `pyproject.toml console script 'tool'` or `named as a string in settings.yaml` |
| `dynamic_lookup_possible` | `yes` when the scanned code looks names up by a computed value (`importlib.import_module(name)`, `__import__(name)`, `getattr(obj, name)`, `globals()[expr]`, `vars()[expr]`, `locals()[expr]`, `obj.__dict__[expr]`, `sys.modules[expr]`, or `.get(expr)` on any of those), `no` otherwise. The flag covers the whole scanned set (every module and package in it). When `yes`, "dead" may be wrong even if `framework_hook` is `no`. |
| `dynamic_lookup_count` | how many computed lookups were seen |

What counts as a use (so the name is not reported dead at all):

- `from x import y` uses `y`, including a re-export in an `__init__.py` and an import inside `if TYPE_CHECKING:`. `from x import *` uses every public name in a module called `x`.
- `__all__` however it is built: `= [...]`, `: list[str] = [...]`, `+= [...]`, `= a + b`, `.extend([...])`, `.append("x")`.
- A name inside a string annotation or forward reference: `def f(a: "Foo")`, `x: "list[Foo] | None"`, `Optional["Foo"]`, `Dict[str, "Foo"]`, `cast("Foo", v)`, `TypeVar("T", bound="Foo")`. `# type:` comments are not read.
- A name in a `.pyi` stub file sitting in the same folder as a scanned module (the stub is the declared public surface).

What counts as a reference (the name is still reported, but flagged `framework_hook: yes`):

- Entry points in `pyproject.toml` (scripts, gui-scripts, entry-points, poetry scripts and plugins), `setup.cfg`, and literal strings in `setup.py`. The target's module must match the file that defines the name. If the target module cannot be found in the repo, the name alone is matched and the reason says so.
- A computed lookup whose key starts with a literal prefix (`globals()["_cmd_" + x]`, `getattr(mod, f"cmd_{x}")`): every name starting with that prefix is flagged, and `referenced_by` names the prefix.
- A string equal to the name as the second argument of `getattr`, `hasattr` or `setattr`, or inside a list, tuple, set or dict of strings in any scanned Python file.
- The name as a whole word in a config or data file (yaml, yml, json, toml, ini, cfg, txt, conf, env) at the repo root or inside a folder such as `config`, `settings` or `.github`. Lock files, `requirements*.txt` and files over 1 MB are skipped. README and other markdown prose never count.

Limits: `setup.py` is read with a text pattern, not run, so entry points built in code are missed. `pyproject.toml` and `setup.cfg` are read only for entry points, not for other settings. A computed lookup can be flagged but never resolved. The repo-level attributes appear when a project root (`pyproject.toml`, `setup.cfg`, `setup.py` or `.git`) is found or a computed lookup is seen.

### Exit codes

| Code | Meaning | What a caller should do |
|---|---|---|
| 0 | The scan ran. Nothing new at MAJOR or CRITICAL. | Read `status` (below): 0 with `"incomplete"` is not a clean bill of health. |
| 1 | The scan ran and found something new at MAJOR or CRITICAL. | Read the findings. This is the tool working. |
| 2 | The scan did not start: bad arguments, target missing or unreadable, unreadable baseline (including a `--baseline` file that does not exist), ledger or case file, nothing to scan. | Fix the command or the inputs. A plain reason is on stderr. |
| 3 | The scan started and the tool crashed (an unhandled error inside ghost_buster). | Treat as "unknown", never as "findings". The reason is on stderr, with a traceback. |
| 4 | The run would have exited 0, but its report could not be delivered: standard output is closed, full (`/dev/full`, a disk with no room) or failing. | The scan ran; nothing reached you. Fix where stdout goes and run again. One plain line on stderr says why. |

Anything other than 0 or 1 means no verdict was reached, except that a 4 says the verdict was reached and not delivered. `--verify-chain` keeps its own use of 1 (a break in the ledger chain).

Report delivery, for all six commands (`ghost-buster`, `ghost-writer`, `ghost-triage`, `blackhole-extrapolator`, `stack-census`, `ghost-rank`): a reader that goes away (`ghost-buster DIR | head -3`, a broken pipe) is not an error of the run, so the command finishes, writes one plain line to stderr and exits with the code it earned (0, 1 or 2 as above), with no traceback. Any other delivery failure (standard output closed before the command started, a full device, an I/O error) writes the same one line and turns an exit of 0 into 4; an exit that was already non-zero (1 findings, 2 did not start, 3 crashed, 130 interrupted) is kept, so a crashed scan never looks clean. `--version` and `--help` follow the same rule. The code is `ghost_buster/delivery.py`; `Tests/test_report_delivery.py` runs all six commands against a pipe nobody reads, a closed file descriptor 1 and `/dev/full`.

### `--json` output

An object, always valid JSON, including on codes 2 and 3:

- `status`: `"ok"` (every check that was supposed to run ran), `"incomplete"` (something that should have run did not, so an empty `findings` is not clean), or `"error"` (no scan; see `error`).
- `exit_code`, and `error` (`null`, or `{"kind": "usage" | "crash", "message": "..."}`).
- `findings`: the list of finding records (this used to be the whole output).
- `scan`: `files_scanned`, `files_skipped` (left out by exclusion rules), `files_unparsable`, and `unparsable` (file and reason for each; a file over the size limit, a file too deeply nested to parse and a file that ran out of memory are listed here). Also `skipped_dirs` (each excluded directory name met, with `dirs` and `files` counts, at most 20 listed, `skipped_dirs_more` says how many were cut), `symlinked_dirs` (symlinked directories that were not followed and whose files are scanned under no other name, with the `files` behind each; same cap), `python_files_analysed`, and `max_file_bytes`.
- `baseline`: `{"path": <string or null>, "suppressed": <number>}`. `path` is the baseline file in effect (null when there is none); `suppressed` is how many findings it hid from `findings`. A baseline named with `--baseline` is your choice and only reported. A baseline found in the scanned folder that hid anything adds an `unmeasured` row (`check: "baseline"`, `by_request: false`) and makes `status` `"incomplete"`: whoever controls the folder controls what the report omits. Consumers should treat `suppressed > 0` as a gap.
- `unmeasured`: one row per check that did not run: `check`, `state` (`declined`, `could_not_run`, `not_run`), a plain `reason`, and `by_request` (true when you asked for that, such as `--no-tests`; false when the tool could not, such as no git or no gitleaks). A detector that raised shows up as `structural` with the detector names and errors in `detail`. Unparsable files show up as `parse`. A scan that analysed no Python file at all shows up as `python` (`none_analysed`). `status` is `"incomplete"` when any row has `by_request` false.

Every mode keeps this shape under `--json`. `--verify-chain --json` returns the envelope with a `chain` key (`runs`, `broken`, `breaks`, `report`) and the exit code above; it reads the ledger and scans nothing. Ctrl-C exits 130 with `status: "error"` and `error.kind: "interrupted"`. The one exception is `--priors --json`, which is data about the case file rather than a scan: it prints a bare JSON list of per-detector rows (an error there still prints the error envelope). While `--json` runs, anything printed by the code goes to stderr, so stdout is one JSON document.

Readers that expect the bare list should read the `findings` key. `FindingSet.from_json` accepts both.

### What a scan reads, runs and writes

- **Git.** Every git command goes through `ghost_buster/gitsafe.py`. The target's `.git/config` can name programs (`diff.external`, `core.fsmonitor`, hooks, textconv drivers, `ext::` transports), so every call overrides those on the command line (`diff.external` empty, `core.fsmonitor` false, `core.hooksPath` pointed at `/dev/null`, `protocol.ext.allow` never, and more), switches off external diff and textconv for diff, show and log, ignores the system git config, never opens a pager or prompt, and sets `GIT_OPTIONAL_LOCKS=0` so git does not refresh `.git/index`. The same environment is given to gitleaks, and its own `git log` is told to skip external diff and textconv. Your own `~/.gitconfig` is still read.
- **Size and poison files.** A file over `--max-file-size` (default 5 MB; `$GHOST_MAX_FILE_BYTES` also works; `5M`, `512K` accepted) is never read: it is listed under `scan.unparsable` and the status is `incomplete`. A file that makes the parser run out of recursion or memory is listed the same way and the scan carries on.
- **Skipped directories** (`build`, `dist`, `node_modules`, `venv`, `.tox`, caches, VCS directories, anything given to `--exclude`) are named on stderr and in `scan.skipped_dirs`, with counts. Symlinked directories are never followed; see `scan.symlinked_dirs`.
- **Writes.** With `--no-tests`, a scan writes nothing into the folder (the ledger is opt-in, see below). With tests on (the default) and consent recorded, the target's own test suite runs. Ghost blocks pytest-benchmark (`-p no:benchmark`, which is what created `.benchmarks/`), turns off the pytest cache and bytecode files, points hypothesis and coverage state at a temporary directory, and stops git from refreshing `.git/index`. What the target's tests write on purpose, Ghost cannot prevent: it is the target's code, run because you consented.
- **Trust limit.** Consent is recorded against the `origin` remote URL, and that URL is read from the target's own `.git/config`. Anyone who can write that file can make a different checkout claim the URL of a repository you trust, and the next test or mutation run executes their code. Ghost does not close this, because a fresh clone of your own repository not asking again is the point of the design (see `ghost_buster/trust.py`). If you scan folders you did not make, use `--no-tests`, which executes nothing whatever the consent record says.

### Ledger and finding ids

The ledger is opt-in: a default scan writes nothing into the folder it scans. Use `--ledger` to keep history in `<path>/.ghost_ledger.json`, or `--ledger-path FILE` (which also turns it on) to keep it anywhere else. `--no-ledger` still works.

`--ledger-path` fails closed: the file's folder must already exist, or the scan stops before it starts (exit 2, a plain reason on stderr, the usual `status: "error"` envelope under `--json`) and nothing is created. A mistyped path used to create every missing folder on the way, silently. Pass `--create-ledger-dir` to say you want the folders made. A path that is itself a folder, or whose parent is a file, is refused either way.

### Diagnostics and logging

Everything the tools write to stderr (receipts for declined checks, warnings, the reason a scan did not start) goes through the stdlib `logging` module, logger `ghost_tools` (children `ghost_tools.<module>`). stdout is the report or the one `--json` document and is never touched by logging; exit codes do not depend on it. By default the records appear on stderr as the bare message, exactly as before. `--verbose` (`-v`, accepted by every command) adds debug records, prefixed `<logger>: debug:`. `GHOST_TOOLS_LOG=DEBUG|INFO|WARNING|ERROR` sets the level without the flag (an unrecognised value is reported and INFO is used; `--verbose` wins; WARNING or ERROR hides the INFO receipts, which is your explicit choice). A program that embeds the library can attach its own handlers to the `ghost_tools` logger.

### Releases

The version is declared once, in `pyproject.toml`; `ghost_buster.__version__` and `--version` read it back. `CHANGELOG.md` has a dated section per release and an `Unreleased` section on top. A release is a tag `vX.Y.Z` on the commit that bumped the version; the publish workflow also accepts `VX.Y.Z` (the 1.9.1 tag was written that way) and refuses a tag whose version differs from `pyproject.toml`. Tags are created by the owner, not by CI or by the changes themselves. Check the repository's tags and releases on GitHub for what exists; this file does not list them.

#### Bumping the CI pins

CI pins everything it fetches by content. Each GitHub Action is a full commit SHA with its release in a comment (resolve one with `git ls-remote https://github.com/<owner>/<action> refs/tags/<tag> 'refs/tags/<tag>^{}'` and use the peeled `^{}` line when there is one). The `swizzle-gate` siblings (SWIZZLE, ASSAY) are pinned to this repository's "tested set": the last SWIZZLE and ASSAY commits this repository's CI tested on its own (SWIZZLE `522658415b026ac3211d3fc130ba7da7c77cc400`, 0.8.5; ASSAY `a1732f2bf3748235661f65b96e590a6d44ace71c`, 0.11.3). They are not claimed to be the head of either repository's `main`, and one or more commits behind a sibling's branch head is expected. Whether the landing set of all the repositories works together is checked by the `stack` job in the CNS repository, not here; to move a pin, read the sibling's new head with `git ls-remote`, run the job against it and change the SHA and its version comment in the same commit. The gate installs numpy and matplotlib into the interpreter that runs ASSAY's verifier (ASSAY 0.11.1 exits 1 on a skipped claim, and the claims that need them skip without them; numpy 2.5.4 needs Python 3.12 or newer, so Python 3.11 gets 2.4.6). The workflow runs on pushes to `main`, on pushes to `claude/**` branches and on pull requests. CNS is pinned in the workflow, in the `cns` extra and in `Tests/test_cns_independence.py` together. gitleaks is installed by `.github/scripts/install-gitleaks.sh` and the job fails if the download's sha256 is not the digest written in `tests.yml` (the one in the release's own checksums file). The gate's base revision comes from `.github/scripts/resolve-swizzle-base.sh`: a pull request or a push to a repository with history that has no reachable base fails the gate; only the repository's very first commit is skipped, with a warning. `Tests/test_workflow_pins.py`, `Tests/test_install_gitleaks.py` and `Tests/test_swizzle_base.py` hold all of this.

A finding's id hashes the detector, the file's path relative to the scanned folder (posix slashes) and the summary, so the way the folder was typed (`./x`, `x/`, absolute, a symlink, another working directory) does not change it. The path is hashed in Unicode NFC form, so a file name written composed (Linux, git) or decomposed (macOS) has one id; the report still shows the name the filesystem gave. Ids from earlier versions, including the spelling an unnormalised non-ASCII path had before, are still recognised by the baseline, the ledger history and retired case-file decisions for the same finding.

Test suite: `pip install -e ".[dev]"` (pytest and pytest-xdist; `addopts = "-n auto"` needs the latter) and run `pytest`. It is slow because most of it is the mutant suites: on 2026-10-22 one full run on Python 3.12 took about eighteen minutes on a four-core machine that other jobs were also using, and each CI run lists how long its job for each Python version took (for example run 39835317208). The hand-mutant suites run each mutant's test file with a timeout of 120 seconds. `GHOST_MUTANT_TIMEOUT` (seconds, a positive number; anything else is an error) sets that base, a one-minute load average above the CPU count multiplies it by load/CPUs (at most 4x), and no timeout ever exceeds 900 seconds, so a hung mutant still ends the run. The counts of passed and skipped tests are not written here: a number in prose goes stale, and the CI log is the record. The skips are not bugs. Some tests need the `gitleaks` binary and some need the `cns` package, and skip themselves, with the reason, where it is absent; the tests workflow installs both, so there they run:

- `Tests/test_secrets.py`, `Tests/test_secrets_disclosure.py`, `Tests/test_secrets_mutants.py`: skip with "gitleaks is not installed". To run them, put a `gitleaks` binary (v8, from the gitleaks project releases) on `PATH`.
- `Tests/test_cns_adapter.py`, `Tests/test_cns_finding_gate.py` and `Tests/test_cns_report_check.py`: skip when `cns` cannot be imported. Install the pinned package with `pip install -e '.[cns]'` from a checkout and they run. `Tests/test_cns_independence.py` needs nothing and always runs.

The static gates are `python -m ruff check .` (rules E, F, W, B) and `python -m mypy` (configuration and the few justified exceptions in `pyproject.toml`); both are hard gates in CI on Python 3.11, 3.12 and 3.13.

No test in the suite is marked expected-to-fail (`grep -rn "mark.xfail" Tests` finds only sample source text that the detector tests feed to the scanner).

## 7. Stack Integration Topology

```text
SWIZZLE attack worlds  →  ghost_buster  →  findings
ASSAY specimens   →  known-damage corpus; `swizzle assay` scores this tool against it
Warden                →  runs ghost_buster to observe, then re-inspect after an authorized change
                          (any actor's change enters through Warden's claim seat, the Judge decides;
                          the circuit is five repositories, Drafter, Burnish and WATCHER_MCU are released from it, see STACK.md)
composition-engine     →  retired, folded into CNS (cns_composition.super_gate); GhostToolsAdapter now lives in cns_composition (one adapter, optional)
observe-perceive       ✗ does not import
swizzle-gate CI        replays SWIZZLE cases and ASSAY specimens against this tool (no secret needed)
```

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Copyright 2026 William N. King. Prefer this README plus `CHANGELOG.md` over folklore.
