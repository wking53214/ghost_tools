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

# Directories holding code kept as a FIXTURE rather than run. `specimens/`
# is TOUCHSTONE's; the rest are the names the same idea usually takes.
SPECIMEN_DIRS = frozenset({"specimens", "fixtures", "testdata", "corpus"})

# Phrases a repository uses, in its own README, to say it is a corpus and
# not a system. Matched only in the opening lines, because a sentence about
# specimens halfway down a long README is discussing them, not declaring.
# "not a system" is deliberately NOT here. It is a disclaimer both
# categories use: GSA-Master-Kernel says "This is not a system. It is a
# preserved design conversation", which is an archive, and matching on it
# labelled that repository a specimen corpus. A phrase shared by two kinds
# cannot distinguish them; only the specimen-specific ones do, and the
# share test below still catches an archive that says nothing.
_SPECIMEN_PHRASES = (
    "specimen corpus", "specimen library", "test corpus", "fixture corpus",
)

# ... and to say it is finished. `(archived)` in a title, or a retirement
# line naming a successor.
_RETIRED_PHRASES = ("(archived)", "(retired)", "archived.", "retired ")
# The successor is often on the LINE AFTER the phrase that introduces it --
# VANGUARD's "folded into" ends its line and "[GSA-GATEWAY](...)" begins the
# next -- so this crosses a line break, within a short bounded window.
_FORWARDING = re.compile(
    r"(?:folded into|moved to|superseded by|now lives (?:in|at)|"
    r"canonical home for this content)[\s\S]{0,40}?\[?([A-Za-z0-9_.-]{3,})\]?",
    re.I)
README_LINES = 12

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
    # Code that is broken ON PURPOSE, kept so tools can be tested against
    # it. Its damaged files are the point of the repository, not a loss in
    # it, and outlining them as absences reports the fixtures as failures.
    SPECIMEN_CORPUS = "specimen_corpus"
    # A repository that says it is finished and names where its content
    # went. What looks lost here is somewhere else, usually somewhere the
    # scan was never pointed at.
    RETIRED = "retired"


@dataclass(frozen=True)
class RootClassification:
    kind: RootKind
    reason: str
    archived_files: int
    total_files: int
    # Where a retired repository says its content went, when it says.
    forwarding: str = ""

    @property
    def is_archive(self) -> bool:
        """True for every kind whose damaged files are not losses."""
        return self.kind in (RootKind.CODE_ARCHIVE, RootKind.SPECIMEN_CORPUS,
                             RootKind.RETIRED)


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


def _readme_head(root: Path) -> str:
    """The opening lines of the README, where a repository declares itself.

    Bounded deliberately. A README that mentions specimens in paragraph
    nine is discussing them; one that says so in its first two lines is
    telling you what the repository IS.
    """
    for name in ("README.md", "README.rst", "README.txt", "README"):
        path = root / name
        if path.is_file():
            return "\n".join(path.read_text(errors="replace").splitlines()[:README_LINES])
    return ""


def _specimen_share(sources: Sequence[Path], root: Path) -> float:
    if not sources:
        return 0.0
    under = sum(1 for p in sources
                if SPECIMEN_DIRS & {q.lower() for q in p.relative_to(root).parts[:-1]})
    return under / len(sources)


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

    # A repository that states what it is gets believed, when it states it
    # where a declaration belongs. Measured 2026-09-10: TOUCHSTONE opens
    # "A specimen corpus. Not a system." and VANGUARD opens
    # "# VANGUARD (archived) ... folded into GSA-GATEWAY", and the six
    # highest-confidence voids in the whole library came from those two.
    head = _readme_head(root)
    if head:
        lowered = head.lower()
        if any(phrase in lowered for phrase in _SPECIMEN_PHRASES):
            return RootClassification(
                RootKind.SPECIMEN_CORPUS,
                "its README declares a specimen corpus rather than a system, so "
                "its damaged files are fixtures",
                len(archived), total)
        if any(phrase in lowered for phrase in _RETIRED_PHRASES):
            match = _FORWARDING.search(head)
            target = match.group(1) if match else ""
            reason = "its README declares the repository retired"
            if target:
                reason += f"; its content moved to {target}"
            return RootClassification(RootKind.RETIRED, reason,
                                      len(archived), total, forwarding=target)

    # Python living under a fixture directory says the same thing without
    # a README, and is checked second so an explicit statement wins.
    if total and _specimen_share(sources, root) >= ARCHIVE_SHARE:
        return RootClassification(
            RootKind.SPECIMEN_CORPUS,
            "its Python lives under fixture directories rather than an "
            "importable source tree",
            len(archived), total)

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
