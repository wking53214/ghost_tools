"""A detector that starts stating its identity keeps the old id as a previous id.

Moving a detector from "the summary is the identity" to "this key is the identity" changes
every id it makes. A baseline written before the change must keep suppressing the same
finding, so the id the summary used to produce stays a previous id. It is opt-in: a
detector that does not name `previous_key` is unchanged.
"""
from __future__ import annotations

from ghost_buster.baseline import Baseline
from ghost_buster.schema import (Category, Evidence, Finding, FindingSet, Layer, Severity,
                                 Status)

SUMMARY = "'run' spans 200 lines (threshold 80)"


def _finding(summary=SUMMARY, **kw):
    return Finding(
        detector="long_function", category=Category.COMPLEXITY, layer=Layer.MECHANICAL,
        severity=Severity.MINOR, status=Status.CONFIRMED, summary=summary, detail="",
        evidence=Evidence(file="pkg/mod.py", line_start=1, line_end=2), **kw)


def test_without_previous_key_nothing_changes():
    assert _finding(identity_key="'run' is long").previous_ids == []
    assert _finding().previous_ids == []


def test_the_summary_id_stays_a_previous_id():
    old = _finding()
    new = _finding(identity_key="'run' is long", previous_key=SUMMARY)
    assert new.id != old.id
    assert new.previous_ids == [old.id]


def test_a_previous_key_equal_to_the_key_adds_nothing():
    assert _finding(identity_key=SUMMARY, previous_key=SUMMARY).previous_ids == []


def test_the_new_id_does_not_move_with_the_measurement():
    a = _finding("'run' spans 200 lines (threshold 80)", identity_key="'run' is long",
                 previous_key="'run' spans 200 lines (threshold 80)")
    b = _finding("'run' spans 201 lines (threshold 80)", identity_key="'run' is long",
                 previous_key="'run' spans 201 lines (threshold 80)")
    assert a.id == b.id


def test_a_baseline_written_before_the_change_still_matches(tmp_path):
    path = tmp_path / "baseline.json"
    fs = FindingSet()
    old = _finding()
    old.status = Status.SUPPRESSED
    fs.add(old)
    path.write_text(fs.to_json(), encoding="utf-8")
    new, known = Baseline(path).diff([_finding(identity_key="'run' is long", previous_key=SUMMARY)])
    assert new == [] and len(known) == 1


def test_a_stale_check_does_not_call_the_matched_entry_stale(tmp_path):
    path = tmp_path / "baseline.json"
    fs = FindingSet()
    fs.add(_finding())
    path.write_text(fs.to_json(), encoding="utf-8")
    assert Baseline(path).stale([_finding(identity_key="'run' is long", previous_key=SUMMARY)]) == []
