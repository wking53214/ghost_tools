"""branches.py -- unmerged branch detection: a repository-state check,
not a file-content check.

WHY THIS IS A SEPARATE MODULE, NOT A mechanical.py DETECTOR
-------------------------------------------------------------
Every detector in mechanical.py is `Callable[[List[Path]], List[Finding]]`
-- a pure function of the files handed to it. This check needs the
repository's ref graph and commit history, not parsed file content, so it
takes the project root and shells out to git, the same kind of subprocess
use mutation.py already makes (that module runs pytest in scratch copies;
this one runs read-only git plumbing against the checkout in place --
never a write, never a push, never a fetch). It is still deterministic
and produces only Status.CONFIRMED findings, so it is still "mechanical"
in every sense that matters to schema.py; it is a different module only
because its input shape is different.

WHY THIS DOES NOT CALL THE GITHUB API
----------------------------------------
The accurate way to know whether a branch's pull request was merged,
closed, or never opened is to ask GitHub. This module deliberately does
not: every check in this project other than semantic.py's LLM calls runs
with zero network calls and zero API keys, and even those are opt-in and
never wired into the default CLI path because they cost real money.
Adding a GitHub dependency here would break that property for a check
git's own plumbing can approximate well enough locally. The real cost of
that choice, stated plainly in every finding this module produces: it
cannot see pull-request state at all. A flagged branch may have an open,
rejected, or never-created pull request behind it; git's ref graph and
diff content are all this detector looked at.

THE SQUASH-MERGE PROBLEM, AND HOW THIS SOLVES IT
--------------------------------------------------------
A fast-forward or ordinary merge leaves the branch tip as an ancestor of
the base branch (`git merge-base --is-ancestor` says so directly). A
squash merge does not: GitHub rewrites the branch's N commits into ONE
new commit on the base branch, so the branch tip is never an ancestor of
anything, forever, even though every line it changed is sitting right
there on the base branch. A naive ancestor-only check flags every
squash-merged branch as unmerged forever. Measured directly against this
project's own history: four of ghost_tools' own branches, all merged via
GitHub's squash-merge button, would have been false positives under
ancestor-only detection -- confirmed by hand before this module existed.

The fix: a squash merge's one new commit has, as its diff, exactly the
union of what the branch changed since it diverged from base. So: take
the whole diff from the merge-base to the branch tip as ONE patch,
compute its patch-id (`git patch-id`, a hash of the diff's content that
is stable across the commit message, author, timestamp, and exact commit
boundaries), and check whether that patch-id matches the patch-id of any
single commit base has picked up since the same merge-base. A match
means: this exact set of changes, as one unit, already landed on base --
squashed, most likely, but the mechanism doesn't have to be named for
the branch to be safely treated as absorbed.

This does not (yet) recognize a branch merged via an ordinary,
non-fast-forward merge commit whose individual commits were themselves
rewritten (e.g. an interactive rebase onto base before a real merge
commit) -- that case needs a per-commit patch-id comparison rather than
one whole-branch patch-id, and is not implemented here. It also cannot
tell a squash-absorbed branch from one that coincidentally introduces an
identical diff without ever being merged; in practice this is the same
false-positive risk `git cherry` and every other patch-id-based tool
already accepts.

THE OTHER FALSE-POSITIVE SOURCE: A STALE LOCAL CLONE
--------------------------------------------------------
Never fetching means never learning that a branch was deleted from the
actual remote. A remote-tracking ref (`origin/some-branch`) this module
finds locally can already be gone on GitHub; until something in this
checkout runs `git fetch --prune` (or the equivalent), it reads as an
ordinary unmerged branch here. Measured directly: four branches that had
already been deleted on GitHub still showed up as findings against this
project's own checkout, because they had been fetched once, outside the
checkout's configured fetch refspec, and neither an ordinary fetch nor
`--prune` touches a ref outside that refspec. A finding from this
detector is only as current as the checkout's last fetch of that branch.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "unmerged_branch"

# Tried in order when no --branches-base is given; the first that resolves
# to a real ref wins. A remote-tracking main/master is preferred over the
# local branch of the same name, since a local checkout's own `main` may
# be behind what a CI runner or a fresh clone actually has as ground truth.
_CANDIDATE_BASES = ("origin/main", "origin/master", "main", "master")


def _run(root: Path, args: List[str], *, input_text: Optional[str] = None,  # ghost_buster: name-disagreement -- `input_text` is `diff_out` at every call site
         timeout: float = 30.0) -> Optional[str]:
    """Run a read-only git command; None on any failure (missing git, not
    a repository, a bad ref, a nonzero exit, a timeout) -- fail closed,
    the same discipline semantic.py's _run_json_check uses for its own
    external call. Never raises into a caller that didn't ask for git's
    own error handling."""
    # errors="replace": a diff or `git show` of a file that is not valid
    # UTF-8 (a Windows-1252 smart quote in a transcript dump, measured on
    # the first whole-library run) must not raise out of a read-only scan.
    # A replaced byte still yields a deterministic patch-id for the same
    # input, which is all the squash check needs.
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, input=input_text,
            capture_output=True, text=True, errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


@dataclass
class BranchScanReport:
    """What happened, independent of what was found -- the same "ran vs.
    didn't, and why" discipline semantic.py's SemanticRunReport uses, for
    the same reason: "not a git repository" and "a git repository with
    nothing unmerged" must never look the same to a caller."""

    ran: bool
    reason: str = ""
    base_branch: Optional[str] = None
    branches_scanned: int = 0


