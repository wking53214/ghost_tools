# CENSUS.md

Census run: 2026-10-21 (first run). Read-only, from `ghost_tools` `stack-census`.
Population: 41 local folders: 40 public repos under `wking53214` plus the local `WATCHER` folder.
Clones are shallow, deepened to 1000 commits.

## Categorization (from the pin network around CNS)

- **Foundation:** `CNS`. Pins nothing; 34 repos depend on it.
- **Middle libraries:** pinned by others and pin something else.
- **Top assemblers:** nothing pins them; they pin others.
- **Leaves:** pin only `CNS`.
- **Outside the network:** `STACK-Kernel`, `constitution`, `p3-2-governance-research`, `WATCHER`, `Graveyard`.

## Tier decisions

Tiers are proposed from the network categorization. PRODUCT picks are the owner's choice (option B). Pin cycles (WARDEN and JUDGE; interconnected_beta and interconnected_delta) are a follow-up, not decided here.

| Repo | Tier | Promises (from census) | Decision |
|---|---|---|---|
| ASSAY | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| BURNISH | LAB | license, CI, no status line | Add the one-line status line in README. |
| CCC | LIBRARY | license, CI, no status line, pins not tags | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| CCCb | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| CNS | LIBRARY | license, CI, no status line | Keep LIBRARY. Pinned by tag. |
| Conservation_Kernel | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| constitution | ARCHIVE (candidate) | no license, no CI, no status line | No license, no CI, one commit. Archive, or add a license and status line. |
| DGK | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| DIT | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| DRAFTER | LAB | license, CI, no status line | Add the one-line status line in README. |
| Ecology | LAB | license, CI, no status line | Add the one-line status line in README. |
| experimental | LAB | license, CI, no status line | Add the one-line status line in README. |
| fortress-kernel | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| GEMS | LIBRARY | license, CI, no status line, pins not tags | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| ghost_tools | LIBRARY | license, CI, no status line, pins not tags | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| Governance_Gateway | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| Graveyard | RECORD (not tiered) | license, no CI, no status line | Keep as the record of retired repos. |
| GSA | LAB | license, CI, status line | Add the one-line status line in README. |
| GSA-815 | LAB | license, CI, no status line | Add the one-line status line in README. |
| HERALD | LAB | license, CI, no status line | Add the one-line status line in README. |
| interconnected_alpha | LAB | license, CI, no status line | Add the one-line status line in README. |
| interconnected_beta | LIBRARY | license, CI, no status line, pins not tags | Keep LIBRARY. Pinned by Reporting and delta. Pin zeta by tag (currently no version). |
| interconnected_delta | LIBRARY | license, CI, no status line, pins not tags | Keep LIBRARY. No cycle with beta (checked). Pin beta and zeta by tag (currently no version). |
| interconnected_zeta | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| JUDGE | LIBRARY | license, CI, no status line, pins not tags | Keep LIBRARY. Cycle with WARDEN is being fixed elsewhere. |
| Link | LAB | license, CI, no status line | Add the one-line status line in README. |
| OBSERVE | LAB | license, CI, no status line | Add the one-line status line in README. |
| observe-perceive | PRODUCT | license, CI, no status line | PROMOTE to PRODUCT. Retired AUGUR pin is still used by the demo (requirements-demo.txt, fixture_augur.py). Drop only after you decide the demo's fate. |
| p3-2-governance-research | LAB | license, no CI, status line | Add the one-line status line in README. |
| PERCEIVE | LAB | license, CI, no status line | Add the one-line status line in README. |
| Reporting | LAB | license, no CI, no status line | Default branch is claude/lean-technical-review-9n6xwk, and it is the only branch on GitHub. Needs a main branch and a default-branch change in GitHub settings. |
| sentinel_os | PRODUCT | license, CI, no status line | PROMOTE to PRODUCT. Pin DIT by tag, not branch (V0.1.0). |
| STACK-Kernel | LAB | license, CI, no status line | Add the one-line status line in README. |
| SWIZZLE | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| TIE | LIBRARY | license, CI, no status line | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| Triad-42 | LIBRARY | license, CI, no status line, pins not tags | Keep LIBRARY. Publish a tag; consumers pin the tag. |
| URE | LAB | license, CI, no status line | Pin is already a tag (V1.9.1 exists on ghost_tools). Census tool misread it as a branch. No change needed. |
| WARDEN | LIBRARY | license, CI, no status line, pins not tags | Keep LIBRARY. Cycle with JUDGE is being fixed elsewhere. |
| WATCHER | ARCHIVE (candidate) | no license, no CI, no status line | Local clone has no commits. Confirm the remote and archive if unused. |
| WATCHER_MCU | LAB | license, CI, no status line | Add the one-line status line in README. |
| ZTS | LAB | license, CI, no status line | Add the one-line status line in README. |

