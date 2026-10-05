"""What ghost_buster remembers between runs, and what it must never do
with the memory.

The dangerous feature here is not the storage, it is the temptation: a
tool that remembers what you ignored is one small step from a tool that
stops telling you. Every self-tuning suppressor shares one gradient --
fewer findings looks like success -- so the tests below spend as much
effort proving the ledger stays additive as proving it works at all.
"""
from __future__ import annotations

import json

import pytest

from ghost_buster.cli import main
from ghost_buster.ledger import (
    BLIND_SPOT_AFTER, COULD_NOT_RUN, DECLINED, FLAPPING_AFTER, Ledger, LedgerError,
    MAX_RUNS_KEPT, NOT_APPLICABLE, NOT_RUN, PERSISTENT_AFTER, RAN, SCHEMA_VERSION,
)
from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status

ALL_RAN = {"structural": RAN, "branches": RAN, "tests": RAN, "secrets": RAN}


def _f(detector="dead_code", file="m.py", summary="a dead function", severity=Severity.MINOR):
    return Finding(
        detector=detector, category=Category.DEAD_CODE, layer=Layer.MECHANICAL,
        severity=severity, status=Status.CONFIRMED, summary=summary,
        evidence=Evidence(file=file),
    )


def _ledger(tmp_path):
    return Ledger(tmp_path / ".ghost_ledger.json")


def _run(led, findings, *, checks=None, at=None):
    led.record(findings, checks=checks or dict(ALL_RAN), commit="c0ffee",
               tool_version="test", at=at)
    return led.derive(findings)


# --------------------------------------------------------------- storage

def test_first_run_has_no_history_and_says_so(tmp_path):
    led = _ledger(tmp_path)
    assert led.existed is False
    assert _run(led, [_f()]) == []


def test_history_survives_a_reload(tmp_path):
    led = _ledger(tmp_path)
    _run(led, [_f()])
    led.save()
    again = _ledger(tmp_path)
    assert again.existed is True
    assert again.run_count == 1
    assert len(again.findings) == 1


def test_a_corrupt_ledger_is_refused_not_silently_restarted(tmp_path):
    """Starting fresh would report an empty history as though it were a
    clean one, which is the exact lie this module exists to prevent."""
    p = tmp_path / ".ghost_ledger.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(LedgerError):
        Ledger(p)


def test_a_ledger_from_a_future_schema_is_refused(tmp_path):
    p = tmp_path / ".ghost_ledger.json"
    p.write_text(json.dumps({"schema": SCHEMA_VERSION + 1, "runs": [], "findings": {}}))
    with pytest.raises(LedgerError):
        Ledger(p)


def test_a_non_ledger_json_file_is_refused(tmp_path):
    p = tmp_path / ".ghost_ledger.json"
    p.write_text(json.dumps([1, 2, 3]))
    with pytest.raises(LedgerError):
        Ledger(p)


def test_save_leaves_no_temp_files_behind(tmp_path):
    led = _ledger(tmp_path)
    _run(led, [_f()])
    led.save()
    assert [p.name for p in tmp_path.iterdir()] == [".ghost_ledger.json"]


def test_run_history_is_capped_but_the_count_is_not(tmp_path):
    """A governance record nobody wants to commit is one nobody keeps."""
    led = _ledger(tmp_path)
    for i in range(MAX_RUNS_KEPT + 25):
        _run(led, [_f()], at=f"2026-01-01T00:{i:02d}:00+00:00")
    assert len(led.runs) == MAX_RUNS_KEPT
    assert led.run_count == MAX_RUNS_KEPT + 25


# ------------------------------------------------------------ regression

def test_a_finding_that_was_fixed_and_came_back_is_a_regression(tmp_path):
    led = _ledger(tmp_path)
    _run(led, [_f()])
    _run(led, [])            # fixed
    derived = _run(led, [_f()])  # back
    kinds = [d.attributes["kind"] for d in derived]
    assert "regressed_finding" in kinds


def test_a_regression_outranks_the_finding_it_is_about(tmp_path):
    led = _ledger(tmp_path)
    _run(led, [_f(severity=Severity.MINOR)])
    _run(led, [])
    derived = _run(led, [_f(severity=Severity.MINOR)])
    regression = next(d for d in derived if d.attributes["kind"] == "regressed_finding")
    assert regression.severity == Severity.MAJOR


def test_a_regressed_critical_stays_critical_instead_of_crashing(tmp_path):
    """There is no rung above CRITICAL. Escalating off the end of the
    ladder would take the whole run down with an IndexError."""
    led = _ledger(tmp_path)
    crit = _f(severity=Severity.CRITICAL)
    _run(led, [crit])
    _run(led, [])
    derived = _run(led, [_f(severity=Severity.CRITICAL)])
    regression = next(d for d in derived if d.attributes["kind"] == "regressed_finding")
    assert regression.severity == Severity.CRITICAL


