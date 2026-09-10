"""Proof that a scan left the tree alone, instead of a docstring saying so.

WHY THIS EXISTS

"The working tree is never modified" appears 35 times across this project's
code and documentation. Nothing verified it. A promise repeated 35 times and
checked zero times is precisely the shape of defect ghost_buster exists to
find in other people's code, and it went unexamined here for the whole life
of the project -- through the version that added `--annotate-names` and the
one that added `--recover-into`, which are the first two things in the
toolkit that write anything at all.

The idea came from a capability tracer recovered out of a chat history:
declare what a component may do, watch what it actually does, refuse the
difference. Its mechanism does not survive contact with this codebase --
it patched `builtins.open`, and every write here goes through
`Path.write_text`, which does not call it. Measured:

    Path.write_text seen by a builtins.open patch: False

So the mechanism is a content snapshot of the tree instead. It cannot be
bypassed by which API a writer happens to use, and it catches a deletion, a
chmod and a stray directory as readily as an edit.

THE INVARIANT IS NOT "NEVER WRITES"

Writing this guard immediately showed the blanket claim to be too strong. A
default scan writes `.ghost_ledger.json` into the scanned path; `--accept`
writes `.ghost_baseline.json`; and `--annotate-names` deliberately edits the
sources it was pointed at. The true and testable invariant is narrower and
more useful:

    NOTHING THAT ALREADY EXISTED IS MODIFIED OR DELETED, and the only files
    that appear are ones the caller declared it expected.

which is what `unchanged(root, may_create=...)` asserts. `--annotate-names`
is the one documented exception and gets its own assertion, that it changes
only what it claims to and only by comment.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, Sequence, Tuple

# Caches and VCS internals churn for reasons that have nothing to do with
# what a scan did. Anything outside this list counts, including a file the
# scan created and deleted again -- which would be invisible to a check that
# only compared the survivors.
IGNORE = (".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")


@dataclass(frozen=True)
class Snapshot:
    """Every path under a root, with enough of its state to notice a change.

    The entry is `mode:digest` rather than a digest alone so that a chmod is
    a change too: a scan that leaves a file's bytes alone and makes it
    world-writable has still modified the tree.
    """

    root: str
    entries: Dict[str, str]


def _entry(path: Path) -> str:
    if path.is_symlink():
        return "symlink:" + os.readlink(path)
    if path.is_dir():
        return "dir"
    try:
        mode = path.stat().st_mode & 0o777
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as e:
        return f"unreadable:{type(e).__name__}"
    return f"{mode:o}:{digest}"


def snapshot(root: Path, ignore: Sequence[str] = IGNORE) -> Snapshot:
    root = Path(root)
    entries: Dict[str, str] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = [d for d in directories if d not in ignore]
        for name in list(directories) + files:
            path = Path(current) / name
            entries[str(path.relative_to(root))] = _entry(path)
    return Snapshot(root=str(root), entries=entries)


@dataclass(frozen=True)
class Changes:
    modified: Tuple[str, ...] = ()
    deleted: Tuple[str, ...] = ()
    created: Tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.modified or self.deleted or self.created)

    def report(self) -> str:
        lines = []
        for label, paths in (("modified", self.modified), ("deleted", self.deleted),
                             ("created", self.created)):
            for path in paths:
                lines.append(f"  {label}: {path}")
        return "\n".join(lines) or "  (no change)"


def compare(before: Snapshot, after: Snapshot) -> Changes:
    modified = tuple(sorted(
        path for path, entry in before.entries.items()
        if path in after.entries and after.entries[path] != entry))
    deleted = tuple(sorted(set(before.entries) - set(after.entries)))
    created = tuple(sorted(set(after.entries) - set(before.entries)))
    return Changes(modified=modified, deleted=deleted, created=created)


def _allowed(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


@contextmanager
def unchanged(root: Path, may_create: Sequence[str] = ()) -> Iterator[Snapshot]:
    """Assert that nothing under `root` that already existed is touched.

    A modification or a deletion is always a failure. A creation is a failure
    unless it matches one of `may_create`, which is a declaration the caller
    has to make on purpose -- an output directory, a tool's own dotfile.
    Declaring it is the point: an undeclared file appearing in somebody's
    repository is exactly the surprise this guards against.
    """
    root = Path(root)
    before = snapshot(root)
    yield before
    changes = compare(before, snapshot(root))
    undeclared = tuple(p for p in changes.created if not _allowed(p, may_create))
    if changes.modified or changes.deleted or undeclared:
        raise AssertionError(
            f"the scanned tree at {root} was not left alone:\n"
            + Changes(changes.modified, changes.deleted, undeclared).report()
            + (f"\n  (declared as expected: {', '.join(may_create)})" if may_create else "")
        )
