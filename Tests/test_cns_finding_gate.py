"""Ghost's finding gate (cns.gate): is this finding established well enough to act on.

Skipped where CNS is not installed; the tests workflow installs the cns extra, so in CI
they run. Every test builds its own finding: nothing here is shared, so no test can
leave a mutated finding for a later one, and the file passes in any order.
"""
from __future__ import annotations

import copy
import json

import pytest

gate = pytest.importorskip("cns.gate")
pytest.importorskip("cns.finding")

from ghost_buster import cns_adapter  # noqa: E402
from ghost_buster.cns_adapter import FindingGate  # noqa: E402
from ghost_buster.schema import (  # noqa: E402
    Category, Evidence, Finding, Layer, Severity, Status,
)

# What each Ghost status must come to. Written out here, not read from the module,
# so a changed table fails this file instead of silently agreeing with itself.
EXPECTED = {
    Status.CONFIRMED: gate.GateOutcome.PASS,
    Status.CONFIRMED_BY_REVIEW: gate.GateOutcome.PASS,
    Status.SUPPRESSED: gate.GateOutcome.PASS,
    Status.REASONED: gate.GateOutcome.RETRY,
    Status.REJECTED: gate.GateOutcome.TERMINAL_BREACH,
}


def _finding(status=Status.CONFIRMED, summary="helper is never called", **kw):
    """A fresh Ghost finding, built the way a detector builds one."""
    return Finding(
        detector=kw.pop("detector", "dead_code"),
        category=Category.DEAD_CODE,
        layer=kw.pop("layer", Layer.SEMANTIC if status is Status.REASONED else Layer.MECHANICAL),
        severity=Severity.MINOR,
        status=status,
        summary=summary,
        evidence=kw.pop("evidence", Evidence(file="pkg/mod.py", line_start=3, line_end=9,
                                              snippet="def helper(): ...")),
        detail=kw.pop("detail", "nothing references it"),
        attributes=kw.pop("attributes", {"symbol": "helper"}),
        **kw,
    )


def _row(status=Status.CONFIRMED, **kw):
    """The mapping Ghost writes for a finding, as a fresh dict."""
    return _finding(status, **kw).as_dict()


def test_the_gate_satisfies_the_cns_protocol_at_the_alpha_end():
    g = FindingGate()
    assert isinstance(g, gate.Gate)
    assert g.name == "ghost.finding_established" and g.position is gate.GatePosition.ALPHA
    result = g.check(_row())
    assert result.position is gate.GatePosition.ALPHA and result.gate == "ghost.finding_established"


def test_every_ghost_status_is_covered_here():
    assert set(EXPECTED) == set(Status)


@pytest.mark.parametrize("status", list(Status))
@pytest.mark.parametrize("form", ["mapping", "object", "json"])
def test_each_status_maps_to_its_outcome_in_every_form(status, form):
    finding = _finding(status)
    candidate = {"mapping": finding.as_dict(), "object": finding,
                 "json": json.loads(json.dumps(finding.as_dict()))}[form]
    result = FindingGate().check(candidate)
    assert result.outcome is EXPECTED[status]
    assert result.bound() and result.subject == finding.id


@pytest.mark.parametrize("status", list(Status))
def test_the_gate_and_the_adapter_never_disagree_on_a_status(status):
    result = FindingGate().check(_row(status))
    adapted = cns_adapter.translate_status(status, {"path": "pkg/mod.py", "id": "x"})
    assert result.outcome.value == adapted.translation.cns_outcome
    assert result.reason == adapted.translation.reason


def test_there_is_one_table_so_changing_it_moves_both(monkeypatch):
    monkeypatch.setitem(cns_adapter._STATUS_TO_OUTCOME, "confirmed", ("retry", "table moved"))
    result = FindingGate().check(_row(Status.CONFIRMED))
    adapted = cns_adapter.translate_status(Status.CONFIRMED, {"path": "a.py"})
    assert result.outcome is gate.GateOutcome.RETRY and result.reason == "table moved"
    assert adapted.translation.cns_outcome == "retry"


@pytest.mark.parametrize("odd", ["weird", "CONFIRMED_OR_NOT", "pass", "unknown"])
def test_a_status_ghost_does_not_produce_is_a_breach_never_a_pass(odd):
    row = _row()
    row["status"] = odd
    result = FindingGate().check(row)
    assert result.outcome is gate.GateOutcome.TERMINAL_BREACH
    assert "never read as permission" in result.reason
    assert result.bound()  # it judged this exact content


def test_the_adapter_still_reads_an_unmapped_status_as_retry():
    # translate_status is unchanged. The gate is stricter on purpose; see FindingGate.
    adapted = cns_adapter.translate_status("weird", {"path": "a.py"})
    assert adapted.translation.cns_outcome == "retry"


def test_the_status_is_read_the_way_the_adapter_reads_it():
    for spelled in ("Confirmed", " reasoned ", "REJECTED"):
        row = _row()
        row["status"] = spelled
        adapted = cns_adapter.translate_status(spelled, {"path": "a.py"})
        assert FindingGate().check(row).outcome.value == adapted.translation.cns_outcome


def test_the_object_and_the_mapping_and_the_json_of_one_finding_bind_the_same_digest():
    finding = _finding()
    digests = {
        FindingGate().check(finding).subject_digest,
        FindingGate().check(finding.as_dict()).subject_digest,
        FindingGate().check(json.loads(json.dumps(finding.as_dict()))).subject_digest,
    }
    assert len(digests) == 1 and "" not in digests


def test_a_status_given_as_the_enum_binds_like_its_text():
    row = _row()
    as_enum = dict(row, status=Status.CONFIRMED)
    assert FindingGate().check(as_enum).subject_digest == FindingGate().check(row).subject_digest
    assert FindingGate().check(as_enum).outcome is gate.GateOutcome.PASS