def test_a_finding_present_every_run_is_not_a_regression(tmp_path):
    led = _ledger(tmp_path)
    for _ in range(4):
        derived = _run(led, [_f()])
    assert [d for d in derived if d.attributes.get("kind") == "regressed_finding"] == []


def test_repeated_returns_become_flapping_not_more_regressions(tmp_path):
    """A detector that cannot make up its mind is a different problem from
    a defect that came back, and baselining it would hide the real fault."""
    led = _ledger(tmp_path)
    for _ in range(FLAPPING_AFTER):
        _run(led, [_f()])
        _run(led, [])
    derived = _run(led, [_f()])
    kinds = [d.attributes["kind"] for d in derived]
    assert "flapping_finding" in kinds
    assert "regressed_finding" not in kinds


# ------------------------------------------------------------ persistence

def test_a_finding_open_for_many_runs_with_no_decision_is_reported(tmp_path):
    led = _ledger(tmp_path)
    for _ in range(PERSISTENT_AFTER):
        derived = _run(led, [_f()])
    assert any(d.attributes["kind"] == "persistent_finding" for d in derived)


def test_a_finding_with_a_recorded_decision_is_not_nagged_about(tmp_path):
    """The point of persistent_finding is "nobody has said either way". Once
    somebody has, repeating it is nagging, and nagging is how the tool
    trains you to stop reading it."""
    led = _ledger(tmp_path)
    for _ in range(PERSISTENT_AFTER):
        decided = _f()
        decided.disposition = "keep"
        decided.disposition_note = "intentional, documented in ADR-4"
        derived = _run(led, [decided])
    assert not any(d.attributes["kind"] == "persistent_finding" for d in derived)


def test_a_young_finding_is_not_called_persistent(tmp_path):
    led = _ledger(tmp_path)
    for _ in range(PERSISTENT_AFTER - 1):
        derived = _run(led, [_f()])
    assert not any(d.attributes["kind"] == "persistent_finding" for d in derived)


# ------------------------------------------------------------- blind spot

@pytest.mark.parametrize("state,severity", [
    (DECLINED, Severity.MAJOR),
    (COULD_NOT_RUN, Severity.MINOR),
    (NOT_RUN, Severity.INFORMATIONAL),
])
def test_blind_spot_severity_follows_the_reason_nobody_looked(tmp_path, state, severity):
    """--mutate is opt-in on cost, so it is NOT_RUN forever on most repos.
    Rating that MAJOR would put a permanent unfixable MAJOR in every
    ledger, which is how a tool teaches people to stop reading it."""
    led = _ledger(tmp_path)
    checks = dict(ALL_RAN, tests=state)
    for _ in range(BLIND_SPOT_AFTER):
        derived = _run(led, [_f()], checks=checks)
    spot = next(d for d in derived if d.attributes.get("check") == "tests")
    assert spot.severity == severity


def test_a_check_with_nothing_to_examine_is_never_a_blind_spot(tmp_path):
    """NOT_APPLICABLE is not a skip. A repository that reaches across no
    boundary has no cross-boundary seam to leave unchecked, so counting it
    would put a finding nobody can ever clear in every single-repository
    ledger -- the failure _BLIND_SPOT_SEVERITY reasons about, one severity
    quieter. Measured on ATS: 7 consecutive runs of exactly that."""
    led = _ledger(tmp_path)
    checks = dict(ALL_RAN, boundary=NOT_APPLICABLE)
    for _ in range(BLIND_SPOT_AFTER * 2):
        derived = _run(led, [_f()], checks=checks)
    assert not any(d.attributes.get("check") == "boundary" for d in derived)


def test_a_check_nobody_ran_is_still_a_blind_spot_beside_one_that_did_not_apply(tmp_path):
    """The other half: adding the state must not have muffled the states it
    sits beside, and the two are told apart in the same run."""
    led = _ledger(tmp_path)
    checks = dict(ALL_RAN, boundary=NOT_APPLICABLE, tests=DECLINED)
    for _ in range(BLIND_SPOT_AFTER):
        derived = _run(led, [_f()], checks=checks)
    spots = {d.attributes.get("check") for d in derived if d.attributes.get("check")}
    assert spots == {"tests"}


def test_an_inapplicable_run_breaks_a_streak_the_way_a_run_does(tmp_path):
    """A check that had nothing to look at this time ends the streak: the
    question stopped being unanswered, it stopped being asked."""
    led = _ledger(tmp_path)
    declined = dict(ALL_RAN, boundary=DECLINED)
    for _ in range(BLIND_SPOT_AFTER - 1):
        _run(led, [_f()], checks=declined)
    _run(led, [_f()], checks=dict(ALL_RAN, boundary=NOT_APPLICABLE))
    derived = _run(led, [_f()], checks=declined)
    assert not any(d.attributes.get("check") == "boundary" for d in derived)


