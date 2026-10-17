"""A detector that starts stating its identity keeps the old id as a previous id.

Moving a detector from "the summary is the identity" to "this key is the identity" changes
every id it makes. A baseline written before the change must keep suppressing the same
finding, so the id the summary used to produce stays a previous id. It is opt-in: a
detector that does not name `previous_key` is unchanged.
"""
from __future__ import annotations

import re

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


# ---------------------------------------------------------------------------
# Twins. A detector that now states one identity for findings that used to be
# told apart by their summaries produces several findings with one base id, and
# `disambiguate_ids` gives each a place suffix. The ids those summaries produced
# were plain, so the previous ids must stay plain. Measured on the committed
# baselines of 14 repositories: without this, 62 of 76 affected findings in one
# of them missed their own baseline entry.
# ---------------------------------------------------------------------------

from ghost_buster.schema import disambiguate_ids  # noqa: E402


def _at(line, summary, **kw):
    return Finding(
        detector="long_function", category=Category.COMPLEXITY, layer=Layer.MECHANICAL,
        severity=Severity.MINOR, status=Status.CONFIRMED, summary=summary,
        detail=f"pkg/mod.py:{line}",
        evidence=Evidence(file="pkg/mod.py", line_start=line, line_end=line + 1), **kw)


def _migrated(line, summary):
    return _at(line, summary, identity_key="'run' is long", previous_key=summary)


def test_twins_keep_the_plain_ids_their_summaries_used_to_make():
    old = [_at(10, "'run' spans 200 lines"), _at(40, "'run' spans 300 lines")]
    disambiguate_ids(old)
    new = [_migrated(10, "'run' spans 200 lines"), _migrated(40, "'run' spans 300 lines")]
    disambiguate_ids(new)
    assert new[0].id != new[1].id
    assert [f.previous_ids for f in new] == [[old[0].id], [old[1].id]]
    assert all(re.fullmatch(r"ghost-[0-9a-f]{12}", i) for f in new for i in f.previous_ids)


def test_twins_that_collided_before_keep_the_suffix_they_had():
    same = "'run' spans 200 lines"
    old = [_at(10, same), _at(40, same)]
    assert disambiguate_ids(old) == 2
    new = [_migrated(10, same), _migrated(40, same)]
    disambiguate_ids(new)
    assert [f.previous_ids for f in new] == [[old[0].id], [old[1].id]]


def test_a_baseline_with_plain_ids_still_matches_every_twin(tmp_path):
    old = [_at(10, "'run' spans 200 lines"), _at(40, "'run' spans 300 lines")]
    disambiguate_ids(old)
    path = tmp_path / "baseline.json"
    fs = FindingSet()
    for f in old:
        f.status = Status.SUPPRESSED
        fs.add(f)
    path.write_text(fs.to_json(), encoding="utf-8")
    new = [_migrated(10, "'run' spans 200 lines"), _migrated(40, "'run' spans 300 lines")]
    disambiguate_ids(new)
    fresh, known = Baseline(path).diff(new)
    assert fresh == [] and len(known) == 2
    assert Baseline(path).stale(new) == []


def test_disambiguating_twice_gives_the_same_previous_ids():
    new = [_migrated(10, "'run' spans 200 lines"), _migrated(40, "'run' spans 300 lines")]
    disambiguate_ids(new)
    first = [f.previous_ids for f in new]
    disambiguate_ids(new)
    assert [f.previous_ids for f in new] == first
