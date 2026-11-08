"""A baseline found in the scanned folder hides findings; the report says so.

Red team: a `.ghost_baseline.json` planted in (or left in) the folder being
scanned silently removed findings from the output. The envelope now carries
`baseline: {path, suppressed}`, and hidden findings from a baseline the user did
not name with --baseline make the scan "incomplete".
"""
from __future__ import annotations

import json

from ghost_buster import cli as buster_cli

BASE = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
        "--no-correlate", "--no-structure", "--single-repo", "--json"]


def _tree(tmp_path):
    root = tmp_path / "tgt"
    root.mkdir()
    (root / "m.py").write_text("def orphan_one():\n    return 1\n\ndef orphan_two():\n    return 2\n")
    return root


def _run(args, capsys):
    rc = buster_cli.main(args)
    out, err = capsys.readouterr()
    return rc, json.loads(out), err


def _accepted(root, capsys, where=None):
    args = [str(root), *BASE, "--accept"]
    if where:
        args += ["--baseline", str(where)]
    buster_cli.main(args)
    capsys.readouterr()


def test_no_baseline_means_null_path_and_nothing_suppressed(tmp_path, capsys):
    rc, env, _ = _run([str(_tree(tmp_path)), *BASE], capsys)
    assert env["baseline"] == {"path": None, "suppressed": 0}
    assert not any(u["check"] == "baseline" for u in env["unmeasured"])


def test_a_baseline_in_the_folder_is_reported_and_makes_the_scan_incomplete(tmp_path, capsys):
    root = _tree(tmp_path)
    _accepted(root, capsys)
    rc, env, err = _run([str(root), *BASE], capsys)
    assert env["baseline"]["suppressed"] == 2
    assert env["baseline"]["path"].endswith(".ghost_baseline.json")
    assert env["findings"] == []
    row = next(u for u in env["unmeasured"] if u["check"] == "baseline")
    assert row["by_request"] is False and "2 finding(s)" in row["reason"]
    assert env["status"] == "incomplete"


def test_a_baseline_named_on_the_command_line_is_reported_but_not_a_gap(tmp_path, capsys):
    root = _tree(tmp_path)
    chosen = tmp_path / "mine.json"
    _accepted(root, capsys, where=chosen)
    rc, env, _ = _run([str(root), *BASE, "--baseline", str(chosen)], capsys)
    assert env["baseline"] == {"path": str(chosen), "suppressed": 2}
    assert not any(u["check"] == "baseline" for u in env["unmeasured"])
    assert env["status"] == "ok"


def test_the_human_report_warns_when_an_unnamed_baseline_hid_findings(tmp_path, capsys):
    root = _tree(tmp_path)
    _accepted(root, capsys)
    buster_cli.main([str(root), *[a for a in BASE if a != "--json"]])
    err = capsys.readouterr().err
    assert "hidden by" in err and "--baseline" in err


def test_error_envelopes_carry_the_baseline_key(tmp_path, capsys):
    buster_cli.main([str(tmp_path / "nope"), "--json"])
    env = json.loads(capsys.readouterr().out)
    assert env["status"] == "error" and env["baseline"] == {"path": None, "suppressed": 0}
