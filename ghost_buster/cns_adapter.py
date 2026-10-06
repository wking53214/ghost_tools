"""Optional adapter: ghost_tools Status → cns.gate shapes.

CNS is never required to import or run ghost_tools. When ``cns.gate`` is
present, this module can produce a ``GateResult`` whose ``subject_digest``
comes from CNS. When CNS is absent, it returns an advisory translation
with no digest and no claimed gate authority.

This module does not modify CNS. It does not vendor CNS. It does not
treat a domain Status as a GateOutcome without an explicit mapping.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from .schema import Status

# Explicit translation — not identity.
# information_lost is always non-empty: severity, detector id, evidence spans.
_STATUS_TO_OUTCOME: dict[str, tuple[str, str]] = {
    Status.CONFIRMED.value: ("pass", "detector confirmed; continue with evidence on record"),
    Status.CONFIRMED_BY_REVIEW.value: ("pass", "human-confirmed; continue with evidence on record"),
    Status.SUPPRESSED.value: ("pass", "accepted into baseline; not a live defect"),
    Status.REASONED.value: ("retry", "unverified claim; re-examine before terminal action"),
    Status.REJECTED.value: ("terminal_breach", "finding rejected; stop treating as defect"),
}

_REQUIRED_GATE = ("GateOutcome", "GateResult", "GatePosition", "subject_digest")


@dataclass(frozen=True)
class CnsAvailability:
    ok: bool
    missing: Tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class TranslationRecord:
    source_model: str
    source_value: str
    cns_outcome: str
    reason: str
    information_preserved: str
    information_lost: str
    cns_present: bool
    subject_digest: str
    authority: str  # "cns.gate" | "advisory_only"


@dataclass(frozen=True)
class AdapterResult:
    translation: TranslationRecord
    gate_result: Optional[Any] = None


def cns_available() -> CnsAvailability:
    try:
        gate = importlib.import_module("cns.gate")
    except ImportError as e:
        return CnsAvailability(ok=False, missing=("cns.gate",), error=str(e))
    missing = tuple(n for n in _REQUIRED_GATE if not hasattr(gate, n))
    if missing:
        return CnsAvailability(ok=False, missing=missing, error=f"cns.gate lacks {missing}")
    return CnsAvailability(ok=True)


def translate_status(
    status: Status | str,
    subject: Mapping[str, object],
    *,
    gate_name: str = "ghost_tools.cns_adapter",
) -> AdapterResult:
    """Map a finding status to a CNS gate outcome.

    ``subject`` is the content digested when CNS is present (e.g. path,
    detector, summary). Only ``cns.gate.subject_digest`` is used for the
    digest field — never a local hash claimed to be equivalent.
    """
    if isinstance(status, Status):
        value = status.value
    else:
        value = str(status or "").strip().lower()

    outcome, reason = _STATUS_TO_OUTCOME.get(
        value, ("retry", "unmapped or unknown status; do not invent certainty")
    )
    if value not in _STATUS_TO_OUTCOME:
        value = value or "unknown"

    avail = cns_available()
    if not avail.ok:
        tr = TranslationRecord(
            source_model="ghost_tools.schema.Status",
            source_value=value,
            cns_outcome=outcome,
            reason=f"{reason} | CNS unavailable: {avail.error or avail.missing}",
            information_preserved="status label and explicit mapping table only",
            information_lost=(
                "canonical subject_digest; GateResult row; severity; detector id; "
                "evidence spans; layer"
            ),
            cns_present=False,
            subject_digest="",
            authority="advisory_only",
        )
        return AdapterResult(translation=tr, gate_result=None)

    gate = importlib.import_module("cns.gate")
    digest = gate.subject_digest(dict(subject))
    gr = gate.GateResult(
        gate=gate_name,
        position=gate.GatePosition.ALPHA,
        outcome=gate.GateOutcome(outcome),
        reason=reason,
        subject=str(subject.get("path") or subject.get("file") or subject.get("id") or ""),
        subject_digest=digest,
    )
    tr = TranslationRecord(
        source_model="ghost_tools.schema.Status",
        source_value=value,
        cns_outcome=outcome,
        reason=reason,
        information_preserved="status→outcome per mapping table; subject_digest from cns.gate",
        information_lost="severity ordinal; detector id; evidence spans; layer; correlation ids",
        cns_present=True,
        subject_digest=digest,
        authority="cns.gate",
    )
    return AdapterResult(translation=tr, gate_result=gr)


def translate_finding(finding: Any, *, gate_name: str = "ghost_tools.cns_adapter") -> AdapterResult:
    """Convenience: map a schema.Finding-like object."""
    status = getattr(finding, "status", None) or "unknown"
    subject = {
        "path": getattr(getattr(finding, "evidence", None), "file", None)
        or getattr(finding, "path", None)
        or "",
        "detector": getattr(finding, "detector", ""),
        "summary": getattr(finding, "summary", ""),
        "id": getattr(finding, "id", ""),
    }
    return translate_status(status, subject, gate_name=gate_name)
