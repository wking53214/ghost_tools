# What `forensics.py` cannot know, and why it escalates anyway

`unreachable_declared_state` grades a declared-but-unproduced enum member
partly on git history: a state nobody ever wired up is MINOR, and a state
some commit stopped producing is MAJOR. `ghost_buster/forensics.py` walks
history with a pickaxe to tell those apart.

This document records the limit of that approach. It is not a bug list.
Every finding described here is technically correct, and the reason they
are worth writing down is that being correct is not the same as being
useful to the person reading the report.

## The shape of the problem

A member is added to an enum. Library code produces it. A later commit
stops producing it. A test still names it.

The forensics layer reads that history exactly and classifies the member
as removed from library code, which escalates the finding to MAJOR. That
classification is right about what happened. It is silent about why, and
the why is the whole question:

- **A security fix.** The member was removed because producing it was
  dangerous, and something still referencing it is a real problem.
  MAJOR is correct and urgent.
- **A deliberate refactor.** The member was removed because the design
  changed and a different member covers the case now. Nothing is wrong.
  MAJOR is correct and useless.
- **A regression.** The member should still be produced and a commit
  dropped the call by accident. MAJOR understates it, if anything: the
  finding says "removed" where the truth is "broken".

Git history is objective about the first fact and says nothing about the
second. The three cases produce byte-identical evidence.

## Why it escalates rather than abstaining

Because the tool grades on what the evidence costs to fake, and a removal
from production history costs the same to fake in all three cases. There
is no signal in the diff that separates them, so a detector that tried to
would be inventing the distinction rather than reading it.

Abstaining is worse than escalating here. The security-fix case is the one
where silence is expensive, and it is indistinguishable from the refactor
case, so declining to report would mean declining to report the one that
matters. Erring toward MAJOR puts the judgement in front of a human who
has the context the tree does not contain. That is the same rule the rest
of this toolkit follows: report the observation, never the motive.

## The honest consequence

On a codebase that refactors enums regularly, this detector will produce
MAJOR findings that a human triages as "intentional, not a defect", and it
will produce them again on the next scan, because nothing in the tree has
changed. That is what `.ghost_casefile.json` is for: a `ghost-triage`
decision recorded once shows up beside the finding on every later run, so
the second reader sees "this team called this one false" rather than
re-deriving it. The finding is not suppressed; the history is attached.

## What would actually narrow it, and what would not

Not signal, and named here so nobody spends an afternoon on them:

- **Commit-message prefixes** (`refactor:`, `fix:`, `remove:`). A
  convention, not a fact. It costs one word to write the reassuring one,
  which makes it evidence that lowers a severity and costs nothing to
  fake -- the exact thing 1.7.8 removed from this detector.
- **Absence from a changelog.** Same objection, one file further away.

Possible signal, unmeasured:

- **Whether any surviving production path can still construct the
  member.** This is already how the structural clearance works
  (`Status(row["s"])` means it really can arrive), and extending it to
  historical removals is the one direction that reads the code rather
  than somebody's description of it.

Neither is implemented. This section exists so the question stays open in
a place somebody will find it, rather than being rediscovered as a bug.

## Provenance of this document

It is the durable half of `Tests/fixtures/wizzle/FORENSICS_SCENARIOS.md`,
a corpus added in 1.7.1-1.7.8 and deleted in 1.9.1. That corpus was a
standalone repository copied into this tree as static files, and its
scenarios were defined by commits from its own history, which did not come
with it. It could not demonstrate what it described, no test referenced it,
pytest collected one of its files as a real test and errored on the import,
and the self-scan reported its unresolvable import as a MAJOR finding
against this repository. The argument above survived it; the files did not.
