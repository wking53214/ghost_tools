# ghost_tools

Codebase **integrity toolkit**: things that are present and wrong, documentation drift, duplication, dead/vacuous tests, secrets, structural ghosts. Version per README title / CHANGELOG (v1.5.x lineage). Assurance loop: **this scanner ← [`SWIZZLE`](https://github.com/wking53214/SWIZZLE) + [`TOUCHSTONE`](https://github.com/wking53214/TOUCHSTONE) specimens**.

## 1. Pipeline Position & Role

**ASSURANCE**, off the live decision path. CI-shaped. Does not admit, decide, or execute governed actions. Commercial red team: **product candidate** (small ACV, fast cycle) for VP Engineering where AI-written code makes green CI meaningless.

## 2. Full System Scope & Architectural Depth

```
ghost-buster              present-and-wrong
ghost-buster --operate    surgeon: heal comments on a branch, re-examine, learn
ghost-buster --profile    repeated work
ghost-buster --mutate     tests that pass with the named thing broken
ghost-triage              human decision, recorded
ghost-writer              worth documenting
blackhole-extrapolator    ones that went up in smoke
```

Seven rules (each from a real defect): silence is the defect; fail-closed; say what was established (`CONFIRMED` vs `REASONED`); measured before built (`ghost_buster/calibration.json`); memory only adds (ledger never suppresses); tree unmodified except declared comment surgery; a human decides.

~185 Python files, ~1926 functions, ~86 TODOs. Stdlib-oriented CLI. Kernel scan measures duplication/drift against private `CNS` schema when present.

## 3. What It Does NOT Do / Non-Goals

- Does not govern runtime decisions.
- Surgeon edits **comments only**, on a branch it opened, syntax-tree identity checked. It is not an autonomous refactorer.
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
TOUCHSTONE specimens   →  known-damage corpus
composition-engine     →  GhostToolsAdapter (one adapter, optional)
observe-perceive       ✗ does not import
swizzle-gate CI        replays SWIZZLE cases against this tool
```

Proprietary. Copyright (c) 2026 William N. King. All rights reserved. See LICENSE. Prefer this README plus `CHANGELOG.md` over folklore.