def test_the_verdict_is_bound_to_the_finding_it_judged():
    row = _row()
    first = FindingGate().check(row)
    again = FindingGate().check(copy.deepcopy(row))
    assert first.subject_digest == again.subject_digest and first.bound()
    assert first.binds(row["id"], gate.subject_digest(row))
    assert first.subject == row["id"]


@pytest.mark.parametrize("change", [
    lambda r: r.update(summary="a different sentence"),
    lambda r: r.update(detail="other detail"),
    lambda r: r["evidence"].update(line_start=4),
    lambda r: r["evidence"].update(snippet="def other(): ..."),
    lambda r: r["attributes"].update(symbol="other"),
    lambda r: r["attributes"].update(added="key"),
    lambda r: r.update(severity="major"),
    lambda r: r.update(status="confirmed_by_review"),
    lambda r: r.update(extra_key_ghost_may_add="x"),
])
def test_a_changed_finding_gets_a_different_digest_everything_judged_is_bound(change):
    row = _row()
    before = FindingGate().check(row)
    other = copy.deepcopy(row)
    change(other)
    after = FindingGate().check(other)
    assert before.subject_digest != after.subject_digest and after.bound()


def test_a_verdict_cannot_be_moved_to_other_content():
    mine, theirs = _row(summary="mine"), _row(summary="theirs")
    verdict = FindingGate().check(mine)
    other = FindingGate().check(theirs)
    assert verdict.subject_digest != other.subject_digest
    assert not verdict.binds(mine["id"], other.subject_digest)
    assert not verdict.binds(theirs["id"], verdict.subject_digest)
    forged = gate.GateResult(verdict.gate, verdict.position, verdict.outcome, "", "", "")
    assert not forged.binds("", "")


def test_the_gate_does_not_change_the_finding_it_reads():
    row = _row()
    snapshot = copy.deepcopy(row)
    FindingGate().check(row)
    assert row == snapshot
    finding = _finding()
    taken = finding.as_dict()
    FindingGate().check(finding)
    assert finding.as_dict() == taken


def _short(field):
    row = _row()
    row[field] = ""
    return row


def _missing(field):
    row = _row()
    del row[field]
    return row


def _typed(field, value):
    row = _row()
    row[field] = value
    return row


@pytest.mark.parametrize("candidate", [
    _missing("id"), _missing("detector"), _missing("severity"), _missing("status"),
    _missing("summary"), _short("id"), _short("summary"), _short("status"),
    _typed("id", 7), _typed("severity", None), _typed("summary", ["x"]),
    _typed("detail", 4), _typed("evidence", ["not", "an", "object"]),
    _typed("attributes", "text"),
    {}, "not a finding", None, 7, ["a"], object(), b"bytes",
])
def test_a_row_that_does_not_meet_cns_finding_is_a_breach_and_unbound(candidate):
    result = FindingGate().check(candidate)
    assert result.outcome is gate.GateOutcome.TERMINAL_BREACH
    assert not result.bound() and result.blocking()
    assert result.subject  # the label is never empty, even when nothing could be bound


def _cycle():
    d = {}
    d["self"] = d
    return d


@pytest.mark.parametrize("make", [
    lambda: _typed("evidence", {"file": "a.py", "span": {1, 2}}),
    lambda: _typed("evidence", {"file": "a.py", "line_start": float("nan")}),
    lambda: _typed("evidence", {"file": "a.py", "line_start": float("inf")}),
    lambda: _typed("attributes", {1: "a", "1": "b"}),
    lambda: _typed("attributes", _cycle()),
    lambda: _typed("attributes", {"obj": object()}),
    lambda: _typed("evidence", {"raw": b"bytes"}),
])
def test_content_that_cannot_be_bound_is_a_breach_and_unbound_not_a_crash(make):
    result = FindingGate().check(make())
    assert result.outcome is gate.GateOutcome.TERMINAL_BREACH
    assert not result.bound() and result.blocking()


def test_an_evidence_object_in_place_of_the_json_object_is_not_a_row():
    row = _typed("evidence", Evidence(file="a.py"))
    result = FindingGate().check(row)
    assert result.outcome is gate.GateOutcome.TERMINAL_BREACH and not result.bound()


def test_an_exception_from_ghosts_own_code_is_not_turned_into_a_pass():
    class Broken(Finding):
        def as_dict(self):
            raise RuntimeError("boom")

    base = _finding()
    broken = Broken(
        detector=base.detector, category=base.category, layer=base.layer,
        severity=base.severity, status=base.status, summary=base.summary,
        evidence=base.evidence,
    )
    with pytest.raises(RuntimeError):
        FindingGate().check(broken)


def test_resolve_treats_the_finding_gate_like_any_other_gate():
    def other(outcome):
        return gate.GateResult("other.alpha", gate.GatePosition.ALPHA, outcome, "r", "x", "y")

    passing = FindingGate().check(_row(Status.CONFIRMED))
    retry = FindingGate().check(_row(Status.REASONED))
    breach = FindingGate().check(_row(Status.REJECTED))
    assert gate.resolve([passing]) is gate.GateOutcome.PASS
    assert gate.resolve([passing, retry]) is gate.GateOutcome.RETRY
    assert gate.resolve([retry, breach, other(gate.GateOutcome.PASS)]) \
        is gate.GateOutcome.TERMINAL_BREACH
    assert gate.resolve([passing, other(gate.GateOutcome.RETRY)]) is gate.GateOutcome.RETRY
    assert gate.unbound([passing, retry, breach]) == ()
    assert gate.unbound([FindingGate().check("nothing")]) == ("ghost.finding_established",)