def _is_git_repo(root: Path) -> bool:
    return _run(root, ["rev-parse", "--git-dir"]) is not None


def _resolve_base_branch(root: Path, explicit: Optional[str]) -> Optional[str]:  # ghost_buster: name-disagreement -- `explicit` is `base_branch` at every call site
    candidates = (explicit,) if explicit else _CANDIDATE_BASES
    for candidate in candidates:
        if candidate and _run(root, ["rev-parse", "--verify", "--quiet", candidate]) is not None:
            return candidate
    return None


def _short_name(ref: str) -> str:
    """The name a base and a same-named local/remote branch share, e.g.
    "main" for both "main" and "origin/main" -- so a base of one form
    correctly excludes the other form of itself from the scan."""
    return ref.split("/", 1)[1] if ref.startswith("origin/") else ref


def _list_branches(root: Path, base: str) -> List[str]:
    """Local heads, then origin's remote-tracking branches, excluding the
    base branch (in either form), excluded refs, and anything -- local or
    remote -- pointing at the same commit as one already listed (a local
    branch and its own remote-tracking counterpart are one branch, not
    two; local is listed first so it wins as the more actionable name)."""
    base_name = _short_name(base)
    seen_shas: Set[str] = set()
    names: List[str] = []
    # Full refnames, shortened here, not by git: `%(refname:short)` renders
    # refs/remotes/origin/HEAD as the bare word "origin", which slipped past
    # an endswith("/HEAD") filter and was counted as a branch on every
    # clone-shaped checkout (measured: 37 of 37 repos on the first
    # whole-library run reported one phantom branch each).
    for ref_root, prefix in (("refs/heads/", ""), ("refs/remotes/origin/", "origin/")):
        out = _run(root, ["for-each-ref", "--format=%(refname) %(objectname)", ref_root.rstrip("/")])
        if out is None:
            continue
        for line in out.splitlines():
            if not line.strip():
                continue
            refname, _, sha = line.rpartition(" ")
            if not refname.startswith(ref_root) or not sha:
                continue
            name = prefix + refname[len(ref_root):]
            if name == "origin/HEAD" or _short_name(name) == base_name:
                continue
            if sha in seen_shas:
                continue
            seen_shas.add(sha)
            names.append(name)
    return names


def _is_ancestor(root: Path, branch: str, base: str) -> bool:
    """Cheap fast path, not a correctness requirement: an ancestor branch's
    merge-base with base is its own tip, so _is_squash_absorbed's empty-diff
    case (see below) would also recognize it as absorbed on its own, at the
    cost of one extra `git diff` + `git patch-id` per branch. Removing this
    check cannot produce a wrong finding, only a slower correct one -- so
    it's deliberately not something the hand-mutant suite treats as
    load-bearing."""
    # Exit 0 = ancestor, exit 1 = not, per git's own documented contract
    # for this plumbing command; either way there is nothing to parse.
    return _run(root, ["merge-base", "--is-ancestor", branch, base]) is not None


def _patch_id(root: Path, diff_args: List[str]) -> Optional[str]:
    """The first token of `git patch-id --stable`'s output for the diff or
    show given by `diff_args`; None if the diff is empty, unreadable, or
    the plumbing fails."""
    diff_out = _run(root, diff_args)
    if not diff_out:
        return None
    piped = _run(root, ["patch-id", "--stable"], input_text=diff_out, timeout=15.0)  # ghost_buster: name-disagreement -- `diff_out` is `input_text` in the signature
    if not piped or not piped.strip():
        return None
    return piped.split()[0]


