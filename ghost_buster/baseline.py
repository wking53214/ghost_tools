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

from .schema import Category, Evidence, Finding, FindingSet, Layer, Severity, Status
from .schema import authoritative

DETECTOR = "stale_baseline"


class Baseline:
    def __init__(self, path: Path):
        self.path = path
        self._known_ids: Set[str] = set()
        self._known: dict = {}
        if path.exists():
            fs = FindingSet.from_json(path.read_text(encoding="utf-8"))
            self._known = {f.id: f for f in fs}
            self._known_ids = set(self._known)

    @property
    def size(self) -> int:
        return len(self._known_ids)

    def accept(self, findings: List[Finding]) -> None:
        """Add these findings' IDs to the baseline and persist it.

        Only findings a detector established. Accepting a REASONED one
        would write a model's claim into the file that decides what a
        future run stays quiet about, which is the one place silence is
        purchased rather than earned. See schema.authoritative.
        """
        existing = FindingSet.from_json(self.path.read_text(encoding="utf-8")) \
            if self.path.exists() else FindingSet()
        existing_ids = {f.id for f in existing}
        for f in authoritative(findings):
            if f.id not in existing_ids:
                f.status = Status.SUPPRESSED
                existing.add(f)
                existing_ids.add(f.id)
        self.path.write_text(existing.to_json(), encoding="utf-8")
        self._known_ids = existing_ids

    def diff(self, current: List[Finding]) -> Tuple[List[Finding], List[Finding]]:
        """Split `current` into (new, already_known). `new` is what a
        report should actually surface; `already_known` still exists but
        was already accepted into the baseline on a prior run.

        An accepted finding whose severity has since risen is NEW again: the
        id hashes detector, path and summary, not severity, so before this an
        entry accepted as MINOR silently suppressed the same finding once it
        became CRITICAL (measured 2026-09-08)."""
        new: List[Finding] = []
        known: List[Finding] = []
        for f in current:
            stored = self._known.get(f.id)
            if stored is None:
                new.append(f)
            elif _rank(f.severity) < _rank(stored.severity):
                f.detail = (
                    f"ESCALATED since baseline: accepted as {stored.severity.value}, now {f.severity.value}. "
                    + (f.detail or "")
                ).strip()
                new.append(f)
            else:
                known.append(f)
        return new, known

    def stale(self, current: List[Finding]) -> List[Finding]:
        """Baseline entries that matched nothing in this run.

        Before this they were invisible: a fixed finding, a renamed detector
        and a baseline written on another machine all looked the same as a
        clean repository (measured 2026-09-08: 137 of 137 entries in one
        committed baseline were inert and nothing said so)."""
        seen = {f.id for f in current}
        return [f for fid, f in self._known.items() if fid not in seen]

    def derive_findings(self, current: List[Finding]) -> List[Finding]:
        """The baseline's own rot, as a finding rather than a receipt line.

        WHY THIS EXISTS AS A FINDING AND NOT A PRINTED LINE (v1.8.0)

        `stale` above has been able to answer this since 2026-09-08, and
        the answer went to stderr and nowhere else. So it reached a person
        reading a terminal and did not reach the JSON, which is what a
        pipeline reads, or the report a reviewer is handed. Measured on
        ATS: 35 of 48 entries inert, announced on the one channel most
        likely to be redirected to /dev/null, while the 13 live entries
        suppressed four MAJOR findings.

        A baseline is the only place in this tool where silence is
        purchased rather than earned (see the module docstring). A
        suppression list nobody can audit is therefore the one piece of
        state that most needs saying out loud, and it was the piece with
        no structured output at all.

        NO THRESHOLD, DELIBERATELY. The proportion is reported and not
        graded. "Mostly inert" and "a few entries fixed last week" are
        genuinely different situations, but which proportion is bad
        depends on how a team uses the file, and this tool does not ship
        numbers it has not measured (principle 4). The counts are in the
        attributes so a caller can apply its own cutoff.

        WHAT IT IS NOT: stale entries are not themselves suppressing
        anything -- by definition they match nothing. The defect is that
        the list cannot be read, so nobody can tell the inert entries from
        the live ones without doing this comparison by hand.
        """
        stale = self.stale(current)
        if not stale:
            return []
        proportion = len(stale) / self.size if self.size else 0.0
        first = sorted(stale, key=lambda f: f.id)[0]
        return [Finding(
            detector=DETECTOR, category=Category.STALE_FLAG, layer=Layer.MECHANICAL,
            severity=Severity.MINOR, status=Status.CONFIRMED,
            summary=(f"{len(stale)} of {self.size} baseline entries "
                     f"({proportion:.0%}) matched nothing in this scan"),
            evidence=Evidence(file=str(self.path)),
            detail=(
                "Every one of these entries suppresses a finding that no longer "
                "occurs. Three things look identical here and the file cannot "
                "tell them apart: a defect that was fixed, a detector that was "
                "renamed, and a baseline written against a different checkout "
                "-- the last of which suppresses nothing it was meant to and "
                "may be suppressing something it was not.\n\n"
                "The live entries are the ones worth reading, and they are the "
                "ones this rot hides: a reviewer asked to audit what a "
                "repository has agreed to stop seeing has to separate them by "
                "hand first.\n\n"
                "Regenerating the baseline (--accept on a scan you have read) "
                "clears the inert entries and re-accepts only what is still "
                "found. Do it having read the findings, not instead of.\n\n"
                f"First inert entry: {first.id} {first.evidence.file}"
            ),
            attributes={
                "stale": str(len(stale)), "size": str(self.size),
                "first_stale_id": first.id,
            },
        )]


def _rank(severity) -> int:
    from .schema import Severity
    return {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2, Severity.INFORMATIONAL: 3}[severity]
