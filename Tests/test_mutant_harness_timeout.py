"""The per-mutant timeout of the hand-mutant suites.

It was a fixed 120 s. Under load (a load average of 12 to 20 on 4 CPUs, other
jobs on the same machine) four mutants that pass in seconds when alone timed
out. `GHOST_MUTANT_TIMEOUT` (seconds) sets the base, a busy machine scales it,
and nothing may exceed MAX_TIMEOUT, so a hung mutant still ends the run.
"""
from __future__ import annotations

import pytest

import mutant_harness as h


def _t(env=None, load=0.0, cpus=4):
    return h.mutant_timeout(environ=env or {}, loadavg=load, cpus=cpus)


def test_the_default_is_120_seconds_on_an_idle_machine():
    assert _t() == 120.0
    assert _t(load=4.0) == 120.0          # load equal to the CPU count is not busy


def test_the_environment_variable_sets_the_base():
    assert _t({"GHOST_MUTANT_TIMEOUT": "300"}) == 300.0
    assert _t({"GHOST_MUTANT_TIMEOUT": "12.5"}) == 12.5
    assert _t({"GHOST_MUTANT_TIMEOUT": ""}) == 120.0


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "nan", "inf"])
def test_a_bad_value_is_refused_not_replaced_by_the_default(bad):
    with pytest.raises(ValueError, match="GHOST_MUTANT_TIMEOUT"):
        _t({"GHOST_MUTANT_TIMEOUT": bad})


def test_a_busy_machine_scales_the_timeout_by_load_over_cpus():
    assert _t(load=8.0) == 240.0          # load 8 on 4 CPUs: 2x
    assert _t(load=6.0, cpus=4) == 180.0
    assert _t({"GHOST_MUTANT_TIMEOUT": "100"}, load=8.0) == 200.0


def test_the_scaling_factor_is_capped():
    assert _t(load=20.0) == 120.0 * h.MAX_LOAD_FACTOR == 480.0
    assert _t(load=10_000.0) == 480.0


def test_nothing_exceeds_the_hard_upper_bound():
    assert h.MAX_TIMEOUT == 900.0
    assert _t({"GHOST_MUTANT_TIMEOUT": "100000"}) == 900.0
    assert _t({"GHOST_MUTANT_TIMEOUT": "600"}, load=20.0) == 900.0


def test_the_harness_passes_the_computed_timeout_to_the_subprocess(monkeypatch, tmp_path):
    seen = {}

    def fake_run(*args, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setenv("GHOST_MUTANT_TIMEOUT", "77")
    monkeypatch.setattr(h.os, "getloadavg", lambda: (0.0, 0.0, 0.0))
    monkeypatch.setattr(h.subprocess, "run", fake_run)
    monkeypatch.setattr(h, "ROOT", tmp_path)
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="stop here"):
        h.run_tests_with_mutation("t.py", "m.py", "x = 1", "x = 2")
    assert seen["timeout"] == 77.0


def test_no_load_average_means_no_scaling(monkeypatch):
    def unavailable():
        raise OSError("no load average")
    monkeypatch.setattr(h.os, "getloadavg", unavailable)
    assert h.mutant_timeout(environ={}, cpus=4) == 120.0
