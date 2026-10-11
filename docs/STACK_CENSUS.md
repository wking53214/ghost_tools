# stack-census

A read-only census of every git repo one level down in a folder. It reports
what git, the manifests and the Graveyard already say, so the person deciding
what each repo should promise starts from facts. It assigns no tier and writes
nothing, not even `CENSUS.md`.

Run it with the folder that holds all the clones as the only required
argument. Options: `--owner` (whose repos count as yours when reading pins,
default `wking53214`), `--graveyard` (the Graveyard folder's name, default
`Graveyard`), `--date`, `--json`, and `--entry`.

## What it reads

| Source | What it gives |
|---|---|
| git, through `ghost_buster.gitsafe` | last commit date, commits in 30 days, total commits |
| `.git/HEAD` | the checked-out branch (not GitHub's default branch) |
| top of each repo | license file, CI workflow, README status line in the first five lines |
| manifests | which repo pins which other repo, at what version, and whether that is a commit, a tag, a branch or nothing |
| the Graveyard folder | which repos were wholly retired (a `full-retirement` burial) and which were only partly buried |

Manifests read: `pyproject.toml`, `requirements*.txt`, `setup.py`, `setup.cfg`,
`Dockerfile`, and `.github/workflows/*.yml`. Folders named `fixtures`,
`node_modules`, `venv`, `site-packages` and the like are skipped, and so is
the Graveyard repo itself, whose snapshots hold old manifests.

## Hints

A hint is a starting point for a human tier decision. PRODUCT is never
suggested, because it is a decision about what a repo means to promise, which
no file can show.

| Hint | When |
|---|---|
| BURIED | wholly retired in the Graveyard and the clone is a gravestone (six top-level files or fewer) |
| RETIRED, CLONE NOT A GRAVESTONE | wholly retired but the clone still holds the repo |
| LIBRARY or higher | at least one other repo pins it |
| ARCHIVE candidate | nothing pins it and the last commit is over 60 days old |
| LAB or PRODUCT (not pinned; your call) | everything else |
| GRAVEYARD | the Graveyard folder itself, not counted |

## Flags

Facts that deserve a look: a `claude/` checked-out branch, no license file, a
live pin to a wholly retired repo, a repo pinned at several different
versions, a repo never pinned by a tag, and a repo some consumer pins with no
version. Repos pinned but not cloned in the folder are listed separately, and
marked when the Graveyard says they were retired.

## What it cannot see

* Only declared dependencies. A path hack or an import with no manifest entry
  leaves no pin.
* Whether docs are true at HEAD, or whether CI is green. It only sees that a
  workflow file exists.
* GitHub-side facts (default branch, archived, private). It reads the clone.
* A git answer it could not get is `?` in the table and `null` in JSON. It is
  never counted as zero.
