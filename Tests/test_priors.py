"""--priors: what the team decided about each kind of finding, and whether
the decision held (ghost_buster/priors.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ghost_buster.casefile import Case, Casefile
from ghost_buster.ledger import FindingHistory, Ledger
from ghost_buster.priors import HELD, OPEN, RETURNED, REVISITED, UNKNOWN, build, render, to_json
from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status


def _t(days: int) -> str:
    return (datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=days)).isoformat()


def _casefile(tmp_path: Path, cases) -> Casefile:
    cf = Casefile(tmp_path / "cases.json")
    cf.cases = list(cases)
    return cf


def _ledger(tmp_path: Path, histories: dict) -> Ledger:
    led = Ledger(tmp_path / "ledger.json")
    led.findings = {fid: FindingHistory(finding_id=fid, **h) for fid, h in histories.items()}
    return led


def test_a_fix_whose_finding_is_gone_held(tmp_path):
    cf = _casefile(tmp_path, [Case("dead_code", "dead_code", "real", "unused", _t(1), "ghost-1", "a.py", "fix")])
    led = _ledger(tmp_path, {"ghost-1": {"last_seen": _t(0), "absent_last_run": True, "returns": 0}})
    [row] = build(cf, led)
    assert row.verdicts == {HELD: 1} and row.hold_rate == 1.0


def test_a_fix_whose_finding_is_still_there_is_open(tmp_path):
    cf = _casefile(tmp_path, [Case("dead_code", "dead_code", "real", "unused", _t(1), "ghost-1", "a.py", "fix")])
    led = _ledger(tmp_path, {"ghost-1": {"last_seen": _t(5), "absent_last_run": False, "returns": 0}})
    [row] = build(cf, led)
    assert row.verdicts == {OPEN: 1} and row.hold_rate == 0.0


def test_a_fix_the_ledger_has_not_run_since_is_open_not_held(tmp_path):
    """Last seen before the decision, and not recorded absent: nothing has
    looked since, so nothing says it is gone."""
    cf = _casefile(tmp_path, [Case("dead_code", "dead_code", "real", "unused", _t(1), "ghost-1", "a.py", "fix")])
    led = _ledger(tmp_path, {"ghost-1": {"last_seen": _t(0), "absent_last_run": False, "returns": 0}})
    [row] = build(cf, led)
    assert row.verdicts == {OPEN: 1}


def test_a_fix_whose_finding_came_back_returned(tmp_path):
    cf = _casefile(tmp_path, [Case("dead_code", "dead_code", "real", "unused", _t(1), "ghost-1", "a.py", "fix")])
    led = _ledger(tmp_path, {"ghost-1": {"last_seen": _t(9), "absent_last_run": False, "returns": 1}})
    [row] = build(cf, led)
    assert row.verdicts == {RETURNED: 1}


def test_a_suppression_holds_until_somebody_says_otherwise(tmp_path):
    cf = _casefile(tmp_path, [
        Case("long_function", "long_function", "false", "argparse table", _t(1), "ghost-2", "cli.py", "suppress"),
        Case("long_function", "long_function", "false", "the pipeline", _t(1), "ghost-3", "cli.py", "suppress"),
        Case("long_function", "long_function", "real", "actually split it", _t(4), "ghost-3", "cli.py", "fix"),
    ])
    [row] = build(cf, None)
    assert row.verdicts[HELD] == 1 and row.verdicts[REVISITED] == 1
    assert row.verdicts[UNKNOWN] == 1        # the later fix has no ledger to be judged against
    assert row.false_rate == 2 / 3


def test_a_case_without_a_finding_id_is_unknown_never_held(tmp_path):
    cf = _casefile(tmp_path, [Case("dead_code", "dead_code", "real", "old style", _t(1))])
    [row] = build(cf, _ledger(tmp_path, {}))
    assert row.verdicts == {UNKNOWN: 1} and row.hold_rate is None


def test_operations_are_counted_beside_decisions(tmp_path):
    cf = _casefile(tmp_path, [
        Case("name_disagreement", "name_disagreement", "healed", "by annotate", _t(2), "ghost-4", "x.py"),
        Case("name_disagreement", "name_disagreement", "real", "renamed", _t(1), "ghost-5", "x.py", "fix"),
    ])
    [row] = build(cf, None)
    assert row.outcomes == {"healed": 1, "real": 1} and row.decided == 1
    text = render([row], "cases.json", None)
    assert "operations: 1 healed" in text and "no ledger" in text
    assert "- by annotate" in text and "- renamed" in text


def test_rows_are_ordered_by_decisions_and_notes_are_the_latest_three(tmp_path):
    cases = [Case("a", "a", "real", f"reason {i}", _t(i), f"ghost-a{i}", "a.py", "document") for i in range(5)]
    cases.append(Case("b", "b", "false", "one", _t(1), "ghost-b", "b.py", "suppress"))
    rows = build(_casefile(tmp_path, cases), None)
    assert [r.detector for r in rows] == ["a", "b"]
    assert rows[0].notes == ["reason 4", "reason 3", "reason 2"]
    assert rows[0].verdicts == {HELD: 5}


def test_json_carries_the_same_numbers(tmp_path):
    cf = _casefile(tmp_path, [Case("dead_code", "dead_code", "real", "unused", _t(1), "ghost-1", "a.py", "fix")])
    led = _ledger(tmp_path, {"ghost-1": {"last_seen": _t(0), "absent_last_run": True, "returns": 0}})
    data = json.loads(to_json(build(cf, led)))
    assert data[0]["detector"] == "dead_code" and data[0]["verdicts"] == {HELD: 1} and data[0]["hold_rate"] == 1.0


def test_triage_records_which_finding_and_which_word(tmp_path):
    f = Finding(detector="dead_code", category=Category.DEAD_CODE, layer=Layer.MECHANICAL,
                severity=Severity.MINOR, status=Status.CONFIRMED, summary="a.py: unused",
                detail="", evidence=Evidence(file="a.py", line_start=1), disposition="document",
                disposition_note="kept for the plugin")
    cf = Casefile(tmp_path / "c.json")
    assert cf.record_dispositions([f]) == 1
    case = cf.cases[0]
    assert case.finding_id == f.id and case.file == "a.py" and case.decision == "document"
    cf.save()
    again = Casefile(tmp_path / "c.json")
    assert again.cases[0].decision == "document"


def test_an_old_case_file_still_loads(tmp_path):
    (tmp_path / "old.json").write_text(json.dumps({"cases": [
        {"detector": "dead_code", "shape": "dead_code", "outcome": "false", "note": "", "when": _t(1)}]}))
    cf = Casefile(tmp_path / "old.json")
    assert cf.cases[0].finding_id == "" and cf.cases[0].decision == ""
    [row] = build(cf, None)
    assert row.verdicts == {UNKNOWN: 1}


def test_the_cli_prints_the_view_and_scans_nothing(tmp_path, capsys):
    from ghost_buster.cli import main
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def unused():\n    pass\n")
    cf = Casefile(repo / ".ghost_casefile.json")
    cf.cases = [Case("dead_code", "dead_code", "false", "plugin hook", _t(1), "ghost-9", "m.py", "suppress")]
    cf.save()
    rc = main([str(repo), "--priors"])
    out, err = capsys.readouterr()
    assert rc == 0
    assert "dead_code: 1 decision(s), 100% false, 100% held" in out
    assert "- plugin hook" in out
    assert "scanning" not in err
    rc = main([str(repo), "--priors", "--json"])
    out, _ = capsys.readouterr()
    assert json.loads(out)[0]["verdicts"] == {HELD: 1}
