"""Baseline integrity: attacks on the evidence infrastructure that passed
on 2026-09-08.

1. A baseline written at one path matched nothing at another: 137 of 137
   entries in a committed baseline were inert and nothing said so.
2. A checkout under a directory named venv scanned nothing and reported
   "0 new finding(s)", exit 0.
3. An entry accepted as MINOR suppressed the same finding once CRITICAL.
4. A corrupt baseline exited 1, the same status as a MAJOR finding.
5. `--accept --json` handed the pipeline a prose line instead of JSON.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from ghost_buster.baseline import Baseline
from ghost_buster.cli import main
from ghost_buster.schema import Category, Evidence, Finding, FindingSet, Layer, Severity, Status

DEAD = '''
def used():
    return 1

def never_called_anywhere():
    return 2
'''


def _checkout(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "mod.py").write_text(textwrap.dedent(DEAD))
    (root / "README.md").write_text("# proj\n\nNothing here calls never_called_anywhere.\n")
    return root


def _finding(summary, severity=Severity.MAJOR, file="src/pkg/mod.py"):
    return Finding(detector="d", category=Category.DEAD_CODE, layer=Layer.MECHANICAL, severity=severity,
                   status=Status.CONFIRMED, summary=summary, evidence=Evidence(file=file, line_start=3))


# ---------------------------------------------------------------- 1. portability

def test_a_baseline_written_at_one_path_applies_at_another(tmp_path, capsys):
    a = _checkout(tmp_path / "ci-runner-1" / "proj")
    assert main([str(a), "--accept"]) == 0
    baseline = a / ".ghost_baseline.json"
    stored = json.loads(baseline.read_text())
    assert stored, "the fixture must produce at least one finding"
    assert all(not Path(f["evidence"]["file"]).is_absolute() for f in stored), "stored paths are project-relative"
    # A fresh clone elsewhere, three segments deep and at the root.
    b = _checkout(tmp_path / "laptop" / "work" / "proj")
    (b / ".ghost_baseline.json").write_text(baseline.read_text())
    rc = main([str(b)])
    out = capsys.readouterr()
    assert rc == 0, out.out
    assert f"0 new finding(s), {len(stored)} already in baseline" in out.out
    assert "matched nothing" not in out.err


def test_a_stale_baseline_is_reported_not_silent(tmp_path, capsys):
    root = _checkout(tmp_path / "proj")
    inert = FindingSet([_finding("something that no longer occurs", file="src/pkg/gone.py")])
    (root / ".ghost_baseline.json").write_text(inert.to_json())
    main([str(root)])
    err = capsys.readouterr().err
    assert "1 of 1 baseline entries matched nothing scanned" in err


def test_stored_absolute_paths_from_an_old_baseline_are_read_back_portably(tmp_path):
    # An entry whose absolute path exists on this machine recomputes to the
    # project-relative form; one whose path does not exist keeps its
    # two-segment fallback and is reported stale rather than silently inert.
    root = _checkout(tmp_path / "proj")
    live = Finding.from_dict({**_finding("x").as_dict(), "evidence": {"file": str(root / "src" / "pkg" / "mod.py"), "line_start": 3}})
    assert live.evidence.file == "src/pkg/mod.py" and live.evidence.absolute_file == str(root / "src" / "pkg" / "mod.py")
    assert live.id == _finding("x").id


# ---------------------------------------------------------------- 2. nothing scanned

def test_scanning_nothing_is_an_error_not_a_clean_run(tmp_path, capsys):
    root = tmp_path / "venv" / "proj"
    _checkout(root)
    rc = main([str(root)])
    err = capsys.readouterr().err
    assert rc == 2 and "no .py or .md files to scan" in err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main([str(empty), "--json"]) == 2


def test_the_file_count_is_reported(tmp_path, capsys):
    root = _checkout(tmp_path / "proj")
    main([str(root)])
    assert "scanning 2 file(s)" in capsys.readouterr().err


# ---------------------------------------------------------------- 3. escalation

def test_an_accepted_minor_does_not_suppress_the_same_finding_once_critical(tmp_path):
    path = tmp_path / "b.json"
    b = Baseline(path)
    b.accept([_finding("s", Severity.MINOR)])
    b = Baseline(path)
    new, known = b.diff([_finding("s", Severity.CRITICAL)])
    assert len(new) == 1 and known == [] and "ESCALATED since baseline" in new[0].detail
    new, known = b.diff([_finding("s", Severity.MINOR)])
    assert new == [] and len(known) == 1


# ---------------------------------------------------------------- 4/5. exit codes and JSON

def test_a_corrupt_baseline_is_a_usage_error(tmp_path, capsys):
    root = _checkout(tmp_path / "proj")
    (root / ".ghost_baseline.json").write_text("{not json")
    assert main([str(root)]) == 2
    assert "could not be read" in capsys.readouterr().err
    assert main([str(root), "--baseline", str(root / "src")]) == 2


def test_accept_with_json_emits_json_on_stdout(tmp_path, capsys):
    root = _checkout(tmp_path / "proj")
    assert main([str(root), "--accept", "--json"]) == 0
    out = capsys.readouterr()
    accepted = json.loads(out.out)
    assert isinstance(accepted, list) and accepted
    assert "accepted" in out.err
