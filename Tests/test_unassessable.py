"""A file nobody could read must not read as a file that was read.

WHERE THIS CAME FROM

observe-perceive is a pediatric deterioration engine. Its BayesianFusion
carries this comment, written after a real defect:

    An engine that returns abstained=True is saying "I have no data to
    assess this patient" -- which is fundamentally different from "this
    patient looks stable." Previously, three low-confidence abstentions
    could outvote a single high-confidence septic-shock detection.

ghost_buster had the same bug wearing different clothes. `_parse` returns
None for a file it cannot read; every AST detector skips that file; the
run says nothing. Measured 2026-09-10 on three files -- one clean, one
with conflict markers, one with a syntax typo -- the typo file produced
no findings at all, its dead function invisible, while the header still
reported "scanning 3 file(s)".

The clinical fix was to make abstention explicit and refuse to let it
count as a verdict. This is the same fix in a static analyser.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ghost_buster.mechanical import detect_unassessable_file, run_all

CLEAN = "def used():\n    return used\n"
TYPO = "def broken(:\n    return 1\n"
CONFLICT = "def f():\n<<<<<<< HEAD\n    return 1\n=======\n    return 2\n>>>>>>> other\n"


def _write(tmp_path, name, text, *, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


def test_a_syntax_error_is_reported_rather_than_skipped(tmp_path):
    p = _write(tmp_path, "typo.py", TYPO)
    findings = detect_unassessable_file([p])
    assert len(findings) == 1
    assert "SyntaxError" in findings[0].attributes["reason"]


def test_the_reason_names_the_line(tmp_path):
    """"Could not parse" is not actionable. "Line 1" is."""
    p = _write(tmp_path, "typo.py", TYPO)
    assert "line 1" in detect_unassessable_file([p])[0].attributes["reason"]


def test_a_file_that_is_not_valid_utf8_is_reported(tmp_path):
    p = tmp_path / "bytes.py"
    p.write_bytes(b"def f():\n    return '\xff\xfe not utf-8'\n")
    findings = detect_unassessable_file([p])
    assert len(findings) == 1
    assert "UnicodeDecodeError" in findings[0].attributes["reason"]


def test_a_readable_file_is_not_reported(tmp_path):
    assert detect_unassessable_file([_write(tmp_path, "clean.py", CLEAN)]) == []


def test_markdown_is_not_reported(tmp_path):
    """Only .py files are handed to the AST detectors, so only .py files
    can be silently skipped by them. Flagging prose would be noise.

    The body has to be prose that genuinely will not parse as Python. The
    first draft of this test used "# not python", which is a valid Python
    comment, so it passed whether the extension filter was there or not --
    a vacuous test caught by the mutant that removes the filter. Exactly
    the kind of thing --mutate exists to find, found in this project's own
    suite.
    """
    prose = "# Title\n\nThis is prose, and prose is not Python source.\n"
    assert detect_unassessable_file([_write(tmp_path, "README.md", prose)]) == []


def test_the_abstention_is_major(tmp_path):
    """Silent exclusion from every structural check is not a nit. A file
    that will not parse is usually broken right now, which is the worst
    possible moment for every check to look away."""
    from ghost_buster.schema import Severity
    p = _write(tmp_path, "typo.py", TYPO)
    assert detect_unassessable_file([p])[0].severity == Severity.MAJOR


def test_conflict_markers_produce_both_findings(tmp_path):
    """The two detectors say different things and both are needed. The
    marker detector reads raw text and says WHAT is wrong; the abstention
    says every other check consequently looked away."""
    p = _write(tmp_path, "conflict.py", CONFLICT)
    detectors = {f.detector for f in run_all([p])}
    assert "merge_conflict_marker" in detectors
    assert "unassessable_file" in detectors


def test_the_defect_this_detector_exists_for(tmp_path):
    """The regression test proper: a dead function inside an unparseable
    file. `dead_code` cannot see it and never will -- that is correct,
    it fails closed. What must never happen again is the run being SILENT
    about having looked away."""
    broken = _write(tmp_path, "broken.py", "def never_referenced_anywhere(:\n    return 1\n")
    clean = _write(tmp_path, "clean.py", CLEAN)

    findings = run_all([broken, clean])
    by_detector = {f.detector for f in findings}

    assert "dead_code" not in {
        f.detector for f in findings if f.evidence.file.endswith("broken.py")
    }, "dead_code cannot parse it; failing closed is correct"
    assert "unassessable_file" in by_detector, (
        "but the run must say so -- without this the output is identical "
        "to a file that was checked and found clean"
    )


@pytest.mark.parametrize("name", ["mechanical.py", "correlate.py", "ledger.py", "cli.py"])
def test_ghost_buster_can_read_its_own_source(name):
    """If this ever fails, some detector has been silently skipping part of
    this project and reporting a clean scan."""
    src = Path(__file__).resolve().parent.parent / "ghost_buster" / name
    assert detect_unassessable_file([src]) == []
