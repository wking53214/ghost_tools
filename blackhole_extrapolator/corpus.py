"""Is this a system with holes in it, or a record of code someone kept?

A void report assumes its input is a codebase: something that was meant to
run, whose missing pieces are a defect. That assumption is wrong for a large
class of repositories, and wrong in a way that produces confident nonsense.

MEASURED, 2026-09-10

Across a 37-repository library the extrapolator produced 248 voids. 39% of
the evidence behind them pointed into `extracted/`, `Takeout/` and
`derived/colab_extracts/` -- directories holding code that was pasted into
a conversation, exported from a chat product, or lifted out of a notebook.
ARCHIVE alone accounted for 70 voids, 28% of the total, and its README opens:

    Eight archived "System Architecture and Integration Report" JSON
    payloads ... See PROVENANCE.md for the full source writeup and
    TRANSCRIPT.md for the original conversation.

The repository says what it is, in the first sentence, and the tool did not
read it. A truncated paste in a conversation export is not a hole in a
system. It is a faithful record of a partial thing. The finding worth making
about it is that the extraction is lossy, which is a statement about the
archive, not about a missing module somebody should rebuild.

WHAT THIS DOES NOT DO

It does not silence anything. An archive still reports every mark it
carries; the marks are classified as extraction fidelity instead of being
outlined as absences. And the classifier is deliberately hard to trip: a
source tree that merely contains a `docs/` folder full of examples is not an
archive, because the test is where the PYTHON lives, not where the prose
does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

# Directory names that mean "this code was taken out of somewhere else".
# Each was observed in the measured library; none is a name a working
# package would give a source directory it imports from.
ARCHIVE_DIRS = frozenset({
    "extracted", "takeout", "colab_extracts", "conversations",
    "chat_exports", "claude_export", "raw_exports",
})

# Files a repository writes when its job is to preserve something.
PROVENANCE_FILES = ("PROVENANCE.md", "TRANSCRIPT.md", "MANIFEST.md")

# `artifact_1.py`, `report_3.py`: a numbered dump of turn N, not a module
# anybody imports by name.
_NUMBERED_ARTIFACT = re.compile(r"^(artifact|report|turn|cell|extract)_\d+\.py$", re.I)

# Below this share of Python-under-archive-paths a tree is source, whatever
# else it holds. Two thirds, not a bare majority: a working repository that
# happens to vendor one export directory must stay a source tree.
ARCHIVE_SHARE = 2 / 3
# A provenance manifest lowers the bar but never clears it alone. The first
# version of this classifier treated PROVENANCE.md as sufficient and
# promptly called ghost_tools and GSA-815 archives -- two live codebases
# with 0 of 83 and 0 of 53 Python files under an export path, which would
# have silenced every void in them. Documenting where you came from is
# something good source repositories do. Where the Python lives is the
# load-bearing signal; the manifest only corroborates it.
ARCHIVE_SHARE_WITH_MANIFEST = 1 / 2


class RootKind(str, Enum):
    SOURCE_TREE = "source_tree"
    CODE_ARCHIVE = "code_archive"


@dataclass(frozen=True)
class RootClassification:
    kind: RootKind
    reason: str
    archived_files: int
    total_files: int

    @property
    def is_archive(self) -> bool:
        return self.kind is RootKind.CODE_ARCHIVE


def _is_archived_path(path: Path, root: Path) -> bool:
    try:
        parts = [p.lower() for p in path.relative_to(root).parts]
    except ValueError:
        return False
    if ARCHIVE_DIRS & set(parts):
        return True
    if "my activity" in parts:          # Google Takeout's own layout
        return True
    return bool(_NUMBERED_ARTIFACT.match(path.name))


def classify_root(root: Path, sources: Sequence[Path] | None = None) -> RootClassification:
    """Decide whether `root` is a codebase or a record of code.

    Two independent signals, either sufficient, because they fail in
    different circumstances: a repository that declares itself an archive in
    a provenance file, and one whose Python overwhelmingly lives under
    export-shaped paths. A repository with no Python at all is a source
    tree by default -- there is nothing to misclassify, and defaulting the
    other way would let an empty directory silence a real scan.
    """
    root = Path(root)
    if sources is None:
        from .detect import _source_files
        sources = _source_files(root)
    sources = list(sources)

    present = [name for name in PROVENANCE_FILES if (root / name).is_file()]
    archived = [p for p in sources if _is_archived_path(p, root)]
    total = len(sources)

    # No archived Python at all is a source tree no matter what it documents.
    if total and archived:
        share = len(archived) / total
        threshold = ARCHIVE_SHARE_WITH_MANIFEST if present else ARCHIVE_SHARE
        if share >= threshold:
            pct = round(100 * share)
            reason = (f"{pct}% of its Python ({len(archived)} of {total} files) sits under "
                      "export-shaped paths rather than an importable source tree")
            if present:
                reason += f", and it declares itself a record ({', '.join(present)})"
            return RootClassification(RootKind.CODE_ARCHIVE, reason, len(archived), total)

    return RootClassification(
        RootKind.SOURCE_TREE,
        "no provenance manifest, and its Python lives in an ordinary source tree",
        len(archived), total,
    )
