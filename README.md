# ghost_tools

Codebase **integrity toolkit**: things that are present and wrong, documentation drift, duplication, dead/vacuous tests, secrets, structural ghosts. Version per README title / CHANGELOG (v1.5.x lineage). Assurance loop: **this scanner ← [`SWIZZLE`](https://github.com/wking53214/SWIZZLE) + [`ASSAY`](https://github.com/wking53214/ASSAY) specimens**.

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
```

Seven rules (each from a real defect): silence is the defect; fail-closed; say what was established (`CONFIRMED` vs `REASONED`); measured before built (`ghost_buster/calibration.json`); memory only adds (ledger never suppresses); tree unmodified except declared comment surgery; a human decides.

Defaults, all 24 detectors and the mutant census: [docs/REFERENCE.md](docs/REFERENCE.md), checked by the test suite.

~185 Python files, ~1926 functions, ~86 TODOs. Stdlib-oriented CLI. Kernel scan measures duplication/drift against private `CNS` schema when present.

## 2b. Optional CNS adapter

`ghost_buster.cns_adapter` maps `Status` → `cns.gate` outcomes when the private
`CNS` package is installed. It is **optional**: ghost_tools imports and runs
without CNS. When CNS is absent the adapter returns an advisory translation
(`authority=advisory_only`) with no `subject_digest`. When CNS is present,
`subject_digest` comes only from `cns.gate.subject_digest`. CNS is never
modified by this package.

## 3. What It Does NOT Do / Non-Goals

- Does not govern runtime decisions.
- Writes nothing into the code it scans. Ghost reports; changing a tree is the job of Warden (the governor), proposing fixes is Drafter's, and the final tidy and README are Burnish's. The old repair mode, the name annotator and the doc-correction drafter were removed so no two repositories do the same job.
- Model claims stay `REASONED` and never self-promote.

## 4. Brutally Honest Current Status & Gaps

Crowded category (ruff, mutmut, Sonar). Differentiation is fail-closed silence reporting + SWIZZLE adversarial loop. Calibration records with no corpus must say so. 86 TODOs. CNS-aware scan needs private CNS. Commercial audit used this tool on the portfolio and found real vacuous tests — that is the existence proof, not a market.

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

- **Git.** Every git command goes through `ghost_buster/gitsafe.py`. The target's `.git/config` can name programs (`diff.external`, `core.fsmonitor`, hooks, textconv drivers, `ext::` transports), so every call overrides those (`-c diff.external= -c core.fsmonitor=false -c core.hooksPath=/dev/null -c protocol.ext.allow=never` and more), passes `--no-ext-diff --no-textconv` to diff, show and log, ignores the system git config, never opens a pager or prompt, and sets `GIT_OPTIONAL_LOCKS=0` so git does not refresh `.git/index`. The same environment is given to gitleaks, which also gets `--log-opts="--no-ext-diff --no-textconv"`. Your own `~/.gitconfig` is still read.
- **Size and poison files.** A file over `--max-file-size` (default 5 MB; `$GHOST_MAX_FILE_BYTES` also works; `5M`, `512K` accepted) is never read: it is listed under `scan.unparsable` and the status is `incomplete`. A file that makes the parser run out of recursion or memory is listed the same way and the scan carries on.
- **Skipped directories** (`build`, `dist`, `node_modules`, `venv`, `.tox`, caches, VCS directories, anything given to `--exclude`) are named on stderr and in `scan.skipped_dirs`, with counts. Symlinked directories are never followed; see `scan.symlinked_dirs`.
- **Writes.** With `--no-tests`, a scan writes nothing into the folder (the ledger is opt-in, see below). With tests on (the default) and consent recorded, the target's own test suite runs. Ghost blocks pytest-benchmark (`-p no:benchmark`, which is what created `.benchmarks/`), turns off the pytest cache and bytecode files, points hypothesis and coverage state at a temporary directory, and stops git from refreshing `.git/index`. What the target's tests write on purpose, Ghost cannot prevent: it is the target's code, run because you consented.
- **Trust limit.** Consent is recorded against the `origin` remote URL, and that URL is read from the target's own `.git/config`. Anyone who can write that file can make a different checkout claim the URL of a repository you trust, and the next test or mutation run executes their code. Ghost does not close this, because a fresh clone of your own repository not asking again is the point of the design (see `ghost_buster/trust.py`). If you scan folders you did not make, use `--no-tests`, which executes nothing whatever the consent record says.

### Ledger and finding ids

The ledger is opt-in: a default scan writes nothing into the folder it scans. Use `--ledger` to keep history in `<path>/.ghost_ledger.json`, or `--ledger-path FILE` (which also turns it on) to keep it anywhere else. `--no-ledger` still works.

A finding's id hashes the detector, the file's path relative to the scanned folder (posix slashes) and the summary, so the way the folder was typed (`./x`, `x/`, absolute, a symlink, another working directory) does not change it. The path is hashed in Unicode NFC form, so a file name written composed (Linux, git) or decomposed (macOS) has one id; the report still shows the name the filesystem gave. Ids from earlier versions, including the spelling an unnormalised non-ASCII path had before, are still recognised by the baseline, the ledger history and retired case-file decisions for the same finding.

Test suite at the time of writing: 1849 passed, 39 skipped.

## 7. Stack Integration Topology

```text
SWIZZLE attack worlds  →  ghost_buster  →  findings
ASSAY specimens   →  known-damage corpus; `swizzle assay` scores this tool against it
Warden                →  runs ghost_buster to observe, then re-inspect after an authorized change
composition-engine     →  GhostToolsAdapter (one adapter, optional)
observe-perceive       ✗ does not import
swizzle-gate CI        replays SWIZZLE cases and ASSAY specimens against this tool (no secret needed)
```

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Copyright 2026 William N. King. Prefer this README plus `CHANGELOG.md` over folklore.
