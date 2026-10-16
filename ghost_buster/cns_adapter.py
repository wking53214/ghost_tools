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
import json
import os
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import Any, Mapping, Optional, Tuple

from .schema import Finding, Status

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


def _status_value(status: Status | str) -> str:
    """The table key for a status. translate_status and FindingGate both read it this way."""
    if isinstance(status, Status):
        return status.value
    return str(status or "").strip().lower()


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
    value = _status_value(status)

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


# ---------------------------------------------------------------------------
# The gate over one finding, and the check of Ghost's own report.
#
# Everything below needs CNS and asks for it only when a gate is constructed or
# a check is called. Importing this module never loads CNS.
# ---------------------------------------------------------------------------

INSTALL_HINT = "pip install 'ghost-tools[cns]'"

#: What a gate's ``subject`` is when the finding has no readable id.
DEFAULT_SUBJECT = "finding"

#: Name the finding gate reports itself under.
FINDING_GATE_NAME = "ghost.finding_established"

#: Deepest nesting the digest will follow. A finding is a few levels deep; this stops a cycle.
_MAX_DEPTH = 32


class CnsNotInstalled(ImportError):
    """Raised when a CNS-backed function is used and ``cns`` cannot be imported."""


def _cns_module(name: str) -> ModuleType:
    """Import a CNS module on demand, or say exactly what is missing."""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise CnsNotInstalled(
            f"ghost_buster.cns_adapter needs the CNS package ({name}), which is not "
            f"installed. Install it with: {INSTALL_HINT}. ghost_tools itself works "
            "without it."
        ) from exc


def _plain(value: object, depth: int = 0) -> object:
    """A finding as plain content a digest can bind: scalars, mappings and lists.

    Ghost writes a finding as JSON, so anything else inside one (an object, a set,
    bytes) is not a finding Ghost emitted and cannot be bound. NaN and the
    infinities pass here and are refused by ``cns.gate.subject_digest``.
    """
    if depth > _MAX_DEPTH:
        raise TypeError("the finding is nested too deeply to bind a verdict to")
    if isinstance(value, Enum):
        return _plain(value.value, depth + 1)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {k: _plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v, depth + 1) for v in value]
    raise TypeError(f"cannot bind a verdict to {type(value).__name__}")


class FindingGate:
    """Is this finding established well enough to act on, before anything is drafted for it.

    Ghost's own question, asked in Ghost's own vocabulary, at the ALPHA end: it judges
    a finding before any work is done for it. It does not decide what a result means
    for a run; that is the Judge's.

    ``check`` takes one finding, as the mapping Ghost writes (``Finding.as_dict()``,
    the JSON object) or as ``ghost_buster.schema.Finding``, and returns a
    ``cns.gate.GateResult`` bound to the whole finding, evidence and attributes
    included. The status is read through the same table ``translate_status`` uses:

    ===============================  ===============  ==============================
    Ghost status                     CNS              why
    ===============================  ===============  ==============================
    confirmed, confirmed_by_review,  PASS             established, or accepted
    suppressed
    reasoned                         RETRY            an unverified claim; verify it
                                                      and ask again
    rejected                         TERMINAL_BREACH  a human said no; do not draft
    a status not in the table        TERMINAL_BREACH  never read as permission
    a row that is not a              TERMINAL_BREACH  unbound
    ``cns.finding/1``, or content
    that cannot be bound
    ===============================  ===============  ==============================

    The table is ``_STATUS_TO_OUTCOME``, one source of truth. ``translate_status`` reads
    an unmapped status as RETRY; this gate reads it as TERMINAL_BREACH, because a status
    Ghost does not produce is drift, and asking again cannot repair drift.

    An exception from Ghost's own code propagates; it is never turned into a PASS.
    Constructing the gate without CNS installed raises ``CnsNotInstalled``.
    """

    def __init__(self) -> None:
        self._gate = _cns_module("cns.gate")
        self._row = _cns_module("cns.finding").Finding

    @property
    def name(self) -> str:
        return FINDING_GATE_NAME

    @property
    def position(self) -> Any:
        return self._gate.GatePosition.ALPHA

    def _result(self, outcome: Any, reason: str, subject: str, digest: str = "") -> Any:
        return self._gate.GateResult(
            gate=self.name,
            position=self._gate.GatePosition.ALPHA,
            outcome=outcome,
            reason=reason,
            subject=subject,
            subject_digest=digest,
        )

    def check(self, candidate: object) -> Any:
        breach = self._gate.GateOutcome.TERMINAL_BREACH
        record = candidate.as_dict() if isinstance(candidate, Finding) else candidate
        if not isinstance(record, Mapping):
            return self._result(
                breach,
                f"{type(candidate).__name__} is not a finding, so nothing is approved",
                DEFAULT_SUBJECT,
            )
        label = record.get("id")
        subject = label if isinstance(label, str) and label.strip() else DEFAULT_SUBJECT
        try:
            self._row.from_dict(record)
        except (ValueError, TypeError) as exc:
            return self._result(
                breach, f"the finding does not meet cns.finding/1, so nothing is approved ({exc})",
                subject,
            )
        try:
            content = _plain(record)
            digest = self._gate.subject_digest(content)
        except (TypeError, ValueError, RecursionError) as exc:
            return self._result(
                breach,
                f"the finding cannot be bound to a verdict, so nothing is approved ({exc})",
                subject,
            )
        value = _status_value(content["status"])
        mapped = _STATUS_TO_OUTCOME.get(value)
        if mapped is None:
            return self._result(
                breach,
                f"status {value!r} is not one Ghost produces; an unknown status is never "
                "read as permission",
                subject,
                digest,
            )
        outcome, reason = mapped
        return self._result(self._gate.GateOutcome(outcome), reason, subject, digest)



