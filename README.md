# ghost_tools

Codebase **integrity toolkit**: things that are present and wrong, documentation drift, duplication, dead/vacuous tests, secrets, structural ghosts. Version per README title / CHANGELOG (v1.5.x lineage). Assurance loop: **this scanner ← [`SWIZZLE`](https://github.com/wking53214/SWIZZLE) + [`TOUCHSTONE`](https://github.com/wking53214/TOUCHSTONE) specimens**.

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
- Writes nothing into the code it scans. Ghost reports; changing a tree is the job of Elegant (the governor), proposing fixes is Proposer's, and the final tidy and README are Streamline's. The `--operate` surgeon, `--annotate-names` and `ghost_writer/correct.py` were removed so no two repositories do the same job.
- Model claims stay `REASONED` and never self-promote.

## 4. Brutally Honest Current Status & Gaps

Crowded category (ruff, mutmut, Sonar). Differentiation is fail-closed silence reporting + SWIZZLE adversarial loop. Calibration records with no corpus must say so. 86 TODOs. CNS-aware scan needs private CNS. Commercial audit used this tool on the portfolio and found real vacuous tests — that is the existence proof, not a market.

## 5. Core Invariants & Guarantees

Unrunnable check → finding, not a skip. Unreadable ledger fails the run. Non-git directory hard-stops secrets scan. Ledger never lowers severity. Human triage is the gate for fix/suppress/document.

## 6. Inputs, Outputs & Type Contracts

CLI over a git work tree. Findings: severity, `CONFIRMED`/`REASONED`, evidence. Calibration JSON per detector.

## 7. Stack Integration Topology

```text
SWIZZLE attack worlds  →  ghost_buster  →  findings
TOUCHSTONE specimens   →  known-damage corpus; `swizzle touchstone` scores this tool against it
Elegant                →  runs ghost_buster to observe, then re-inspect after an authorized change
composition-engine     →  GhostToolsAdapter (one adapter, optional)
observe-perceive       ✗ does not import
swizzle-gate CI        replays SWIZZLE cases and TOUCHSTONE specimens against this tool (no secret needed)
```

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Copyright 2026 William N. King. Prefer this README plus `CHANGELOG.md` over folklore.
