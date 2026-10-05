"""Source history: telling a state nobody wired up from a state something stopped producing.

WHY THIS MODULE EXISTS
======================

`unreachable_declared_state` can see that an enum member is not produced.
From a single snapshot it cannot tell the difference between:

  * a member nobody ever wired up, and
  * a member something used to produce, until a change removed the
    production and left the declaration standing.

Those are identical in the AST and very different in meaning. The first is
an oversight. The second is a regression wearing an oversight's clothes,
and the declaration left behind is a claim the code no longer backs.

The sharpest case is RELOCATION. When the last production of a member moves
out of library code and into a test, the state did not become more
reachable. The evidence that it is unreachable became quieter. That is the
shape of silencing a detector rather than repairing what it found, and
naming it is the whole reason this module exists.

Note the inversion this produces. "Only a test produces it" read as a
snapshot is weak evidence of anything. Read against history -- a test
produces it *now* and library code produced it *before* -- it is the
strongest signal here. The same observation, with and without a clock.

WHAT IT REFUSES TO DO
=====================

It never guesses. Git can be missing, the checkout shallow, the file
untracked, the command can fail, the search can exceed its budget. Every
one of those returns UNKNOWN.

A caller that collapsed UNKNOWN into NEVER_PRODUCED would be inventing
history it could not read, which is the exact failure this tool exists to
find in other people's code. Callers are expected to report the finding at
its unescalated weight and say the history was not legible. Not knowing,
said out loud, is the honest answer.

WHAT IT DOES NOT KNOW ABOUT
===========================

Nothing here imports a detector or knows what a Finding is. It is handed a
function that turns source text into two sets of produced member names and
it calls that function at historical revisions. The analysis it performs at
a past commit is therefore the same analysis the caller performs at HEAD,
which is the only way the comparison means anything.
"""

from __future__ import annotations

import subprocess
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

__all__ = ["Provenance", "repo_root", "provenance", "Analyse"]


# The analysis the caller performs at HEAD, handed in so it can be performed
# at a past revision too. Maps {path: source} to (produced_in_library,
# produced_in_tests). Injected rather than imported: this module must not
# depend on the detector that uses it, and a caller can substitute a stub.
Analyse = Callable[[Dict[str, str]], Tuple[Set[str], Set[str]]]

# How many string-changing commits to examine before giving up. A member
# whose spelling churned through more commits than this is not worth an
# unbounded walk, and the answer past the budget is UNKNOWN, never a guess.
BUDGET = 20

_TIMEOUT = 30


class Provenance(str, Enum):
    """How a declared-but-unproduced member came to be unproduced."""

    #: No commit reachable from HEAD ever contained a production of it.
    #: Nobody wired it up. An oversight, or a vocabulary written ahead of
    #: the behaviour.
    NEVER_PRODUCED = "never_produced"

    #: Library code produced it, and a commit removed that production while
    #: leaving the declaration standing.
    REMOVED_FROM_LIBRARY = "removed_from_library"

    #: The production moved from library code into test code in the same
    #: commit. The state became no more reachable and the evidence of its
    #: unreachability became harder to see.
    RELOCATED_TO_TESTS = "relocated_to_tests"

    #: The history could not be read. NOT a synonym for NEVER_PRODUCED, and
    #: a caller that treats it as one is asserting something it did not
    #: check.
    UNKNOWN = "unknown"


