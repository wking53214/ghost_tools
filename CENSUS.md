# CENSUS.md

Census run: 2026-10-21 (first run). Read-only, from `ghost_tools` `stack-census`.
Population: 34 local folders: 33 public repos under `wking53214` plus the local `WATCHER` folder.
`list_repos` lists 40 public repos. Seven were not cloned (access denied): fortress-kernel, sentinel_os, CNS, DGK, Triad-42, GEMS, Link.
The report's "47 public repos" figure does not match the 40 public repos listed today.

Hints are starting points, not tiers. Tier and decision columns are blank on purpose.

## Facts

```
REPO                      LAST        30D  TOTAL  BRANCH                               LIC  CI   README     PINNED-BY  HINT
ASSAY                     2026-10-21  28   42     claude/artifact-session-9pzzdz       yes  yes  no-status  1          LIBRARY or higher
BURNISH                   2026-10-21  73   73     claude/artifact-session-9pzzdz       yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
CCC                       2026-10-21  40   62     main                                 yes  yes  no-status  1          LIBRARY or higher
CCCb                      2026-10-21  12   12     main                                 yes  yes  no-status  2          LIBRARY or higher
Conservation_Kernel       2026-10-21  11   31     main                                 yes  yes  no-status  1          LIBRARY or higher
constitution              2026-10-07  1    1      main                                 no   no   none       0          LAB or PRODUCT (not pinned; your call)
DIT                       2026-10-21  15   19     main                                 yes  yes  no-status  1          LIBRARY or higher
DRAFTER                   2026-10-21  56   56     claude/artifact-session-9pzzdz       yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
Ecology                   2026-10-21  11   46     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
experimental              2026-10-21  178  178    main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
ghost_tools               2026-10-21  79   79     claude/artifact-session-9pzzdz       yes  yes  no-status  2          LIBRARY or higher
Governance_Gateway        2026-10-21  11   27     main                                 yes  yes  no-status  1          LIBRARY or higher
Graveyard                 2026-10-10  76   76     main                                 yes  no   no-status  0          GRAVEYARD (the record, not counted)
GSA                       2026-10-21  14   23     main                                 yes  yes  status     0          LAB or PRODUCT (not pinned; your call)
GSA-815                   2026-10-21  23   70     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
HERALD                    2026-10-21  14   50     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
interconnected_alpha      2026-10-21  13   13     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
interconnected_beta       2026-10-21  12   12     main                                 yes  yes  no-status  2          LIBRARY or higher
interconnected_delta      2026-10-21  12   12     main                                 yes  yes  no-status  1          LIBRARY or higher
interconnected_zeta       2026-10-21  13   13     main                                 yes  yes  no-status  4          LIBRARY or higher
JUDGE                     2026-10-21  59   59     claude/artifact-session-9pzzdz       yes  yes  no-status  1          LIBRARY or higher
OBSERVE                   2026-10-21  11   206    main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
observe-perceive          2026-10-21  30   78     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
p3-2-governance-research  2026-10-15  19   19     main                                 yes  no   status     0          LAB or PRODUCT (not pinned; your call)
PERCEIVE                  2026-10-21  11   17     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
Reporting                 2026-10-08  11   11     claude/lean-technical-review-9n6xwk  yes  no   no-status  0          LAB or PRODUCT (not pinned; your call)
STACK-Kernel              2026-10-20  114  114    main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
SWIZZLE                   2026-10-21  80   110    claude/artifact-session-9pzzdz       yes  yes  no-status  1          LIBRARY or higher
TIE                       2026-10-21  11   23     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
URE                       2026-10-21  11   24     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
WARDEN                    2026-10-21  111  111    claude/artifact-session-9pzzdz       yes  yes  no-status  3          LIBRARY or higher
WATCHER                   ?           ?    ?      claude/artifact-session-9pzzdz       no   no   none       0          LAB or PRODUCT (not pinned; your call)
WATCHER_MCU               2026-10-21  29   29     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)
ZTS                       2026-10-21  47   51     main                                 yes  yes  no-status  0          LAB or PRODUCT (not pinned; your call)

```

## Flags

```
FLAGS (35)
  ASSAY: checked-out branch is claude/artifact-session-9pzzdz
  ASSAY: never pinned by a tag (pinned by none)
  ASSAY: pinned by at least one repo with no version
  BURNISH: checked-out branch is claude/artifact-session-9pzzdz
  CCC: pinned at 2 different versions: 14a7638, 4aa1826
  CCC: never pinned by a tag (pinned by commit)
  CCCb: never pinned by a tag (pinned by commit)
  Conservation_Kernel: pinned at 2 different versions: 25145aa, 97ed6f4
  Conservation_Kernel: never pinned by a tag (pinned by commit)
  constitution: no license file
  DIT: never pinned by a tag (pinned by commit)
  DRAFTER: checked-out branch is claude/artifact-session-9pzzdz
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
  WARDEN: checked-out branch is claude/artifact-session-9pzzdz
  WARDEN: never pinned by a tag (pinned by commit)
  WATCHER: checked-out branch is claude/artifact-session-9pzzdz
  WATCHER: no license file

```

## Pinned but not cloned here

```
  AUGUR <- observe-perceive  [retired 2026-10-07]
  CNS <- ASSAY, BURNISH, CCC, CCCb, Conservation_Kernel, DIT, DRAFTER, Ecology, GSA, GSA-815, Governance_Gateway, HERALD, JUDGE, OBSERVE, PERCEIVE, SWIZZLE, TIE, URE, WARDEN, WATCHER_MCU, ZTS, experimental, ghost_tools, interconnected_alpha, interconnected_beta, interconnected_delta, interconnected_zeta, observe-perceive
  DGK <- experimental
  fortress-kernel <- observe-perceive
  GEMS <- observe-perceive
```

## Tier decisions (fill in)

| Repo | Tier (PRODUCT / LIBRARY / LAB / ARCHIVE) | Promises match tier? | Decision (PROMOTE / DEMOTE / ARCHIVE / no change because...) |
|---|---|---|---|
| ASSAY |  |  |  |
| BURNISH |  |  |  |
| CCC |  |  |  |
| CCCb |  |  |  |
| Conservation_Kernel |  |  |  |
| constitution |  |  |  |
| DIT |  |  |  |
| DRAFTER |  |  |  |
| Ecology |  |  |  |
| experimental |  |  |  |
| ghost_tools |  |  |  |
| Governance_Gateway |  |  |  |
| Graveyard |  |  |  |
| GSA |  |  |  |
| GSA-815 |  |  |  |
| HERALD |  |  |  |
| interconnected_alpha |  |  |  |
| interconnected_beta |  |  |  |
| interconnected_delta |  |  |  |
| interconnected_zeta |  |  |  |
| JUDGE |  |  |  |
| OBSERVE |  |  |  |
| observe-perceive |  |  |  |
| p3-2-governance-research |  |  |  |
| PERCEIVE |  |  |  |
| Reporting |  |  |  |
| STACK-Kernel |  |  |  |
| SWIZZLE |  |  |  |
| TIE |  |  |  |
| URE |  |  |  |
| WARDEN |  |  |  |
| WATCHER |  |  |  |
| WATCHER_MCU |  |  |  |
| ZTS |  |  |  |

## Budget line

Honest weekly build hours: ____
Priced tiers: PRODUCT x 2 hrs/wk + LIBRARY x 0.5 hr/wk = ____
Fits? ____

## Log

- 2026-10-21: First census run. Tiers not yet assigned.
