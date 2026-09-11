"""Whether the patient is a candidate for the serum.

The property under test is the gate failing CLOSED: a criterion the scan
could not assess counts against the patient. A surgeon does not enhance
what they could not examine, and a tool that treated "unknown" as "fine"
would be the tool that hands the serum to Red Skull.
"""
from __future__ import annotations

from ghost_buster.ledger import COULD_NOT_RUN, DECLINED, RAN
from ghost_buster.readiness import (
    COPIES,
    HOLLOW,
    PARSES,
    SECRETS,
    SWALLOWED,
    TESTS,
    assess,
)
from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status


def _f(detector, severity=Severity.MAJOR):
    return Finding(detector=detector, category=Category.OTHER, layer=Layer.MECHANICAL,
                   severity=severity, status=Status.CONFIRMED, summary="x",
                   evidence=Evidence(file="m.py"))


ALL_RAN = {"tests": RAN, "secrets": RAN}


def test_a_clean_fully_examined_patient_is_a_candidate():
    r = assess([], ALL_RAN)
    assert r.candidate
    assert r.failing == [] and r.unknown == []
    assert "CANDIDATE" in r.render()


def test_unknown_counts_against_the_patient():
    """Nothing wrong was found -- because nothing was looked at."""
    r = assess([], {"tests": DECLINED, "secrets": COULD_NOT_RUN})
    assert not r.candidate
    assert {c.name for c in r.unknown} == {TESTS, SECRETS}
    assert "run with --tests" in r.render()
    assert "could not examine" in r.render()


def test_every_criterion_can_fail_on_its_own():
    cases = {
        PARSES: _f("unassessable_file", Severity.MINOR),
        TESTS: _f("test_status"),
        SECRETS: _f("committed_secret", Severity.CRITICAL),
        COPIES: _f("drifted_copy"),
        SWALLOWED: _f("swallowed_exception"),
        HOLLOW: _f("dead_end_call", Severity.MINOR),
    }
    for name, finding in cases.items():
        r = assess([finding], ALL_RAN)
        assert not r.candidate, name
        assert [c.name for c in r.failing] == [name], name


def test_only_major_copies_and_swallows_disqualify():
    """A tidy drifted copy (MINOR) and a narrow swallow (MINOR) are not
    disease; they are recorded and the patient remains a candidate."""
    r = assess([_f("drifted_copy", Severity.MINOR),
                _f("swallowed_exception", Severity.MINOR)], ALL_RAN)
    assert r.candidate


def test_any_hollow_contract_disqualifies_regardless_of_severity():
    """A raised NotImplementedError is MINOR as a finding and still a body
    that does nothing when called. The serum does not go into a patient
    with a hole in a contract."""
    assert not assess([_f("dead_end_call", Severity.MINOR)], ALL_RAN).candidate


def test_the_render_names_the_evidence():
    r = assess([_f("swallowed_exception"), _f("swallowed_exception")], ALL_RAN)
    text = r.render()
    assert "not a candidate" in text
    assert "2 handler(s)" in text
    assert "FAILING" in text
