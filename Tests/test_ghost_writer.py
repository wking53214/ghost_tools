from __future__ import annotations

from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status
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
