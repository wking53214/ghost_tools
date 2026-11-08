"""A case file that cannot be read is a usage error, not a crash.

`--casefile` pointing at malformed JSON used to print a raw traceback after the
scan and exit 3 ("internal error"), where a malformed `--baseline` was already a
clean exit 2. The case file is now read before the scan starts, the same way, and
`--priors` and `ghost_triage --casefile` refuse it too.
"""
from __future__ import annotations

import json

import pytest

from ghost_buster import cli as buster_cli
from ghost_buster.casefile import Casefile, CasefileError
from ghost_buster.schema import Category, Evidence, Finding, FindingSet, Layer, Severity, Status
from ghost_writer import triage

QUIET = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
         "--no-correlate", "--no-ledger", "--no-structure", "--single-repo"]

BAD_CONTENTS = {
    "truncated json": '{"cases": [',
    "not json": "this is not json",
    "a list, not an object": "[1, 2]",
    "cases is not a list": '{"cases": 5}',
    "a case with unknown fields": '{"cases": [{"nonsense": 1}]}',
    "a case that is not an object": '{"cases": [7]}',
}


def _tree(tmp_path):
    root = tmp_path / "tgt"
    root.mkdir()
    (root / "m.py").write_text("def used():\n    return 1\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("contents", BAD_CONTENTS.values(), ids=BAD_CONTENTS.keys())
def test_an_unreadable_case_file_is_a_usage_error_without_a_traceback(tmp_path, capsys, contents):
    case = tmp_path / "bad.json"
    case.write_text(contents, encoding="utf-8")
    rc = buster_cli.main([str(_tree(tmp_path)), *QUIET, "--casefile", str(case)])
    out, err = capsys.readouterr()
    assert rc == buster_cli.EXIT_USAGE == 2
    assert f"case file {case} could not be read" in err
    assert "Traceback" not in err and "internal error" not in err
    assert out == ""


def test_under_json_it_is_the_error_envelope_on_stdout(tmp_path, capsys):
    case = tmp_path / "bad.json"
    case.write_text('{"cases": [', encoding="utf-8")
    rc = buster_cli.main([str(_tree(tmp_path)), *QUIET, "--json", "--casefile", str(case)])
    out, err = capsys.readouterr()
    payload = json.loads(out)
    assert rc == 2
    assert payload["status"] == "error" and payload["exit_code"] == 2
    assert payload["error"]["kind"] == "usage" and "could not be read" in payload["error"]["message"]
    assert payload["findings"] == []
    assert "Traceback" not in err


def test_a_bad_case_file_found_in_the_scanned_folder_is_refused_the_same_way(tmp_path, capsys):
    root = _tree(tmp_path)
    (root / ".ghost_casefile.json").write_text("{", encoding="utf-8")
    assert buster_cli.main([str(root), *QUIET]) == 2
    assert "could not be read" in capsys.readouterr().err


def test_it_is_refused_before_the_scan_does_any_work(tmp_path, monkeypatch):
    case = tmp_path / "bad.json"
    case.write_text("{", encoding="utf-8")

    def scanned(*_a, **_k):
        raise AssertionError("the scan started")

    monkeypatch.setattr(buster_cli, "gather", scanned)
    assert buster_cli.main([str(_tree(tmp_path)), *QUIET, "--casefile", str(case)]) == 2


def test_priors_mode_refuses_it_too(tmp_path, capsys):
    case = tmp_path / "bad.json"
    case.write_text("{", encoding="utf-8")
    rc = buster_cli.main([str(_tree(tmp_path)), "--priors", "--casefile", str(case)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "could not be read" in err and "Traceback" not in err


def test_a_missing_or_valid_case_file_is_unchanged(tmp_path):
    root = _tree(tmp_path)
    assert buster_cli.main([str(root), *QUIET, "--casefile", str(tmp_path / "absent.json")]) in (0, 1)
    good = tmp_path / "good.json"
    good.write_text('{"cases": []}', encoding="utf-8")
    assert buster_cli.main([str(root), *QUIET, "--casefile", str(good)]) in (0, 1)


def test_casefile_raises_a_value_error_subclass_naming_the_file(tmp_path):
    case = tmp_path / "bad.json"
    case.write_text("{", encoding="utf-8")
    with pytest.raises(CasefileError, match="bad.json") as caught:
        Casefile(case)
    assert isinstance(caught.value, ValueError)


def test_triage_refuses_an_unreadable_case_file_and_leaves_the_findings_alone(tmp_path, capsys):
    finding = Finding(detector="dead_code", category=Category.DEAD_CODE, layer=Layer.MECHANICAL,
                      severity=Severity.MAJOR, status=Status.CONFIRMED, summary="one",
                      evidence=Evidence(file="a.py", line_start=3))
    findings = tmp_path / "findings.json"
    findings.write_text(FindingSet([finding]).to_json(), encoding="utf-8")
    case = tmp_path / "bad.json"
    case.write_text("{", encoding="utf-8")
    before = findings.read_text(encoding="utf-8")
    rc = triage.main([str(findings), "--set", f"{finding.id}=fix:why", "--casefile", str(case)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "could not be read" in err and "Traceback" not in err
    assert findings.read_text(encoding="utf-8") == before
