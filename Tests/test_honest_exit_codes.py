"""A Ghost crash must not look like "findings were found".

The red team's case: an unhandled error inside ghost_buster ended the
process with Python's default exit status 1, the same number that means
"the scan ran and found something". A caller that only checks the exit code
(a CI step, a gate) read a dead tool as a repository with findings.

Exit codes: 0 clean, 1 findings, 2 did not start (usage), 3 crashed.
"""
from __future__ import annotations

import json

import pytest

from ghost_buster import cli as buster_cli

QUIET = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
         "--no-correlate", "--no-ledger", "--no-structure", "--single-repo"]


def _tree(tmp_path, body="def used():\n    return 1\n"):
    root = tmp_path / "tgt"
    root.mkdir()
    (root / "m.py").write_text(body, encoding="utf-8")
    return root


def _boom(*_a, **_k):
    raise RuntimeError("boom")


def test_the_four_outcomes_have_four_different_codes():
    codes = {buster_cli.EXIT_CLEAN, buster_cli.EXIT_FINDINGS,
             buster_cli.EXIT_USAGE, buster_cli.EXIT_CRASH}
    assert codes == {0, 1, 2, 3}


def test_a_crash_exits_with_the_crash_code_and_says_why_on_stderr(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(buster_cli, "gather", _boom)
    rc = buster_cli.main([str(_tree(tmp_path)), *QUIET])
    out, err = capsys.readouterr()
    assert rc == buster_cli.EXIT_CRASH != buster_cli.EXIT_FINDINGS
    assert "internal error" in err and "RuntimeError: boom" in err
    assert out == ""


def test_a_crash_under_json_still_leaves_valid_json_with_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(buster_cli, "gather", _boom)
    rc = buster_cli.main([str(_tree(tmp_path)), *QUIET, "--json"])
    out, err = capsys.readouterr()
    payload = json.loads(out)
    assert rc == 3
    assert payload["status"] == "error" and payload["exit_code"] == 3
    assert payload["error"]["kind"] == "crash" and "boom" in payload["error"]["message"]
    assert payload["findings"] == []
    assert "boom" in err


def test_findings_still_exit_1_and_a_clean_scan_still_exits_0(tmp_path, capsys):
    broken = _tree(tmp_path, "def (:\n")             # unparsable file: a MAJOR finding
    assert buster_cli.main([str(broken), *QUIET]) == 1
    capsys.readouterr()
    (broken / "m.py").write_text("X = 1\n", encoding="utf-8")
    assert buster_cli.main([str(broken), *QUIET]) == 0


def test_a_missing_target_exits_2_with_a_reason_and_json(tmp_path, capsys):
    rc = buster_cli.main([str(tmp_path / "nope"), *QUIET, "--json"])
    out, err = capsys.readouterr()
    payload = json.loads(out)
    assert rc == 2 and payload["status"] == "error" and payload["error"]["kind"] == "usage"
    assert "not a directory" in err


def test_bad_arguments_exit_2_and_json_mode_still_prints_json(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        buster_cli.main([str(tmp_path), "--no-such-flag", "--json"])
    out, err = capsys.readouterr()
    assert stop.value.code == 2
    payload = json.loads(out)
    assert payload["status"] == "error" and "no-such-flag" in payload["error"]["message"]
    assert "unrecognized arguments" in err


def test_an_empty_target_is_a_usage_error_not_a_clean_scan(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert buster_cli.main([str(empty), *QUIET, "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"