def test_a_check_that_ran_recently_is_not_a_blind_spot(tmp_path):
    led = _ledger(tmp_path)
    checks_off = dict(ALL_RAN, tests=DECLINED)
    for _ in range(BLIND_SPOT_AFTER):
        _run(led, [_f()], checks=checks_off)
    derived = _run(led, [_f()], checks=dict(ALL_RAN))
    assert not any(d.attributes.get("check") == "tests" for d in derived)


def test_the_streak_must_be_consecutive(tmp_path):
    led = _ledger(tmp_path)
    checks_off = dict(ALL_RAN, tests=DECLINED)
    for _ in range(BLIND_SPOT_AFTER - 1):
        _run(led, [_f()], checks=checks_off)
    _run(led, [_f()], checks=dict(ALL_RAN))          # breaks it
    derived = _run(led, [_f()], checks=checks_off)   # streak restarts at 1
    assert not any(d.attributes.get("check") == "tests" for d in derived)


# ------------------------------------------ the rules it must never break

def test_the_ledger_never_remembers_its_own_output(tmp_path):
    """History about history compounds. correlate.py closes the same trap
    by refusing to correlate correlations."""
    led = _ledger(tmp_path)
    _run(led, [_f()])
    _run(led, [])
    derived = _run(led, [_f()])
    assert derived, "the setup must actually produce a history finding"
    led.record(derived, checks=dict(ALL_RAN), commit="c", tool_version="t")
    assert all(h.detector != "ledger" for h in led.findings.values())


def test_the_ledger_only_ever_adds(tmp_path):
    """Not one derived finding may replace or remove an input finding."""
    led = _ledger(tmp_path)
    original = _f()
    _run(led, [original])
    _run(led, [])
    derived = _run(led, [original])
    assert all(d.detector == "ledger" for d in derived)
    assert original.severity == Severity.MINOR, "the input finding was mutated"


def test_accepting_into_the_baseline_does_not_erase_memory(tmp_path, capsys):
    """--accept changes what you are shown. It must not change what the
    tool remembers, or accepting becomes a way to delete history."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "m.py").write_text("def used():\n    return used\n\ndef dead():\n    return 2\n")
    base = ["--no-tests", "--no-secrets", "--no-branches",
            "--baseline", str(tmp_path / "b.json")]
    main([str(proj), *base])
    main([str(proj), "--accept", *base])
    capsys.readouterr()
    led = Ledger(proj / ".ghost_ledger.json")
    assert led.run_count == 2
    assert any(h.detector == "dead_code" for h in led.findings.values())


# ------------------------------------------------------------------- CLI

def test_history_is_reported_alongside_the_findings_not_instead_of_them(tmp_path, capsys):
    """The ledger is additive. A run that surfaces a regression must still
    surface the underlying defect -- replacing one with the other would
    make the memory a filter, which is the one thing it must never be."""
    proj = tmp_path / "proj"
    proj.mkdir()
    base = ["--json", "--no-tests", "--no-secrets", "--no-branches",
            "--baseline", str(tmp_path / "b.json")]
    live = "def used():\n    return used\n"
    dead = live + "\ndef gone():\n    return 2\n"

    (proj / "m.py").write_text(dead)
    main([str(proj), *base])
    (proj / "m.py").write_text(live)          # fixed
    main([str(proj), *base])
    (proj / "m.py").write_text(dead)          # and back
    capsys.readouterr()
    main([str(proj), *base])
    payload = capsys.readouterr().out

    parsed = json.loads(payload)
    rows = parsed["findings"] if isinstance(parsed, dict) else parsed
    detectors = {f["detector"] for f in rows}
    assert "ledger" in detectors, "the regression must be reported"
    assert "dead_code" in detectors, "the defect it is about must ALSO still be reported"


def test_ledger_is_on_by_default_and_writes_a_file(tmp_path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "m.py").write_text("x = 1\n")
    main([str(proj), "--no-tests", "--no-secrets", "--no-branches",
          "--baseline", str(tmp_path / "b.json")])
    capsys.readouterr()
    assert (proj / ".ghost_ledger.json").exists()


def test_no_ledger_writes_nothing_and_leaves_a_receipt(tmp_path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "m.py").write_text("x = 1\n")
    main([str(proj), "--no-ledger", "--no-tests", "--no-secrets", "--no-branches",
          "--baseline", str(tmp_path / "b.json")])
    err = capsys.readouterr().err
    assert not (proj / ".ghost_ledger.json").exists()
    assert "ledger SKIPPED at your request (--no-ledger)" in err


def test_a_corrupt_ledger_fails_the_run_rather_than_starting_over(tmp_path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "m.py").write_text("x = 1\n")
    (proj / ".ghost_ledger.json").write_text("{not json", encoding="utf-8")
    rc = main([str(proj), "--no-tests", "--no-secrets", "--no-branches",
               "--baseline", str(tmp_path / "b.json")])
    assert rc == 2
    assert "error: ledger" in capsys.readouterr().err
