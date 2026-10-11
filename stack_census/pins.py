"""Which repo pins which other repo, read from the files that declare it.

A pin is a promise one repo makes about another: "I depend on that repo, at
this version". It is the strongest signal a census has about what a repo
means to the rest of the stack, and it is already written down in manifests.

Only declared dependencies are seen. A path hack or an import with no
manifest entry leaves no pin here, and a pin is never inferred from a name.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

MANIFEST_NAMES = frozenset({"pyproject.toml", "setup.py", "setup.cfg", "Dockerfile"})
SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "venv", ".venv", "site-packages",
    "fixtures", ".pytest_cache", ".ruff_cache", ".mypy_cache",
})
MAX_MANIFEST_BYTES = 1_000_000

COMMIT, TAG, BRANCH, NONE = "commit", "tag", "branch", "none"
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
_TAG_RE = re.compile(r"^v?\d+(\.\d+)*([.+-][0-9A-Za-z.]+)*$")
_REF_END = r"""[^\s"'#,;)\]]+"""


@dataclass(frozen=True)
class Pin:
    consumer: str
    target: str
    ref: str
    kind: str
    file: str


def classify_ref(ref: Optional[str]) -> str:
    if not ref:
        return NONE
    if _COMMIT_RE.match(ref):
        return COMMIT
    return TAG if _TAG_RE.match(ref) else BRANCH


def is_manifest(name: str, relative_dir: str) -> bool:
    if name in MANIFEST_NAMES:
        return True
    if name.startswith("requirements") and name.endswith(".txt"):
        return True
    in_workflows = relative_dir.replace(os.sep, "/").endswith(".github/workflows")
    return in_workflows and name.endswith((".yml", ".yaml"))


def _pin_pattern(owner: str) -> "re.Pattern[str]":
    return re.compile(
        rf"github\.com[/:]{re.escape(owner)}/([A-Za-z0-9][A-Za-z0-9_.-]*)(?:@({_REF_END}))?",
        re.IGNORECASE,
    )


def pins_in_text(text: str, consumer: str, file: str, owner: str) -> List[Pin]:
    found: List[Pin] = []
    for match in _pin_pattern(owner).finditer(text):
        target = match.group(1)
        target = target[:-4] if target.lower().endswith(".git") else target
        if not target or target.casefold() == consumer.casefold():
            continue
        ref = match.group(2) or ""
        found.append(Pin(consumer, target, ref, classify_ref(ref), file))
    return found


def _manifests(repo: Path) -> Iterator[Path]:
    for here, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        relative = os.path.relpath(here, repo)
        folder = Path(here)
        for name in sorted(files):
            if is_manifest(name, relative):
                yield folder / name


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def scan_repo(repo: Path, owner: str) -> List[Pin]:
    pins: List[Pin] = []
    for manifest in _manifests(repo):
        text = _read(manifest)
        relative = os.path.relpath(manifest, repo).replace(os.sep, "/")
        pins.extend(pins_in_text(text, repo.name, relative, owner))
    return sorted(set(pins), key=lambda p: (p.target.casefold(), p.ref, p.file))


def scan_all(repos: List[Path], owner: str) -> Dict[str, List[Pin]]:
    """Pins by consumer name, for every repo given."""
    return {repo.name: scan_repo(repo, owner) for repo in repos}