def _git(root: Path, *args: str) -> Optional[str]:
    """stdout, or None for every kind of failure there is.

    Deliberately total. A missing git, a non-zero exit, a timeout and a
    decoding failure all mean the same thing to a caller: this question did
    not get answered. Distinguishing them would invite a caller to treat
    some of them as answers.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return out.stdout.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - decode with errors= does not raise
        return None


def repo_root(paths) -> Optional[Path]:
    """The work tree containing `paths`, or None if there isn't one.

    Asks git rather than looking for a `.git` directory, so a work tree, a
    submodule and a `.git` file all answer correctly. Returns None outside a
    repository, which is the common case in a temporary directory and is not
    an error.
    """
    for path in paths:
        start = Path(path)
        start = start if start.is_dir() else start.parent
        if not start.exists():
            continue
        out = _git(start, "rev-parse", "--show-toplevel")
        if out and out.strip():
            return Path(out.strip())
    return None


def _files_containing(root: Path, rev: str, needle: str) -> Optional[List[str]]:
    """Python files at `rev` containing `needle`, or None if unreadable.

    This is the optimisation that makes walking history affordable, and it
    is exact rather than approximate: a production is an attribute access
    spelled `Enum.MEMBER`, so a file not containing that text cannot contain
    a production of it. Files that do contain it still get parsed, because
    the text alone does not distinguish a production from a comparison.
    """
    out = _git(root, "grep", "-l", "--fixed-strings", needle, rev, "--", "*.py")
    if out is None:
        # git grep exits 1 when nothing matches, which _git cannot tell from
        # a real failure. Ask whether the revision exists at all: if it does,
        # the non-zero exit was "no matches" and the honest answer is none.
        if _git(root, "rev-parse", "--verify", "--quiet", rev + "^{commit}"):
            return []
        return None
    names = []
    for line in out.splitlines():
        # git grep prints "<rev>:<path>" when searching a revision.
        prefix = rev + ":"
        names.append(line[len(prefix):] if line.startswith(prefix) else line)
    return [n for n in names if n]


def _sources_at(root: Path, rev: str, needle: str) -> Optional[Dict[str, str]]:
    names = _files_containing(root, rev, needle)
    if names is None:
        return None
    sources: Dict[str, str] = {}
    for name in names:
        text = _git(root, "show", f"{rev}:{name}")
        if text is not None:
            sources[name] = text
    return sources


def _produced_at(root: Path, rev: str, needle: str,
                 analyse: Analyse) -> Optional[Tuple[Set[str], Set[str]]]:
    """(library, tests) member names produced at `rev`, or None if unreadable.

    An empty revision -- the parent of a root commit, spelled as an empty
    string by the caller -- produces nothing, which is true and is not the
    same as unreadable.
    """
    if rev == "":
        return set(), set()
    sources = _sources_at(root, rev, needle)
    if sources is None:
        return None
    return analyse(sources)


def _parent(root: Path, commit: str) -> str:
    """The first parent, or "" for a root commit."""
    out = _git(root, "rev-parse", "--verify", "--quiet", commit + "^")
    return out.strip() if out and out.strip() else ""


def provenance(root: Path, enum: str, member: str, *,
               analyse: Analyse, budget: int = BUDGET) -> Provenance:
    """Why `enum.member` is not produced in library code today.

    Walks only the commits where the text `enum.member` changed count --
    git's pickaxe -- because the transition being looked for must be one of
    them. At each, the caller's own analysis runs on the handful of files
    that mention it, so "produced" means at this commit exactly what it
    means at HEAD.

    The caller is responsible for having established that the member is not
    produced in library code NOW. This function explains that fact; it does
    not re-check it.
    """
    needle = f"{enum}.{member}"
    log = _git(root, "log", "--format=%H", "--no-merges",
               "-S", needle, "--", "*.py")
    if log is None:
        return Provenance.UNKNOWN
    commits = [line.strip() for line in log.splitlines() if line.strip()]
    if not commits:
        # git answered, and the answer is that this text never entered a
        # Python file. Nothing ever produced it.
        return Provenance.NEVER_PRODUCED

    for commit in commits[:budget]:
        after = _produced_at(root, commit, needle, analyse)
        before = _produced_at(root, _parent(root, commit), needle, analyse)
        if after is None or before is None:
            return Provenance.UNKNOWN
        lib_after, test_after = after
        lib_before, test_before = before
        if member in lib_before and member not in lib_after:
            if member not in test_before and member in test_after:
                return Provenance.RELOCATED_TO_TESTS
            return Provenance.REMOVED_FROM_LIBRARY
        if member in lib_after:
            # Produced in library at this commit and not at HEAD. The removal
            # is real even though this commit is not where it happened -- a
            # file rename or deletion can move a production without changing
            # the text's count in the way the pickaxe reports.
            return Provenance.REMOVED_FROM_LIBRARY

    if len(commits) > budget:
        # Ran out of budget with the question still open. Saying
        # NEVER_PRODUCED here would be reporting the end of the search as
        # the end of the history.
        return Provenance.UNKNOWN
    return Provenance.NEVER_PRODUCED
