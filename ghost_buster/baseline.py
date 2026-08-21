"""baseline.py -- turns ghost_buster from a one-shot report into
something you re-run and get a DELTA from, not the same 200 pre-existing
findings every time.

A baseline is just a FindingSet, saved to disk, keyed by each finding's
stable content-hash ID (see schema.py's _stable_id -- this is exactly
why that ID had to be content-derived rather than a run-order counter:
a baseline comparison is meaningless if the same real finding gets a
different ID on every run).

WHAT "ACCEPT INTO BASELINE" MEANS, AND DOES NOT MEAN
---------------------------------------------------------
Accepting a finding into the baseline marks it SUPPRESSED -- it stops
showing up as new/notable on future runs. It does NOT mean the finding
was reviewed and found to be correct (that's Status.CONFIRMED_BY_REVIEW,
a human disposition, separate from baseline membership). A baseline is
a noise-control mechanism ("we know about this, stop repeating it"), not
a verification record. Conflating the two would let "we're tired of
seeing this" quietly become "this was checked and is fine," which is
exactly the kind of silent scope-creep this whole project is designed
to resist.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Set, Tuple

from .schema import Finding, FindingSet, Status


class Baseline:
    def __init__(self, path: Path):
        self.path = path
        self._known_ids: Set[str] = set()
        if path.exists():
            fs = FindingSet.from_json(path.read_text(encoding="utf-8"))
            self._known_ids = {f.id for f in fs}

    def accept(self, findings: List[Finding]) -> None:
        """Add these findings' IDs to the baseline and persist it."""
        existing = FindingSet.from_json(self.path.read_text(encoding="utf-8")) \
            if self.path.exists() else FindingSet()
        existing_ids = {f.id for f in existing}
        for f in findings:
            if f.id not in existing_ids:
                f.status = Status.SUPPRESSED
                existing.add(f)
                existing_ids.add(f.id)
        self.path.write_text(existing.to_json(), encoding="utf-8")
        self._known_ids = existing_ids

    def diff(self, current: List[Finding]) -> Tuple[List[Finding], List[Finding]]:
        """Split `current` into (new, already_known). `new` is what a
        report should actually surface; `already_known` still exists but
        was already accepted into the baseline on a prior run."""
        new: List[Finding] = []
        known: List[Finding] = []
        for f in current:
            (known if f.id in self._known_ids else new).append(f)
        return new, known
