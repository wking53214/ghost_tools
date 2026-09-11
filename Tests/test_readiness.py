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


def test_the_tests_criterion_names_the_tests():
    """"2 failing or flaky test(s)" sends the reader back to the report.
    The first patient reported exactly that and nothing on the page said
    which two. The criterion names them now, from the finding's nodeid."""
    a, b, minor = _f("test_status"), _f("test_status"), _f("test_status", Severity.MINOR)
    a.attributes["nodeid"] = "Tests/test_a.py::test_one"
    b.attributes["nodeid"] = "Tests/test_b.py::test_two"
    minor.attributes["nodeid"] = "Tests/test_c.py::test_skip"
    r = assess([a, b, minor], ALL_RAN)
    tests = next(c for c in r.criteria if c.name == TESTS)
    assert tests.met is False
    assert "2 failing or flaky test(s): Tests/test_a.py::test_one, Tests/test_b.py::test_two" == tests.evidence
    assert "test_skip" not in tests.evidence


def test_the_tests_criterion_truncates_a_long_list():
    fs = [_f("test_status") for _ in range(6)]
    for i, f in enumerate(fs):
        f.attributes["nodeid"] = f"Tests/test_x.py::test_{i}"
    tests = next(c for c in assess(fs, ALL_RAN).criteria if c.name == TESTS)
    assert tests.evidence.startswith("6 failing or flaky test(s): Tests/test_x.py::test_0")
    assert tests.evidence.endswith("(+2 more)")



# ---------------------------------------------------- secrets: established vs candidate

def test_an_established_credential_fails_the_gate():
    r = assess([_f("committed_secret", Severity.CRITICAL)], ALL_RAN)
    assert [c.name for c in r.failing] == [SECRETS]
    assert "1 credential(s) established" in r.render()


def test_a_shape_only_candidate_is_reported_beside_the_verdict_and_does_not_fail():
    """A generic-api-key hit establishes a candidate, not a credential. The
    last sweep read 32 of them by hand and every one was a fixture, a word
    or a transcript. Failing candidacy on a candidate is how the gate gets
    skimmed."""
    r = assess([_f("committed_secret", Severity.MAJOR)], ALL_RAN)
    assert r.candidate
    [sec] = [c for c in r.criteria if c.name == SECRETS]
    assert sec.met is True
    assert sec.evidence == "none established; 1 candidate(s) to read"


def test_a_candidate_dismissed_in_the_case_file_is_retired_not_hidden():
    import dataclasses
    f1 = _f("committed_secret", Severity.MAJOR)
    f2 = dataclasses.replace(f1, summary="a second candidate, a different id")
    assert f1.id != f2.id
    r = assess([f1, f2], ALL_RAN, retired={f1.id})
    [sec] = [c for c in r.criteria if c.name == SECRETS]
    assert sec.met is True
    assert sec.evidence == "none established; 1 candidate(s) to read, 1 retired as false in the case file"


def test_retirement_never_reaches_an_established_credential():
    f = _f("committed_secret", Severity.CRITICAL)
    r = assess([f], ALL_RAN, retired={f.id})
    assert not r.candidate and "established" in r.render()


def test_the_cli_reads_retirements_from_the_case_file(tmp_path, capsys, monkeypatch):
    """End to end: a candidate the case file dismissed shows as retired in
    the readiness the plain report prints."""
    from ghost_buster.cli import main
    from ghost_buster.casefile import Case, Casefile
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("x = 1\n")
    fake = _f("committed_secret", Severity.MAJOR)
    report = type("R", (), {"ran": True, "reason": ""})()
    monkeypatch.setattr("ghost_buster.pipeline.scan_secrets", lambda root, **kw: ([fake], report))
    monkeypatch.setattr("ghost_buster.pipeline.render_secrets_report", lambda rep: "ghost_buster: secrets: stubbed")
    cf = Casefile(repo / ".ghost_casefile.json")
    cf.cases = [Case("committed_secret", "committed_secret", "false", "fixture", "2026-09-10T00:00:00",
                     fake.id, "m.py", "suppress")]
    cf.save()
    main([str(repo), "--no-tests", "--no-branches", "--no-project", "--no-correlate", "--no-ledger",
          "--single-repo", "--baseline", str(tmp_path / "b.json")])
    out = capsys.readouterr().out
    assert "1 retired as false in the case file" in out
    assert "met      no committed secrets" in out

# ------------------------------------------------- evidence that predates a cut

def test_a_carried_criterion_says_its_evidence_is_the_workups():
    """After a cut, the re-examination does not run the test suite or the
    secrets scan, so their verdicts are the workup's. The gate keeps the
    verdict and the report stops presenting it as a second look."""
    verdict = assess([], {"tests": RAN, "secrets": RAN},
                     carried=(TESTS, SECRETS))
    tests = next(c for c in verdict.criteria if c.name == TESTS)
    parses = next(c for c in verdict.criteria if c.name == PARSES)

    assert tests.met is True and tests.carried
    assert not parses.carried, "the re-examination does run the parser"
    assert "carried from the workup" in verdict.render()
    assert "the evidence predates the cut" in verdict.render()


def test_nothing_is_carried_unless_it_is_named():
    verdict = assess([], {"tests": RAN, "secrets": RAN})
    assert not verdict.carried
    assert "carried" not in verdict.render()


def test_carrying_changes_the_account_not_the_verdict():
    """A carried criterion is not a weaker one: the workup measured it."""
    plain = assess([], {"tests": RAN, "secrets": RAN})
    carried = assess([], {"tests": RAN, "secrets": RAN}, carried=(TESTS,))
    assert plain.candidate == carried.candidate
    assert [c.met for c in plain.criteria] == [c.met for c in carried.criteria]
