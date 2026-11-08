"""What git and the files at the top of a repo already say about it.

No judgments here. A fact git cannot give (not a repository, a timeout, a
repo with no commits) is None, never zero: "no commits in 30 days" and "could
not count" are different answers and are kept different.

Every git command goes through ghost_buster.gitsafe, because a clone's own
.git/config is data written by somebody else.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ghost_buster import gitsafe

GIT_TIMEOUT_SECONDS = 30
README_NAMES = ("README.md", "readme.md", "README")
LICENSE_PREFIXES = ("license", "licence", "copying")
STATUS_PATTERN = re.compile(r"status:|^>\s*(lab|archive|product|library)", re.I | re.M)

README_NONE, README_NO_STATUS, README_STATUS = "none", "no-status", "status"


@dataclass(frozen=True)
class RepoFacts:
    name: str
    path: Path
    last_commit: Optional[str]
    commits_30d: Optional[int]
    commits_total: Optional[int]
    branch: Optional[str]
    has_license: bool
    readme: str
    has_ci: bool
    top_level_files: int


def _git(repo: Path, *args: str) -> Optional[str]:
    try:
        done = gitsafe.run(list(args), root=repo, capture_output=True, text=True,
                           timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None  # git missing, bad path, or a slow repo: unknown, not zero
    return done.stdout.strip() if done.returncode == 0 else None


def _count(repo: Path, *args: str) -> Optional[int]:
    out = _git(repo, "rev-list", "--count", *args, "HEAD")
    return int(out) if out and out.isdigit() else None


def checked_out_branch(repo: Path) -> Optional[str]:
    """The branch HEAD names, read from the file; None when detached or when
    .git is not a plain directory."""
    head = repo / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    prefix = "ref: refs/heads/"
    return text[len(prefix):] if text.startswith(prefix) else None


def readme_state(repo: Path) -> str:
    for name in README_NAMES:
        path = repo / name
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
            found = STATUS_PATTERN.search("\n".join(lines))
            return README_STATUS if found else README_NO_STATUS
    return README_NONE


def _has_ci(repo: Path) -> bool:
    workflows = repo / ".github" / "workflows"
    return workflows.is_dir() and any(workflows.glob("*.y*ml"))


def _has_license(repo: Path) -> bool:
    return any(p.is_file() and p.name.lower().startswith(LICENSE_PREFIXES)
               for p in repo.iterdir())


def gather(repo: Path) -> RepoFacts:
    entries = [p for p in repo.iterdir() if p.name != ".git"]
    return RepoFacts(
        name=repo.name,
        path=repo,
        last_commit=_git(repo, "log", "-1", "--format=%cs") or None,
        commits_30d=_count(repo, "--since=30.days.ago"),
        commits_total=_count(repo),
        branch=checked_out_branch(repo),
        has_license=_has_license(repo),
        readme=readme_state(repo),
        has_ci=_has_ci(repo),
        top_level_files=len(entries),
    )
