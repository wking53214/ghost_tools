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
| `dynamic_lookup_possible` | `yes` when the scanned code looks names up by a computed value (`importlib.import_module(name)`, `__import__(name)`, `getattr(obj, name)`), `no` otherwise. When `yes`, "dead" may be wrong even if `framework_hook` is `no`. |
| `dynamic_lookup_count` | how many computed lookups were seen |

What counts as a reference:

- Entry points in `pyproject.toml` (scripts, gui-scripts, entry-points, poetry scripts and plugins), `setup.cfg`, and literal strings in `setup.py`. The target's module must match the file that defines the name. If the target module cannot be found in the repo, the name alone is matched and the reason says so.
- A string equal to the name as the second argument of `getattr`, `hasattr` or `setattr`, or inside a list, tuple, set or dict of strings in any scanned Python file.
- The name as a whole word in a config or data file (yaml, yml, json, toml, ini, cfg, txt, conf, env) at the repo root or inside a folder such as `config`, `settings` or `.github`. Lock files, `requirements*.txt` and files over 1 MB are skipped. README and other markdown prose never count.

Limits: `setup.py` is read with a text pattern, not run, so entry points built in code are missed. `pyproject.toml` and `setup.cfg` are read only for entry points, not for other settings. A computed lookup can be flagged but never resolved. The repo-level attributes appear when a project root (`pyproject.toml`, `setup.cfg`, `setup.py` or `.git`) is found or a computed lookup is seen. If `tomllib` is missing (Python 3.10), `pyproject.toml` is skipped and `reference_scan_notes` says so.

Test suite at the time of writing: 1817 passed, 39 skipped.

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
