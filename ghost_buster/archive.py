"""An archive is not a patient.

A repository that exists to hold history (a corpus, an export, a set of
specimens kept flattened on purpose) fails "parses completely" forever,
and a readiness gate that keeps saying so is a gate nobody reads. The
scan still runs: an archive's findings are still findings. What changes
is candidacy: an archive is never a candidate and never operated on, and
the report says why in the archive's own words.

    .ghost_archive          at the repository root, committed; its text is
                            the reason, shown on the receipt line

The marker is a decision, recorded where decisions live (in the tree,
reviewed like any other change), and it is visible: the receipt line
names it on every run, so an archive cannot be mistaken for a repository
nobody has looked at.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MARKER = ".ghost_archive"


@dataclass(frozen=True)
class Archive:
    path: Path
    reason: str

    def receipt(self) -> str:
        why = f": {self.reason}" if self.reason else " (no reason given in the marker)"
        return (f"ghost_buster: this repository is an archive{why}. Findings are reported; "
                f"candidacy is not assessed and the surgeon does not operate.")


def marked(root: Path) -> Optional[Archive]:
    """The archive marker if the repository carries one."""
    p = Path(root) / MARKER
    if not p.is_file():
        return None
    try:
        reason = " ".join(p.read_text(encoding="utf-8", errors="replace").split())
    except OSError:
        reason = ""
    return Archive(p, reason[:200])
