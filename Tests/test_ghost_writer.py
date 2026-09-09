from __future__ import annotations

import json

import pytest

from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status
from ghost_buster.semantic import StubModelClient
from ghost_writer.correct import propose_correction
from ghost_writer.report import dispositioned_for_documentation, render_ghost_report


def _finding(disposition=None, category=Category.OTHER, summary="s"):
    return Finding(
        detector="d", category=category, layer=Layer.MECHANICAL,
        severity=Severity.MINOR, status=Status.CONFIRMED, summary=summary,
        evidence=Evidence(file="a.py"), disposition=disposition,
    )


def test_triage_gate_only_admits_document_disposition():
    findings = [_finding(None), _finding("fix"), _finding("suppress"), _finding("document")]
    result = dispositioned_for_documentation(findings)
    assert len(result) == 1
    assert result[0].disposition == "document"


def test_report_omits_undispositioned_findings():
    findings = [_finding(None, summary="should not appear")]
    report = render_ghost_report(findings)
    assert "should not appear" not in report
    assert "None currently dispositioned" in report


def test_report_includes_disposition_note_as_why_documented():
    f = _finding("document", summary="two harnesses coexist")
    f.disposition_note = "intentional migration path"
    report = render_ghost_report([f])
    assert "two harnesses coexist" in report
    assert "intentional migration path" in report


def test_report_groups_by_category():
    f1 = _finding("document", category=Category.DEAD_CODE, summary="dead thing")
    f2 = _finding("document", category=Category.DOC_DRIFT, summary="stale claim")
    report = render_ghost_report([f1, f2])
    assert "Dead Code" in report
    assert "Doc Drift" in report


def test_propose_correction_happy_path():
    stub = StubModelClient(json.dumps({
        "findings": [{"proposed_replacement": "new text", "reasoning": "why: the code summary is the evidence", "confidence": 0.9}]
    }))
    drift = Finding(
        detector="doc_drift", category=Category.DOC_DRIFT, layer=Layer.SEMANTIC,
        severity=Severity.MAJOR, status=Status.REASONED, summary="stale claim",
        evidence=Evidence(file="README.md"),
    )
    proposal, report = propose_correction(stub, drift, "current behavior")
    assert proposal is not None
    assert proposal.proposed_replacement == "new text"
    assert proposal.doc_path == "README.md"
    assert proposal.original_claim == "stale claim"


def test_propose_correction_fails_closed_on_empty_response():
    stub = StubModelClient(json.dumps({"findings": []}))
    drift = Finding(
        detector="doc_drift", category=Category.DOC_DRIFT, layer=Layer.SEMANTIC,
        severity=Severity.MAJOR, status=Status.REASONED, summary="stale claim",
        evidence=Evidence(file="README.md"),
    )
    proposal, report = propose_correction(stub, drift, "current behavior")
    assert proposal is None
    assert report.ran is True


def test_propose_correction_fails_closed_on_malformed_json():
    stub = StubModelClient("not json")
    drift = Finding(
        detector="doc_drift", category=Category.DOC_DRIFT, layer=Layer.SEMANTIC,
        severity=Severity.MAJOR, status=Status.REASONED, summary="stale claim",
        evidence=Evidence(file="README.md"),
    )
    proposal, report = propose_correction(stub, drift, "current behavior")
    assert proposal is None
    assert report.parse_error is not None


def test_propose_correction_never_auto_applies_only_returns_a_proposal():
    """Structural test of the design guarantee, not just behavior: this
    module must not import anything filesystem-writing at all."""
    import ghost_writer.correct as mod
    import inspect
    source = inspect.getsource(mod)
    assert "open(" not in source
    assert ".write_text(" not in source
    assert ".write(" not in source


# ---------------------------------------------------------------------------
# The quality gate around correct.py's LLM call (ghost_writer.polish)
# ---------------------------------------------------------------------------

def _drift():
    return Finding(
        detector="doc_drift", category=Category.DOC_DRIFT, layer=Layer.SEMANTIC,
        severity=Severity.MAJOR, status=Status.REASONED, summary="stale claim",
        evidence=Evidence(file="README.md"),
    )


