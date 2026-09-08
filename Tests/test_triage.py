"""test_triage.py -- the triage step and the triage report, end to end through
the CLIs: ghost_buster --json -> ghost_triage --set -> ghost_writer --mode.
"""
from __future__ import annotations

import json

import pytest

from ghost_buster.schema import Category, Evidence, Finding, FindingSet, Layer, Severity, Status
from ghost_writer.cli import main as writer_main
from ghost_writer.report import render_triage_report
from ghost_writer.triage import apply_dispositions, main as triage_main, pending


def _finding(summary, severity=Severity.MAJOR, detector="dead_code", category=Category.DEAD_CODE, detail="", file="a.py", line=3):
    return Finding(detector=detector, category=category, layer=Layer.MECHANICAL, severity=severity,
                   status=Status.CONFIRMED, summary=summary, detail=detail,
                   evidence=Evidence(file=file, line_start=line))


def test_apply_dispositions_by_full_id_and_unique_prefix():
    a, b = _finding("one"), _finding("two")
    apply_dispositions([a, b], [(a.id, "fix", "real bug"), (b.id[:9], "document", "by design")])
    assert (a.disposition, a.disposition_note) == ("fix", "real bug")
    assert (b.disposition, b.disposition_note) == ("document", "by design")


def test_unknown_id_and_unknown_disposition_are_errors_not_silent():
    a = _finding("one")
    with pytest.raises(ValueError, match="no finding matches"):
        apply_dispositions([a], [("ghost-nope", "fix", "")])
    with pytest.raises(ValueError, match="unknown disposition"):
        apply_dispositions([a], [(a.id, "ignore", "")])
    assert a.disposition is None


def test_ambiguous_prefix_is_refused():
    a, b = _finding("one"), _finding("two")
    with pytest.raises(ValueError, match="ambiguous"):
        apply_dispositions([a, b], [("ghost-", "fix", "")])


def test_pending_is_the_undecided_set():
    a, b = _finding("one"), _finding("two")
    apply_dispositions([a, b], [(a.id, "suppress", "")])
    assert pending([a, b]) == [b]


def test_cli_round_trip_records_decisions_in_the_file(tmp_path, capsys):
    a, b = _finding("one"), _finding("two")
    path = tmp_path / "findings.json"
    path.write_text(FindingSet([a, b]).to_json(), encoding="utf-8")
    assert triage_main([str(path), "--set", f"{a.id}=document:kept on purpose"]) == 0
    stored = FindingSet.from_json(path.read_text(encoding="utf-8"))
    decided = {f.id: (f.disposition, f.disposition_note) for f in stored}
    assert decided[a.id] == ("document", "kept on purpose") and decided[b.id] == (None, "")
    assert triage_main([str(path), "--list"]) == 0
    assert "1 of 2 finding(s) awaiting" in capsys.readouterr().out


def test_cli_rejects_a_bad_id_without_writing(tmp_path, capsys):
    a = _finding("one")
    path = tmp_path / "findings.json"
    original = FindingSet([a]).to_json()
    path.write_text(original, encoding="utf-8")
    assert triage_main([str(path), "--set", "ghost-nope=fix"]) == 2
    assert path.read_text(encoding="utf-8") == original


def test_triage_report_lists_everything_most_severe_first_with_proof():
    critical = _finding("'test_x' never runs its guarded assertions", Severity.CRITICAL, "vacuous_check",
                        Category.VACUOUS_CHECK, detail="shape: guarded_assertion. mutation: guard instrumented.", file="test_x.py", line=10)
    minor = _finding("long function", Severity.MINOR, "long_function", Category.COMPLEXITY, file="b.py", line=1)
    decided = _finding("dup", Severity.MAJOR, "near_duplicate_function", Category.DUPLICATION, file="c.py")
    decided.disposition, decided.disposition_note = "suppress", "known"
    text = render_triage_report([minor, critical, decided])
    assert "NOT been reviewed" in text
    assert text.index("test_x.py") < text.index("b.py")
    assert "*Proof:* shape: guarded_assertion" in text
    assert "| critical | 1 |" in text and "| vacuous_check | 1 |" in text
    assert "Already decided" in text and "`suppress` dup" in text
    assert "2 open**, 1 decided" in text


def test_writer_cli_document_mode_still_gates_and_triage_mode_does_not(tmp_path, capsys):
    a = _finding("undecided one")
    path = tmp_path / "findings.json"
    path.write_text(FindingSet([a]).to_json(), encoding="utf-8")
    assert writer_main([str(path)]) == 0
    assert "None currently dispositioned" in capsys.readouterr().out
    assert writer_main([str(path), "--mode", "triage"]) == 0
    out = capsys.readouterr().out
    assert "undecided one" in out and "NOT been reviewed" in out


def test_pipeline_json_survives_the_round_trip_unchanged_apart_from_dispositions(tmp_path):
    a = _finding("one", detail="d")
    path = tmp_path / "f.json"
    path.write_text(FindingSet([a]).to_json(), encoding="utf-8")
    before = json.loads(path.read_text())
    triage_main([str(path), "--set", f"{a.id}=fix:bug"])
    after = json.loads(path.read_text())
    before[0].update({"disposition": "fix", "disposition_note": "bug"})
    assert before == after
