# ghost_tools

Codebase **integrity toolkit**: things that are present and wrong, documentation drift, duplication, dead/vacuous tests, secrets, structural ghosts. Version 1.10.0 (`pyproject.toml`; see CHANGELOG.md). Assurance loop: **this scanner ← [`SWIZZLE`](https://github.com/wking53214/SWIZZLE) + [`ASSAY`](https://github.com/wking53214/ASSAY) specimens**.

## 1. Pipeline Position & Role

**ASSURANCE**, off the live decision path. CI-shaped. Does not admit, decide, or execute governed actions. Commercial red team: **product candidate** (small ACV, fast cycle) for VP Engineering where AI-written code makes green CI meaningless.

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

Seven rules (each from a real defect): silence is the defect; fail-closed; say what was established (`CONFIRMED` vs `REASONED`); measured before built (`ghost_buster/calibration.json`); memory only adds (ledger never suppresses); tree unmodified except declared comment surgery; a human decides.

Defaults, all 27 detectors and the mutant census: [docs/REFERENCE.md](docs/REFERENCE.md), checked by the test suite. Which failure of AI-assisted work each horseman catches, and which none does: [docs/FAILURE_MODES.md](docs/FAILURE_MODES.md).

213 Python files (everything under the repository root except `Tests/fixtures`; `Tests/test_docs_claims.py` recounts them and fails if this number drifts). Stdlib-oriented CLI, no runtime dependencies, Python 3.11 to 3.13. Kernel scan measures duplication/drift against the `CNS` schema ([public](https://github.com/wking53214/CNS)) when present.

## 2b. Optional CNS connection

`ghost_buster.cns_adapter` connects ghost_tools to CNS in both directions. It is
**optional**: ghost_tools imports and runs without CNS, and nothing loads `cns`
until a CNS-backed function is called. Install the pinned package with
`pip install 'ghost-tools[cns]'`. Without it, `FindingGate`, `cns_chain` and
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

## 3. What It Does NOT Do / Non-Goals

- Does not govern runtime decisions.
- Writes nothing into the code it scans. Ghost reports; changing a tree is the job of Warden (the governor), proposing fixes is Drafter's, and the final tidy and README are Burnish's. The old repair mode, the name annotator and the doc-correction drafter were removed so no two repositories do the same job.
- Model claims stay `REASONED` and never self-promote.

## 4. Brutally Honest Current Status & Gaps

Crowded category (ruff, mutmut, Sonar). Differentiation is fail-closed silence reporting + SWIZZLE adversarial loop. Calibration records with no corpus must say so. CNS-aware scan needs the optional, public `CNS` package (`pip install 'ghost-tools[cns]'`). Commercial audit used this tool on the portfolio and found real vacuous tests. That is the existence proof, not a market.

## 5. Core Invariants & Guarantees

Unrunnable check → finding, not a skip. Unreadable ledger fails the run. Non-git directory hard-stops secrets scan. Ledger never lowers severity. Human triage is the gate for fix/suppress/document.

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

Limits: `setup.py` is read with a text pattern, not run, so entry points built in code are missed. `pyproject.toml` and `setup.cfg` are read only for entry points, not for other settings. A computed lookup can be flagged but never resolved. The repo-level attributes appear when a project root (`pyproject.toml`, `setup.cfg`, `setup.py` or `.git`) is found or a computed lookup is seen. If `tomllib` is missing (Python 3.10), `pyproject.toml` is skipped and `reference_scan_notes` says so.

### Exit codes

| Code | Meaning | What a caller should do |
|---|---|---|
| 0 | The scan ran. Nothing new at MAJOR or CRITICAL. | Read `status` (below): 0 with `"incomplete"` is not a clean bill of health. |
| 1 | The scan ran and found something new at MAJOR or CRITICAL. | Read the findings. This is the tool working. |
| 2 | The scan did not start: bad arguments, target missing or unreadable, unreadable baseline, ledger or case file, nothing to scan. | Fix the command or the inputs. A plain reason is on stderr. |
| 3 | The scan started and the tool crashed (an unhandled error inside ghost_buster). | Treat as "unknown", never as "findings". The reason is on stderr, with a traceback. |

Anything other than 0 or 1 means no verdict was reached. `--verify-chain` keeps its own use of 1 (a break in the ledger chain).

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

The version is declared once, in `pyproject.toml`; `ghost_buster.__version__` and `--version` read it back. `CHANGELOG.md` has a dated section per release and an `Unreleased` section on top. A release is a tag `vX.Y.Z` on the commit that bumped the version; the publish workflow also accepts `VX.Y.Z` (the 1.9.1 tag was written that way) and refuses a tag whose version differs from `pyproject.toml`. Tags are created by the owner, not by CI or by the changes themselves.

A finding's id hashes the detector, the file's path relative to the scanned folder (posix slashes) and the summary, so the way the folder was typed (`./x`, `x/`, absolute, a symlink, another working directory) does not change it. The path is hashed in Unicode NFC form, so a file name written composed (Linux, git) or decomposed (macOS) has one id; the report still shows the name the filesystem gave. Ids from earlier versions, including the spelling an unnormalised non-ASCII path had before, are still recognised by the baseline, the ledger history and retired case-file decisions for the same finding.

Test suite: `pip install -e ".[dev]"` (pytest and pytest-xdist; `addopts = "-n auto"` needs the latter) and run `pytest`. It takes minutes with several cores and about fifteen on one, because most of it is the mutant suites. The counts of passed and skipped tests are not written here: a number in prose goes stale, and the CI log is the record. The skips are not bugs. Some tests need the `gitleaks` binary and some need the `cns` package, and skip themselves, with the reason, where it is absent; the tests workflow installs both, so there they run:

- `Tests/test_secrets.py`, `Tests/test_secrets_disclosure.py`, `Tests/test_secrets_mutants.py`: skip with "gitleaks is not installed". To run them, put a `gitleaks` binary (v8, from the gitleaks project releases) on `PATH`.
- `Tests/test_cns_adapter.py`, `Tests/test_cns_finding_gate.py` and `Tests/test_cns_report_check.py`: skip when `cns` cannot be imported. Install the pinned package with `pip install 'ghost-tools[cns]'` and they run. `Tests/test_cns_independence.py` needs nothing and always runs.

The static gates are `python -m ruff check .` (rules E, F, W, B) and `python -m mypy` (configuration and the few justified exceptions in `pyproject.toml`); both are hard gates in CI on Python 3.11, 3.12 and 3.13.

No test in the suite is marked expected-to-fail.

## 7. Stack Integration Topology

```text
SWIZZLE attack worlds  →  ghost_buster  →  findings
ASSAY specimens   →  known-damage corpus; `swizzle assay` scores this tool against it
Warden                →  runs ghost_buster to observe, then re-inspect after an authorized change
                          (the Drafter proposes from these findings, Burnish finishes, the Judge decides;
                          `warden tagteam PATH --stack FOLDER` seats all seven, see STACK.md)
composition-engine     →  GhostToolsAdapter (one adapter, optional)
observe-perceive       ✗ does not import
swizzle-gate CI        replays SWIZZLE cases and ASSAY specimens against this tool (no secret needed)
```

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Copyright 2026 William N. King. Prefer this README plus `CHANGELOG.md` over folklore.
