"""Ghost's own JSON report, checked against cns.finding at the source.

Skipped where CNS is not installed; the tests workflow installs the cns extra. The
reports here come from the real writer (`ghost_buster.cli`), so a field that drifts
in what Ghost emits fails this file in ghost_tools' own CI.
"""
from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("cns.gate")
finding_module = pytest.importorskip("cns.finding")

from ghost_buster import cli as buster_cli  # noqa: E402
from ghost_buster.cns_adapter import ReportCheck, check_report  # noqa: E402
from ghost_buster.schema import (  # noqa: E402
    Category, Evidence, Finding, FindingSet, Layer, Severity, Status,
)

BASE = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
        "--no-correlate", "--no-structure", "--single-repo", "--json"]


def _scan(tmp_path, capsys):
    """Run Ghost for real on a small tree and return the JSON text it printed."""
    root = tmp_path / "tgt"
    root.mkdir()
    (root / "m.py").write_text("def orphan_one():\n    return 1\n\ndef orphan_two():\n    return 2\n")
    buster_cli.main([str(root), *BASE])
    return capsys.readouterr().out


def _finding(status=Status.CONFIRMED, **kw):
    return Finding(
        detector="dead_code", category=Category.DEAD_CODE,
        layer=Layer.SEMANTIC if status is Status.REASONED else Layer.MECHANICAL,
        severity=Severity.MINOR, status=status, summary=kw.pop("summary", "never called"),
        evidence=Evidence(file="pkg/mod.py", line_start=1, snippet="def f(): ..."),
        attributes={"symbol": "f"}, **kw)


def _object(findings):
    return {"status": "ok", "findings": [f.as_dict() for f in findings]}


def test_a_real_scan_report_meets_the_row(tmp_path, capsys):
    text = _scan(tmp_path, capsys)
    printed = json.loads(text)["findings"]
    assert printed, "the scan found nothing, so this test would prove nothing"
    result = check_report(text)
    assert isinstance(result, ReportCheck) and result.ok and result.problems == ()
    assert [r.id for r in result.rows] == [f["id"] for f in printed]
    assert all(isinstance(r, finding_module.Finding) for r in result.rows)


def test_the_parsed_object_the_text_and_a_file_read_the_same(tmp_path, capsys):
    text = _scan(tmp_path, capsys)
    saved = tmp_path / "report.json"
    saved.write_text(text)
    ids = [r.id for r in check_report(text).rows]
    assert [r.id for r in check_report(json.loads(text)).rows] == ids
    assert [r.id for r in check_report(saved).rows] == ids
    assert len(ids) >= 2


def test_the_old_bare_list_reads_like_the_new_object():
    findings = [_finding(Status.CONFIRMED), _finding(Status.REASONED, summary="maybe")]
    bare = FindingSet(findings).to_json()
    wrapped = _object(findings)
    assert [r.id for r in check_report(bare).rows] == [r.id for r in check_report(wrapped).rows]
    assert check_report(bare).ok and len(check_report(wrapped).rows) == 2


def test_every_status_ghost_can_carry_is_accepted_as_text():
    every = [_finding(s) for s in Status if s is not Status.REASONED]
    every.append(_finding(Status.REASONED, summary="maybe"))
    assert check_report(_object(every)).ok


@pytest.mark.parametrize("drift", [
    lambda f: f.pop("summary"),
    lambda f: f.update(id=12),
    lambda f: f.update(severity=None),
    lambda f: f.update(status=["confirmed"]),
    lambda f: f.update(detector=""),
    lambda f: f.update(evidence="pkg/mod.py"),
    lambda f: f.update(attributes=["a"]),
    lambda f: f.update(detail=3),
])
def test_a_drifting_field_is_named_as_a_problem_and_good_rows_still_come_back(drift):
    good = _finding().as_dict()
    bad = _finding(summary="another").as_dict()
    drift(bad)
    result = check_report({"findings": [good, bad]})
    assert not result.ok and len(result.problems) == 1
    assert result.problems[0].startswith("findings[1]")
    assert [r.id for r in result.rows] == [good["id"]]


def test_a_problem_names_the_finding_by_id_when_it_has_one():
    bad = _finding().as_dict()
    bad["summary"] = ""
    [problem] = check_report([bad]).problems
    assert f"({bad['id']})" in problem and "summary" in problem


@pytest.mark.parametrize("report", [
    "not json", "", "7", "null", "{}", '{"findings": "x"}', '{"findings": {"a": 1}}',
    7, None, {"status": "ok"}, {"findings": None}, b"[]",
])
def test_a_report_that_cannot_be_read_is_a_problem_not_a_crash_and_not_clean(report):
    result = check_report(report)
    assert not result.ok and result.rows == () and len(result.problems) == 1


def test_a_missing_file_is_a_problem(tmp_path):
    result = check_report(tmp_path / "absent.json")
    assert not result.ok and "could not be read" in result.problems[0]


def test_an_entry_that_is_not_an_object_is_a_problem():
    result = check_report([_finding().as_dict(), "text", None, 4])
    assert len(result.rows) == 1 and len(result.problems) == 3


def test_an_empty_list_of_findings_is_ok_and_says_nothing_about_a_clean_tree():
    assert check_report([]).ok and check_report({"findings": []}).ok
    assert check_report([]).rows == ()


def test_checking_changes_nothing_and_a_second_check_agrees():
    report = _object([_finding(), _finding(summary="second")])
    snapshot = copy.deepcopy(report)
    first, second = check_report(report), check_report(report)
    assert report == snapshot
    assert first == second and first.ok
