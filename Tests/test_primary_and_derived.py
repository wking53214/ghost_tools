"""A statement about two findings is not a measurement of the tree.

The trajectory series is findings per file scanned. A correlation joins
two findings that were already counted, and a ledger or trajectory finding
is a statement about history, so counting them in that numerator counts
the same defect twice and makes adding a connector read as the code
getting worse. An external reviewer named this as a methodological
confounder; these tests are the boundary that answers it.

Both kinds are still reported. Only the tree's own findings are a
denominator.
"""
from __future__ import annotations

import ghost_buster.correlate as correlate
from ghost_buster.ledger import DETECTOR as LEDGER_DETECTOR, RAN, Ledger
from ghost_buster.schema import (
    DERIVED_DETECTORS, Category, Evidence, Finding, Layer, Severity, Status,
    derived, is_derived, primary,
)
from ghost_buster.trajectory import DETECTOR as TRAJECTORY_DETECTOR


def _finding(detector, file="src/mod.py", summary=None):
    return Finding(
        detector=detector, category=Category.DEAD_CODE, layer=Layer.MECHANICAL,
        severity=Severity.MAJOR, status=Status.CONFIRMED,
        summary=summary or f"a {detector} finding", detail="",
        evidence=Evidence(file=file),
    )


# ------------------------------------------------- the list cannot go stale

def test_the_derived_set_is_exactly_what_the_registries_produce():
    """The first draft of this set was wrong in both directions: it named
    detectors that do not exist and missed three that do. A hand-kept list
    of what the code does is the drift this project exists to find."""
    live = set(correlate.registered_connectors()) | {LEDGER_DETECTOR, TRAJECTORY_DETECTOR}
    assert DERIVED_DETECTORS == live, (
        f"missing: {sorted(live - DERIVED_DETECTORS)}; "
        f"named but not produced: {sorted(DERIVED_DETECTORS - live)}"
    )


def test_a_mechanical_detector_is_not_derived():
    assert not is_derived(_finding("dead_code"))
    assert is_derived(_finding("secret_in_duplicated_file"))


def test_the_two_halves_partition_the_findings():
    fs = [_finding("dead_code"), _finding("secret_in_duplicated_file"), _finding("long_function")]
    assert len(primary(fs)) + len(derived(fs)) == len(fs)
    assert [f.detector for f in primary(fs)] == ["dead_code", "long_function"]


# ----------------------------------------------------------- the ledger

def test_the_ledger_records_both_counts(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.record([_finding("dead_code"), _finding("long_function"),
                   _finding("secret_in_duplicated_file")],
                  checks={"tests": RAN}, commit="abc", tool_version="test", scanned=10)
    counts = ledger.runs[-1].counts
    assert counts["found"] == 3, "the run still reports everything the scan found"
    assert counts["primary"] == 2, "and separately what it measured about the tree"


# -------------------------------------------------------- the trajectory

def _runs(pairs):
    """One RunRecord per (primary, derived) pair, measured the same way."""
    from datetime import datetime, timedelta, timezone
    from ghost_buster.ledger import RunRecord
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    checks = {"tests": RAN, "secrets": RAN}
    out = []
    for i, (n_primary, n_derived) in enumerate(pairs):
        out.append(RunRecord(
            run_id=f"r{i}", at=(base + timedelta(days=i)).isoformat(),
            commit=f"c{i}", tool_version="test", checks=dict(checks),
            counts={"found": n_primary + n_derived, "primary": n_primary, "scanned": 500},
        ))
    return out


def test_adding_a_connector_does_not_look_like_deterioration():
    """Six runs of unchanged code; on the last one a new connector produces
    twenty correlations. Density is a measurement of the tree, so it must
    not move."""
    from ghost_buster.trajectory import assess
    steady = assess(_runs([(10, 0)] * 6))
    with_connector = assess(_runs([(10, 0)] * 5 + [(10, 20)]))
    assert steady.assessed and with_connector.assessed
    assert with_connector.density == steady.density
    assert with_connector.velocity == steady.velocity


def test_a_real_rise_in_the_tree_still_moves_the_series():
    """The control. If the test above passed because the series stopped
    reading anything, this fails."""
    from ghost_buster.trajectory import assess
    steady = assess(_runs([(10, 0)] * 6))
    worse = assess(_runs([(10, 0)] * 5 + [(40, 0)]))
    assert worse.density > steady.density


def test_an_old_run_without_the_primary_count_still_has_a_density():
    """Ledgers written before this release have only `found`. Dropping
    their points would rewrite history to make the new rule look tidy."""
    from ghost_buster.trajectory import assess
    runs = _runs([(10, 0)] * 6)
    for run in runs:
        del run.counts["primary"]
    assert assess(runs).assessed


def test_an_old_runs_derived_findings_are_still_in_its_denominator():
    """Honesty about the change: a pre-1.5.0 run counted correlations, and
    this cannot retroactively know how many. The old point keeps the number
    it was written with rather than being silently restated."""
    from ghost_buster.trajectory import assess
    old = _runs([(10, 20)] * 6)
    for run in old:
        del run.counts["primary"]
    assert assess(old).density > assess(_runs([(10, 20)] * 6)).density