## Follow-ups

- WARDEN <-> JUDGE cycle: being fixed elsewhere. No beta <-> delta cycle exists (earlier reading was wrong).
- Move commit and branch pins to tags across the network. Start with `observe-perceive` (8 pins, most by commit).
- Retired `AUGUR` pin in `observe-perceive`: decide whether to drop it and retire the demo that uses it.

## Flags

```
FLAGS (43)
  ASSAY: checked-out branch is claude/artifact-session-9pzzdz
  ASSAY: never pinned by a tag (pinned by none)
  ASSAY: pinned by at least one repo with no version
  BURNISH: checked-out branch is claude/artifact-session-9pzzdz
  CCC: pinned at 3 different versions: 14a7638, 4aa1826, 96cfc9c
  CCC: never pinned by a tag (pinned by commit)
  CCCb: never pinned by a tag (pinned by commit)
  CNS: pinned at 2 different versions: none, v1.9.0
  CNS: pinned by at least one repo with no version
  Conservation_Kernel: pinned at 3 different versions: 25145aa, 570c2c7, 97ed6f4
  Conservation_Kernel: never pinned by a tag (pinned by commit)
  constitution: no license file
  DGK: never pinned by a tag (pinned by branch)
  DIT: pinned at 2 different versions: 5763f1a, V0.1.0
  DIT: never pinned by a tag (pinned by branch, commit)
  DRAFTER: checked-out branch is claude/artifact-session-9pzzdz
  fortress-kernel: never pinned by a tag (pinned by commit)
  GEMS: never pinned by a tag (pinned by commit)
  ghost_tools: checked-out branch is claude/artifact-session-9pzzdz
  ghost_tools: pinned at 2 different versions: 5d7a386, V1.9.1
  ghost_tools: never pinned by a tag (pinned by branch, commit)
  Governance_Gateway: pinned at 2 different versions: a02f738, c507be7
  Governance_Gateway: never pinned by a tag (pinned by commit)
  interconnected_beta: pinned at 2 different versions: none, 3bb9c6f
  interconnected_beta: never pinned by a tag (pinned by commit, none)
  interconnected_beta: pinned by at least one repo with no version
  interconnected_delta: never pinned by a tag (pinned by commit)
  interconnected_zeta: pinned at 2 different versions: none, 6d62103
  interconnected_zeta: never pinned by a tag (pinned by commit, none)
  interconnected_zeta: pinned by at least one repo with no version
  JUDGE: checked-out branch is claude/artifact-session-9pzzdz
  JUDGE: never pinned by a tag (pinned by commit)
  observe-perceive: pins AUGUR, retired 2026-10-07 (pyproject.toml, requirements-demo.txt @ 1fc7611)
  Reporting: checked-out branch is claude/lean-technical-review-9n6xwk
  SWIZZLE: checked-out branch is claude/artifact-session-9pzzdz
  SWIZZLE: never pinned by a tag (pinned by none)
  SWIZZLE: pinned by at least one repo with no version
  TIE: never pinned by a tag (pinned by commit)
  Triad-42: never pinned by a tag (pinned by commit)
  WARDEN: checked-out branch is claude/artifact-session-9pzzdz
  WARDEN: never pinned by a tag (pinned by commit)
  WATCHER: checked-out branch is claude/artifact-session-9pzzdz
  WATCHER: no license file

```

## Pinned but not cloned here

```
  AUGUR <- observe-perceive  [retired 2026-10-07]
```

## Budget line

Honest weekly build hours: ____
Priced tiers: PRODUCT x 2 hrs/wk + LIBRARY x 0.5 hr/wk = ____
Fits? ____

## Log

- 2026-10-21: Corrected: no beta <-> delta cycle; URE pin is a tag; Reporting needs a main branch and a settings change.
- 2026-10-21: First census run (41 folders). Tiers assigned from the network categorization (PRODUCT: option B). Budget not yet entered.
