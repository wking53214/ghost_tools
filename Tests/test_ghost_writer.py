from __future__ import annotations

import json

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
        "findings": [{"proposed_replacement": "new text", "reasoning": "why", "confidence": 0.9}]
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