@dataclass(frozen=True)
class ReportCheck:
    """What :func:`check_report` found: the rows that meet ``cns.finding/1`` and the problems."""

    rows: Tuple[Any, ...] = ()
    problems: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True when every finding in the report met the row and the report could be read."""
        return not self.problems


def _findings_of(report: Any) -> list:
    """The findings in a report as Ghost writes it, or raise ValueError saying what is wrong.

    ``report`` is parsed JSON (the object ``ghost-buster --json`` prints, or the old
    bare list), JSON text, or a path to a file holding either.
    """
    if isinstance(report, os.PathLike):
        try:
            with open(report, encoding="utf-8") as handle:
                report = handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"the report could not be read ({exc})") from exc
    if isinstance(report, str):
        try:
            report = json.loads(report)
        except ValueError as exc:
            raise ValueError(f"the report is not JSON ({exc})") from exc
    if isinstance(report, Mapping):
        if "findings" not in report:
            raise ValueError("the report is an object with no findings member")
        report = report["findings"]
    if not isinstance(report, list):
        raise ValueError(f"the findings are {type(report).__name__}, not a list")
    return report


def check_report(report: Any) -> ReportCheck:
    """Check every finding in Ghost's own JSON report against ``cns.finding.Finding``.

    This is the source-side check: Warden reads these findings against the same row at
    read time, and this finds a drifting field in ghost_tools' own CI instead. It reads
    the old bare list and the object with a ``findings`` member the same way, changes
    nothing, and decides nothing: it returns the rows that met the row and one problem
    per finding that did not. A report that cannot be read at all is a problem, not a
    crash. An empty report is ``ok``; whether an empty report means a clean tree is
    the report's ``status`` and ``unmeasured``, which this does not read.
    """
    row = _cns_module("cns.finding").Finding
    try:
        found = _findings_of(report)
    except ValueError as exc:
        return ReportCheck(problems=(str(exc),))
    rows, problems = [], []
    for index, record in enumerate(found):
        try:
            rows.append(row.from_dict(record))
        except (ValueError, TypeError) as exc:
            label = record.get("id") if isinstance(record, Mapping) else None
            named = f" ({label})" if isinstance(label, str) and label else ""
            problems.append(f"findings[{index}]{named}: {exc}")
    return ReportCheck(rows=tuple(rows), problems=tuple(problems))


def cns_chain() -> Any:
    """A ``cns.gate.GateChain`` holding the finding gate in the ``alpha`` slot.

    ``omega`` stays empty: Ghost reports findings and does not judge a run's result,
    so ``complete()`` is ``False`` by design. A consumer that wants a complete chain
    supplies the ``omega`` end from a repository that has one (the Judge).
    """
    return _cns_module("cns.gate").GateChain(alpha=(FindingGate(),))
