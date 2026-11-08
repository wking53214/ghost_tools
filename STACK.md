# Stack role: ghost_tools

**ASSURANCE (not the live decision path).**

The scanner (Ghost Buster). Finds what is present and wrong: dead code, documentation drift, duplication, vacuous tests, secrets. Reports, never writes. Its findings keep their identity across the loop, and it says what it could not look at.

## The circuit

Five repositories, one loop. Warden is the only one that writes, and nothing is
written without a named human.

| # | Part | Repository | Role |
|---|------|------------|------|
| 1 | Answer key | [ASSAY](https://github.com/wking53214/ASSAY) | Known failure modes with independently known answers; the scanner is graded against it before anything is written. |
| 2 | Scanner | [ghost_tools](https://github.com/wking53214/ghost_tools) (Ghost Buster) | Observes: finds defects; findings keep their identity across the loop; says what it could not look at. |
| 3 | Attacker | [SWIZZLE](https://github.com/wking53214/SWIZZLE) | Proves its own planted defects, scores the scanner against the answer key, attacks the governor's rules. |
| 4 | Governor | [Warden](https://github.com/wking53214/Warden) | Applies, measures, refuses and puts the tree back; the only part allowed to write; human grant, green suite before and after, durable record. |
| 5 | Judge | [Judge](https://github.com/wking53214/Judge) | Reads the evidence of the whole run and says ACCEPT, REJECT or INSUFFICIENT; Warden reports INSUFFICIENT as a hold. |

Any actor's real change enters through Warden's claim seat (`--claim-commit` or `--claim-diff`);
an optional Drafter may propose one instead. There is no finisher in the loop.

```text
CODEBASE
   │
   ▼
SWIZZLE   proves its own instrument (12 planted-defect proofs must all hold)
ASSAY     grades the scanner against the answer key (the key is proven first)
   │         nothing is written if either fails
   ▼
CLAIM SEAT  a real change from any actor (--claim-commit or --claim-diff),
            or one proposal from an optional Drafter
   │
   ▼
┌─ WARDEN applies and measures ───────────────────────────────────────────┐
│  GHOST     observe: what is wrong (ghost-* ids)                          │
│  WARDEN    human grant · suite green before · apply · suite green after  │
│  GHOST     re-inspect: nothing new, or the change is put back            │
└──────────────────────────────────────────────────────────────────────────┘
   │
   ▼
SWIZZLE   attacks the governor; every scenario must be held
   │
   ▼
JUDGE     ACCEPT (stands) · REJECT (whole tree put back) · INSUFFICIENT (reported as a hold)
```

Each seat declares `requires_contract = "1"` and reads and returns the shared rows defined in
CNS; Warden imports none of them. Warden tells a Drafter, when one is seated, the grant's scope
(`documentation` or `code`) before it asks it.

**One command runs the circuit.** With a clone of each repository in one folder (names matched
without regard to case):

```bash
warden tagteam PATH --stack FOLDER --stack-manifest stack.json --claim-commit SHA --authorize "Your Name" --reason "why" --scope code
```

A bare `--stack` still requires all six checkouts (`ghost_tools`, `swizzle`, `assay`, `judge`,
`drafter` and `burnish`). Only a pinned `--stack-manifest` that omits `drafter` and `burnish`,
with a folder that lacks them, runs without them, and the run record lists `released_seats`.
Exit 0 means `ACCEPT` and nothing else does. Every run declines eight Ghost checks (mutate, kernel, structure, tests, project, secrets, correlate,
ledger) since ghost_tools 1.10.11; a record that says seven describes a dated earlier run.

## Released from the circuit

DRAFTER, BURNISH and WATCHER_MCU are released from the circuit by owner ruling (2026-10-29). They are
not seats of the circuit Warden runs. Nothing was deleted, and each still works on its own as its
README describes. CNS holds the contracts and records the ruling in `docs/RELEASED_SEATS.md`. An
earlier recorded run (2026-10-14, every seat live on a scratch repository, `ACCEPT` under both grants;
see Warden's `docs/REGISTRY.json`) used the older circuit that seated them.

```text
Live path: Admission → OBSERVE/Keys → Locks → PERCEIVE → Decision → Conservation → Execution → Custody
Assurance: ASSAY · ghost_tools · SWIZZLE · Warden · Judge  (this circuit, off the live path)
```

CNS (public, https://github.com/wking53214/CNS) holds the interoperability contracts. No repository in the circuit modifies it.

See [README.md](README.md).
