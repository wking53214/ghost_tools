"""schema.py -- the one finding shape every detector (mechanical or
semantic) produces, and every downstream consumer (baseline diffing,
ghost_writer) reads.

WHY ONE SHARED SCHEMA
-----------------------
This is the design decision that keeps ghost_buster from becoming two
unrelated tools wearing one name. Layer 1 (mechanical, this module's
sibling `mechanical.py`) and Layer 2 (semantic, `semantic.py`, backed by
a real Claude API call) produce wildly different KINDS of findings --
but every one of them is still "here is a specific claim, here is the
evidence, here is how sure we are, here is what it would take to check
again." That shape is Finding, below.

STATUS VOCABULARY -- reused deliberately, not reinvented
-----------------------------------------------------------
This is the exact execution-status discipline proven out over dozens of
findings against HERALD earlier: never claim more confidence than was
actually earned. A mechanical detector's output is CONFIRMED the moment
it runs -- it's deterministic code touching real files, there's nothing
to doubt. A semantic (LLM-backed) detector's output is NEVER CONFIRMED
on its own; it starts at REASONED (a plausible claim, unverified) and
only becomes CONFIRMED once a human (or a second, independent check)
verifies it. This distinction is load-bearing, not decorative: it's what
stops ghost_buster from inheriting the exact "hallucinated, unreviewed,
non-deterministic AI output" failure mode it exists to catch elsewhere.

SEVERITY IS SEPARATE FROM STATUS
-----------------------------------
Severity (how bad, if true) and status (how sure we are it's true) are
orthogonal. A CONFIRMED dead-code finding can be INFORMATIONAL (an
unused private helper, harmless). A REASONED semantic finding can be
CRITICAL (two implementations of the same governor, one silently unused)
even before anyone's confirmed it. Collapsing these into one axis is how
a report ends up either crying wolf constantly or burying the one
finding that matters -- exactly the "noise drowns signal" failure this
tool is designed not to repeat.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    CRITICAL = "critical"          # actively misleading or dangerous if acted on
    MAJOR = "major"                # real maintainability/correctness risk
    MINOR = "minor"                # real but low-consequence
    INFORMATIONAL = "informational"  # worth knowing, not worth prioritizing


class Status(str, Enum):
    """How sure ghost_buster is that this finding is real. See module
    docstring -- this is intentionally the same discipline as the HULK
    campaign's status vocabulary, narrowed to what ghost_buster actually
    needs."""

    CONFIRMED = "confirmed"                  # deterministic detector; not in doubt
    REASONED = "reasoned"                    # semantic/LLM claim; not yet verified
    CONFIRMED_BY_REVIEW = "confirmed_by_review"  # a REASONED finding a human verified
    REJECTED = "rejected"                    # a human looked and said no
    SUPPRESSED = "suppressed"                # known, accepted, tracked -- not re-surfaced


class Category(str, Enum):
    """Maps directly onto the researched taxonomy. Kept as an enum (not
    a free string) so the detector registry and the baseline file can't
    silently drift into inconsistent category names across detectors."""

    DUPLICATION = "duplication"
    DEAD_CODE = "dead_code"
    COMPLEXITY = "complexity"
    STALE_FLAG = "stale_flag"
    PARALLEL_IMPLEMENTATION = "parallel_implementation"
    DOC_DRIFT = "doc_drift"
    ARCHITECTURE = "architecture"
    OTHER = "other"


class Layer(str, Enum):
    MECHANICAL = "mechanical"
    SEMANTIC = "semantic"


def _stable_id(*parts: str) -> str:
    """A finding's ID is a content hash of what identifies it (detector
    name + file + the specific thing found) -- NOT a counter. A counter
    renumbers every run depending on what order detectors happen to
    execute in, which breaks baseline diffing (finding #47 today is not
    finding #47 tomorrow just because an earlier detector found one more
    thing). A content-hash ID is the same across runs for the same
    underlying finding, and changes only when the finding itself changes
    -- which is exactly the property baseline diffing needs."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"ghost-{digest[:12]}"


@dataclass
class Evidence:
    """Where a finding points, precisely enough that a human can go
    look without re-deriving what the detector already knows."""

    file: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    snippet: Optional[str] = None
    related_files: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    """One ghost. Produced by exactly one detector, identified by a
    stable content-hash ID, carrying enough evidence that a human (or
    ghost_writer, downstream) never has to re-run the detector to
    understand what it found.
    """

    detector: str
    category: Category
    layer: Layer
    severity: Severity
    status: Status
    summary: str
    evidence: Evidence
    detail: str = ""
    confidence: Optional[float] = None  # 0.0-1.0, semantic layer only; None for mechanical
    first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    disposition: Optional[str] = None  # set by the human triage step, see triage.py
    disposition_note: str = ""
    id: str = field(init=False)

    def __post_init__(self):
        self.id = _stable_id(
            self.detector, self.evidence.file, self.summary,
        )
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be 0.0-1.0, got {self.confidence}")
        if self.layer == Layer.MECHANICAL and self.status == Status.REASONED:
            raise ValueError(
                f"{self.detector}: a mechanical-layer finding cannot have "
                "status REASONED -- mechanical detectors are deterministic; "
                "the finding is either present (CONFIRMED) or it wasn't "
                "produced at all. REASONED is reserved for the semantic layer."
            )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "detector": self.detector,
            "category": self.category.value,
            "layer": self.layer.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "summary": self.summary,
            "detail": self.detail,
            "evidence": self.evidence.as_dict(),
            "confidence": self.confidence,
            "first_seen": self.first_seen,
            "disposition": self.disposition,
            "disposition_note": self.disposition_note,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Finding":
        ev = payload["evidence"]
        finding = cls(
            detector=payload["detector"],
            category=Category(payload["category"]),
            layer=Layer(payload["layer"]),
            severity=Severity(payload["severity"]),
            status=Status(payload["status"]),
            summary=payload["summary"],
            detail=payload.get("detail", ""),
            evidence=Evidence(
                file=ev["file"], line_start=ev.get("line_start"),
                line_end=ev.get("line_end"), snippet=ev.get("snippet"),
                related_files=ev.get("related_files", []),
            ),
            confidence=payload.get("confidence"),
            first_seen=payload.get("first_seen", datetime.now(timezone.utc).isoformat()),
            disposition=payload.get("disposition"),
            disposition_note=payload.get("disposition_note", ""),
        )
        return finding


class FindingSet:
    """A run's worth of findings, with the JSON round-trip ghost_writer
    and the baseline mechanism both depend on."""

    def __init__(self, findings: Optional[List[Finding]] = None):
        self.findings: List[Finding] = list(findings or [])

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def by_status(self, status: Status) -> List[Finding]:
        return [f for f in self.findings if f.status == status]

    def by_severity(self, severity: Severity) -> List[Finding]:
        return [f for f in self.findings if f.severity == severity]

    def to_json(self) -> str:
        return json.dumps([f.as_dict() for f in self.findings], indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "FindingSet":
        payload = json.loads(text)
        return cls([Finding.from_dict(p) for p in payload])

    def __len__(self) -> int:
        return len(self.findings)

    def __iter__(self):
        return iter(self.findings)