class _SequenceStubClient:
    """StubModelClient returns one canned response forever; this one returns
    a different response per call, repeating the last, so a retry can be
    given something better than the attempt that was rejected."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._responses[min(len(self.calls), len(self._responses)) - 1]


def _response(replacement, reasoning, confidence=0.9):
    return json.dumps({"findings": [{
        "proposed_replacement": replacement, "reasoning": reasoning, "confidence": confidence,
    }]})


# First person, hedged, and citing nothing: all three filters fire.
_UNGATED = _response("I think this flag might still work", "we could be wrong", 0.4)
_CLEAN = _response("The flag is removed.", "the code summary lists no such flag: that is the evidence")


def test_gate_rejects_first_person_speculative_unsupported_response_and_retries():
    stub = StubModelClient(_UNGATED)
    proposal, report = propose_correction(stub, _drift(), "current behavior", max_attempts=3)
    assert proposal is None
    assert len(stub.calls) == 3
    assert report.ran is True
    assert report.reason.startswith("quality gate rejected 3 attempt(s): ")
    assert "First-person pronouns detected: I, we" in report.reason
    assert "Speculative language detected: I think, could, might" in report.reason
    assert "Missing empirical support" in report.reason
    # The first call carried no feedback; the retry carried the violations,
    # placed after the fenced untrusted block, never inside it.
    first_user = stub.calls[0][1]
    second_user = stub.calls[1][1]
    assert "RECALIBRATION FEEDBACK" not in first_user
    assert "[RECALIBRATION FEEDBACK - Attempt 1]" in second_user
    assert second_user.index("</untrusted_source_code>") < second_user.index("[RECALIBRATION")
    assert "First-person pronouns detected: I, we" in second_user
    assert "Speculative language detected: I think, could, might" in second_user
    assert "Missing empirical support" in second_user
    # The stale claim and code summary are fenced identically on every attempt.
    assert first_user.split("</untrusted_source_code>")[0] == second_user.split("</untrusted_source_code>")[0]


def test_gate_default_attempt_ceiling_is_three_paid_calls():
    stub = StubModelClient(_UNGATED)
    proposal, _ = propose_correction(stub, _drift(), "current behavior")
    assert proposal is None
    assert len(stub.calls) == 3


def test_gate_accepts_the_regenerated_response_after_one_rejection():
    stub = _SequenceStubClient([_UNGATED, _CLEAN])
    proposal, report = propose_correction(stub, _drift(), "current behavior")
    assert len(stub.calls) == 2
    assert proposal is not None
    assert proposal.proposed_replacement == "The flag is removed."
    assert proposal.reasoning == "the code summary lists no such flag: that is the evidence"
    assert proposal.confidence == 0.9
    assert proposal.doc_path == "README.md"
    assert proposal.original_claim == "stale claim"
    assert report.ran is True
    assert report.reason == "quality gate accepted attempt 2 of 3"


def test_gate_first_try_acceptance_leaves_the_report_reason_empty():
    proposal, report = propose_correction(StubModelClient(_CLEAN), _drift(), "current behavior")
    assert proposal is not None
    assert report.reason == ""


def test_gate_pronoun_and_speculation_checks_cover_the_replacement_text():
    # Reasoning is clean and cites evidence; only the replacement is at fault.
    stub = StubModelClient(_response("We may drop this flag.", "the code summary is the evidence"))
    proposal, report = propose_correction(stub, _drift(), "current behavior", max_attempts=2)
    assert proposal is None
    assert "First-person pronouns detected: We" in report.reason
    assert "Speculative language detected: may" in report.reason
    assert "Missing empirical support" not in report.reason


def test_gate_pronoun_and_speculation_checks_cover_the_reasoning_text():
    # Replacement is clean; only the reasoning is at fault (evidence present, hedged).
    stub = StubModelClient(_response("The flag is removed.", "I think the data probably shows this"))
    proposal, report = propose_correction(stub, _drift(), "current behavior", max_attempts=2)
    assert proposal is None
    assert "First-person pronouns detected: I" in report.reason
    assert "Speculative language detected: I think, probably" in report.reason
    assert "Missing empirical support" not in report.reason


def test_gate_empirical_check_is_scoped_to_the_reasoning():
    # An evidence word in the replacement does not excuse a reasoning that cites nothing.
    stub = StubModelClient(_response("Data files load from ./data.", "because"))
    proposal, report = propose_correction(stub, _drift(), "current behavior", max_attempts=2)
    assert proposal is None
    assert report.reason.startswith("quality gate rejected 2 attempt(s): ")
    assert "Missing empirical support" in report.reason
    assert "First-person" not in report.reason
    assert "Speculative" not in report.reason
    # And a replacement with no evidence vocabulary at all is not rejected for that.
    proposal, _ = propose_correction(
        StubModelClient(_response("The flag can be repeated.", "the code summary is the evidence")),
        _drift(), "current behavior",
    )
    assert proposal is not None
    assert proposal.proposed_replacement == "The flag can be repeated."


def test_gate_repeated_identical_rejection_is_reported_as_a_duplicate():
    stub = StubModelClient(_response("The flag is removed.", "because"))
    _, report = propose_correction(stub, _drift(), "current behavior", max_attempts=2)
    assert "Duplicate generation detected" in report.reason


@pytest.mark.parametrize("response", [
    "not json",
    json.dumps({"findings": []}),
    json.dumps({"findings": [{"reasoning": "no replacement key"}]}),
    json.dumps({"findings": ["not a dict"]}),
])
def test_gate_does_not_retry_the_pre_existing_fail_closed_paths(response):
    stub = StubModelClient(response)
    proposal, report = propose_correction(stub, _drift(), "current behavior")
    assert proposal is None
    assert len(stub.calls) == 1
    assert report.ran is True
    assert "quality gate" not in report.reason


def test_gate_does_not_retry_a_client_error():
    class _Failing:
        def __init__(self):
            self.calls = 0

        def complete(self, system, user):
            self.calls += 1
            raise RuntimeError("no key")

    client = _Failing()
    proposal, report = propose_correction(client, _drift(), "current behavior")
    assert proposal is None
    assert client.calls == 1
    assert report.ran is False
    assert "client error" in report.reason


def test_gate_rejects_an_attempt_ceiling_below_one():
    with pytest.raises(ValueError):
        propose_correction(StubModelClient(_CLEAN), _drift(), "current behavior", max_attempts=0)


def test_gate_does_not_log_the_default_signing_key_warning(caplog):
    with caplog.at_level("WARNING", logger="ghost_writer.polish"):
        propose_correction(StubModelClient(_CLEAN), _drift(), "current behavior")
    assert "default signing key" not in caplog.text
