"""The proof that Tests/test_trajectory.py is not vacuous.

The dangerous failure for this module is not silence. It is a confident
number nobody should act on: a growing project reported as decaying, or a
run compared against a run measured a different way. Most mutants here
break a REFUSAL rather than a calculation, because the refusals are what
make the numbers trustworthy.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TRAJECTORY_TESTS = "Tests/test_trajectory.py"
_T = "ghost_buster/trajectory.py"

MUTANTS = [
    # --- the refusals ---
    ("runs measured with a different check set are folded in anyway", _T,
     "    return [r for r in runs\n            if _ran(r.checks) == signature and \"scanned\" in r.counts\n",
     "    return [r for r in runs\n            if \"scanned\" in r.counts\n"),
    ("a run with no denominator is treated as comparable", _T,
     '            if _ran(r.checks) == signature and "scanned" in r.counts\n            and r.counts.get("scanned", 0) > 0]\n',
     '            if _ran(r.checks) == signature]\n'),
    ("the filter scores before it has a trend to score against", _T,
     "    if len(series) < WARMUP_RUNS:\n",
     "    if len(series) < 0:\n"),

    # --- the density decision ---
    ("velocity is taken over raw counts instead of density", _T,
     '        density = run.counts["found"] / run.counts["scanned"]\n',
     '        density = float(run.counts["found"])\n'),

    # --- direction and surprise ---
    ("a rising trend stops being reported", _T,
     "    if result.velocity >= threshold:\n",
     "    if False:\n"),
    ("improvement stops being recorded as evidence", _T,
     "    elif result.velocity <= -threshold:\n",
     "    elif False:\n"),
    ("a surprising run is no longer surprising", _T,
     "    if result.surprise_z >= SURPRISE_Z:\n",
     "    if False:\n"),
    ("the rate estimate stops being driven by the cross term", _T,
     "        self.rate += k1 * innovation\n",
     "        self.rate += 0.0 * innovation\n"),

    # --- the calibration dogfooding exposed ---
    ("the direction threshold stops scaling with density", _T,
     "    return max(abs(density) * ADVERSE_FRACTION, _MIN_ADVERSE_RATE)\n",
     "    return 0.002\n"),
    ("direction is judged against a fixed fraction of nothing", _T,
     "    threshold = adverse_rate_for(result.density)\n    if result.velocity >= threshold:\n",
     "    threshold = 0.0\n    if result.velocity >= threshold:\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_trajectory_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TRAJECTORY_TESTS, run_tests_with_mutation(TRAJECTORY_TESTS, rel, old, new))


def test_trajectory_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        TRAJECTORY_TESTS, _T, "DETECTOR = \"trajectory\"\n", "DETECTOR = \"trajectory\"\n")
    assert result.returncode == 0, result.stdout[-2000:]
