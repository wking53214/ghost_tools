"""Direction, surprise, and the three things it refuses to assess."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ghost_buster.ledger import RunRecord
from ghost_buster.trajectory import (
    SURPRISE_Z, WARMUP_RUNS, adverse_rate_for, assess, comparable, derive, render_report,
)

BASE = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
FULL = {"mechanical": "ran", "tests": "ran", "secrets": "ran"}
NO_TESTS = {"mechanical": "ran", "tests": "declined", "secrets": "ran"}


def _run(i, found, scanned=500, checks=None, at=None):
    moment = at or (BASE + timedelta(days=i))
    return RunRecord(
        run_id=f"r{i}", at=moment.isoformat(), commit=f"c{i}", tool_version="0.0.0",
        checks=dict(checks if checks is not None else FULL),
        counts={"found": found, "scanned": scanned},
    )


def _series(counts, **kw):
    return [_run(i, n, **kw) for i, n in enumerate(counts)]


# ------------------------------------------------------- refusals

def test_no_runs_is_a_refusal_not_a_zero():
    result = assess([])
    assert not result.assessed and "no runs" in result.reason


def test_a_ledger_without_denominators_is_not_assessed():
    """Ledgers written before `scanned` existed have no density, and one
    cannot be invented for them."""
    runs = [RunRecord(f"r{i}", (BASE + timedelta(days=i)).isoformat(), f"c{i}", "0",
                      dict(FULL), {"found": 100 + i * 30}) for i in range(8)]
    result = assess(runs)
    assert not result.assessed
    assert result.comparable_runs == 0


def test_warmup_is_stated_rather_than_scored():
    result = assess(_series([100, 140]))
    assert not result.assessed
    assert f"need {WARMUP_RUNS}" in result.reason
    assert derive(_series([100, 140])) == []


def test_a_run_with_a_different_check_set_is_excluded():
    """--no-tests produces fewer findings with no change in quality. Folding
    it in would measure the flags, not the code."""
    runs = _series([100, 105, 110]) + [_run(3, 40, checks=NO_TESTS)]
    assert len(comparable(runs, frozenset(["mechanical", "secrets"]))) == 1
    # current run declined tests, so only same-shaped runs count: too few
    result = assess(runs)
    assert not result.assessed, "a --no-tests run must not be compared to full runs"


def test_the_receipt_line_says_when_it_cannot_see():
    line = render_report(_series([100, 140]))
    assert "not yet assessable" in line


# ------------------------------------------------------- direction

def test_steady_density_is_flat_and_silent():
    runs = _series([100, 100, 101, 100, 100, 101])
    result = assess(runs)
    assert result.assessed
    assert abs(result.velocity) < adverse_rate_for(result.density)
    assert [f for f in derive(runs) if f.attributes["kind"] == "deteriorating_trend"] == []


def test_growth_at_constant_quality_is_not_decay():
    """THE TRAP THIS MODULE EXISTS TO AVOID. Findings and files double
    together: raw counts would scream, density is flat."""
    runs = [_run(i, 100 * (i + 1), scanned=500 * (i + 1)) for i in range(6)]
    result = assess(runs)
    assert result.assessed
    assert abs(result.velocity) < adverse_rate_for(result.density), (
        f"a project growing at constant quality was reported as trending "
        f"{result.velocity:+.4f}/run"
    )


def test_findings_outpacing_the_code_is_reported():
    runs = [_run(i, 100 + i * 25, scanned=500) for i in range(6)]
    findings = derive(runs)
    kinds = {f.attributes["kind"] for f in findings}
    assert "deteriorating_trend" in kinds
    trend = next(f for f in findings if f.attributes["kind"] == "deteriorating_trend")
    assert trend.severity.value == "minor"
    assert "per file per run" in trend.summary


def test_improvement_is_recorded_as_evidence_too():
    runs = [_run(i, 250 - i * 25, scanned=500) for i in range(6)]
    findings = derive(runs)
    kinds = {f.attributes["kind"] for f in findings}
    assert "improving_trend" in kinds
    good = next(f for f in findings if f.attributes["kind"] == "improving_trend")
    assert good.severity.value == "informational"


# ------------------------------------------------------- surprise

def test_a_jump_the_trend_did_not_predict_is_reported():
    runs = _series([100, 101, 100, 101, 100, 400])
    result = assess(runs)
    assert result.surprise_z >= SURPRISE_Z, result.surprise_z
    assert any(f.attributes["kind"] == "surprising_run" for f in derive(runs))


def test_a_smooth_series_is_not_surprising():
    runs = _series([100, 101, 102, 103, 104, 105])
    assert assess(runs).surprise_z < SURPRISE_Z


# ------------------------------------------------------- determinism

def test_identical_history_yields_identical_output():
    """A nondeterministic signal is exactly what flapping_finding exists to
    catch; this module must never become one."""
    counts = [100, 130, 150, 190, 210, 260]
    first = assess(_series(counts))
    second = assess(_series(counts))
    assert (first.velocity, first.surprise_z, first.density) == (
        second.velocity, second.surprise_z, second.density)


def test_findings_are_repository_level_not_attached_to_one_finding():
    runs = [_run(i, 100 + i * 25, scanned=500) for i in range(6)]
    for f in derive(runs, root_label="proj"):
        assert f.evidence.file == "proj"
        assert f.detector == "trajectory"


# ------------------------------------------------------- calibration

def test_ordinary_wobble_is_not_surprising_at_any_scale():
    """Dogfooded 2026-09-10: absolute noise constants tuned for a density
    near 0.1 collapsed on a two-file repository at density 5.5 and reported
    z=9.0 on a run where nothing meaningful had changed.

    A PERFECTLY CONSTANT series cannot catch this -- its innovation is zero
    whatever the calibration, which is why the first version of this test
    passed against the broken build. Real histories wobble by a finding or
    two, and the question is whether that wobble reads as noise or as news.
    """
    wobble = [0, 1, -1, 1, 0, -1, 1, 0]
    for base_found, scanned in ((11, 2), (100, 500), (30, 4000), (2000, 40)):
        runs = [_run(i, base_found + w, scanned=scanned) for i, w in enumerate(wobble)]
        result = assess(runs)
        assert result.assessed
        assert result.surprise_z < SURPRISE_Z, (
            f"density {base_found/scanned:.4f}: a one-finding wobble reported "
            f"z={result.surprise_z:.1f}"
        )
        assert abs(result.velocity) < adverse_rate_for(result.density), (
            f"density {base_found/scanned:.4f}: a one-finding wobble reported "
            f"a direction of {result.velocity:+.5f}/run"
        )
        assert derive(runs) == [], (
            f"density {base_found/scanned:.4f}: a one-finding wobble produced "
            f"{[f.attributes['kind'] for f in derive(runs)]}"
        )


def test_a_real_departure_is_still_caught_at_a_high_density():
    """Scale-free must not mean insensitive: the same relative jump is
    reported whether the density is 0.2 or 5.0."""
    small = _series([100, 101, 100, 101, 100, 300], scanned=500)
    large = [_run(i, n, scanned=2) for i, n in enumerate([10, 10, 10, 10, 10, 30])]
    assert assess(small).surprise_z >= SURPRISE_Z
    assert assess(large).surprise_z >= SURPRISE_Z