def _is_squash_absorbed(root: Path, branch: str, base: str) -> bool:
    """True if the whole diff from branch's merge-base with base to the
    branch tip matches, as one patch, some single commit base has picked
    up since that same merge-base -- see the module docstring."""
    merge_base = _run(root, ["merge-base", base, branch])
    if merge_base is None:
        return False
    merge_base = merge_base.strip()
    branch_patch = _patch_id(root, ["diff", merge_base, branch])
    if branch_patch is None:
        # Nothing to compare: branch introduces no diff at all relative to
        # its own merge-base, so there is nothing for it to be missing.
        return True
    base_commits = _run(root, ["log", "--format=%H", f"{merge_base}..{base}"])
    if not base_commits:
        return False
    for commit in base_commits.split():
        if _patch_id(root, ["show", commit]) == branch_patch:
            return True
    return False


def _ref_path(root: Path, name: str) -> str:
    """A synthetic but meaningful location for the finding to point at --
    real even when refs are packed (the common case), since _portable_path
    only needs a .git ancestor to exist, not this exact file."""
    if name.startswith("origin/"):
        return str(root / ".git" / "refs" / "remotes" / name)
    return str(root / ".git" / "refs" / "heads" / name)


def _describe_last_commit(root: Path, branch: str) -> Tuple[str, str, str]:
    """(short_sha, author, age-and-date-or-'date unknown') for branch's tip."""
    line = _run(root, ["log", "-1", "--format=%H|%an|%at", branch])
    if not line:
        return "?", "unknown", "date unknown"
    sha, _, rest = line.strip().partition("|")
    author, _, ts = rest.partition("|")
    age = "date unknown"
    if ts.strip().isdigit():
        commit_dt = datetime.fromtimestamp(int(ts.strip()), tz=timezone.utc)
        age_days = (datetime.now(timezone.utc) - commit_dt).days
        age = f"{age_days} day(s) ago ({commit_dt.date().isoformat()})"
    return sha[:12], author or "unknown", age


def _build_finding(root: Path, branch: str, base: str) -> Finding:
    sha, author, age = _describe_last_commit(root, branch)
    diffstat = (_run(root, ["diff", "--shortstat", base, branch]) or "").strip()
    detail = (
        f"Last commit {sha} by {author}, {age}."
        + (f" {diffstat}." if diffstat else "")
        + " This check has no visibility into GitHub pull-request state: the "
        "branch may have an open, rejected, or never-created pull request -- "
        "git's ref graph and diff content are all this detector looked at."
    )
    return Finding(
        detector=DETECTOR,
        category=Category.UNMERGED_BRANCH,
        layer=Layer.MECHANICAL,
        severity=Severity.MAJOR,
        status=Status.CONFIRMED,
        summary=f"branch '{branch}' has commits not reflected in '{base}'",
        detail=detail,
        evidence=Evidence(
            file=_ref_path(root, branch),
            related_files=[_ref_path(root, base)],
        ),
    )


def scan(root: Path, base_branch: Optional[str] = None) -> Tuple[List[Finding], BranchScanReport]:
    """Find every local or remote-tracking branch whose content is not
    reflected in the base branch, by any of: being an outright ancestor
    (fast-forward or an ordinary merge), or having a whole-branch diff
    that matches some single commit base picked up since they diverged
    (a squash merge, or the equivalent). Read-only: never fetches, never
    pushes, never writes a ref. Scans exactly what the checkout already
    has locally -- the same expectation any local git tool has.
    """
    if not _is_git_repo(root):
        return [], BranchScanReport(
            ran=False, reason=f"{root} is not a git repository (or git is not on PATH)",
        )

    base = _resolve_base_branch(root, base_branch)  # ghost_buster: name-disagreement -- `base_branch` is `explicit` in the signature
    if base is None:
        tried = base_branch or ", ".join(_CANDIDATE_BASES)
        return [], BranchScanReport(
            ran=False,
            reason=f"no base branch found (tried: {tried}); pass --branches-base explicitly",
        )

    names = _list_branches(root, base)
    findings: List[Finding] = []
    for name in names:
        if _is_ancestor(root, name, base):
            continue
        if _is_squash_absorbed(root, name, base):
            continue
        findings.append(_build_finding(root, name, base))
    return findings, BranchScanReport(ran=True, base_branch=base, branches_scanned=len(names))
