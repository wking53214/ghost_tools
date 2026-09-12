"""A measurement is not an identity.

WHAT A FINDING'S ID IS FOR

A baseline suppresses by id. A ledger remembers by id. Both promises break
if the id moves while the defect does not:

    the id moves    a committed baseline stops matching, every finding
                    reads as new, and a triaged repository looks untriaged
    the id collides two different defects share one identity, so accepting
                    one silently stops the other being reported

THE DEFECT THIS FILE GUARDS AGAINST (v1.7.3)

The id is a content hash of detector + portable path + summary, and several
summaries carry a number the run just measured. Measured against 1.7.2 by an
adversarial harness: adding three tests to a suite, with the documented claim
untouched at 12, gave three findings three new identities.

    no_ci_configuration            "1 test file(s)" -> "2 test file(s)"
    doc_count_contradicted_by_run  "collects 30"    -> "collects 33"
    doc_test_count_drift           "at least 30"    -> "at least 33"

Accepting any of them into a baseline meant accepting it until the next
commit that changed a count.

WHY NOT JUST STRIP DIGITS FROM EVERY SUMMARY

Because `'core_0' is defined but never referenced` and `'core_1' is defined
but never referenced` differ only in a digit, and collapsing those into one
identity means accepting one suppresses the other. That is the same failure
pointing the other way, and it is the worse direction. There is a test for
it below.

So the DETECTOR says what identifies its finding, because only the detector
knows which part of its own sentence is the defect and which part is this
morning's arithmetic.
"""
from __future__ import annotations

import pytest

from ghost_buster.schema import (Category, Evidence, Finding, Layer, Severity,
                                 Status)


def _finding(summary, *, detector="doc_test_count_drift", file="README.md",
             identity_key=None):
    return Finding(
        detector=detector, category=Category.DOC_DRIFT, layer=Layer.MECHANICAL,
        severity=Severity.MINOR, status=Status.CONFIRMED,
        summary=summary, detail="", identity_key=identity_key,
        evidence=Evidence(file=file, line_start=1, line_end=1))


# ----------------------------------------------------------- the mechanism

def test_without_a_key_the_summary_still_decides():
    """Every detector that has not opted in behaves exactly as before."""
    assert _finding("a").id != _finding("b").id
    assert _finding("a").id == _finding("a").id


def test_a_key_replaces_the_summary_in_the_id():
    same = _finding("claims 12, and 30 exist", identity_key="claims 12")
    moved = _finding("claims 12, and 33 exist", identity_key="claims 12")
    assert same.id == moved.id


def test_an_empty_key_is_a_key_and_not_an_absence():
    """`None` means "use the summary". An empty string is a detector saying
    the path alone identifies this. Reading one as the other would silently
    put the summary back."""
    a = _finding("one summary", identity_key="")
    b = _finding("a different summary", identity_key="")
    assert a.id == b.id
    assert a.id != _finding("one summary").id


def test_the_key_does_not_escape_the_file_or_the_detector():
    """It replaces one of three parts. Two findings with the same key in
    different files, or from different detectors, stay distinct."""
    here = _finding("s", file="README.md", identity_key="claims 12")
    there = _finding("s", file="docs/INDEX.md", identity_key="claims 12")
    other = _finding("s", detector="dead_code", identity_key="claims 12")
    assert len({here.id, there.id, other.id}) == 3


def test_two_defects_differing_only_in_a_digit_stay_distinct():
    """The reason a blanket digit-strip is not the fix. These two are
    different defects and must never share an identity."""
    first = _finding("'core_0' is defined but never referenced",
                     detector="dead_code", file="app/core.py")
    second = _finding("'core_1' is defined but never referenced",
                      detector="dead_code", file="app/core.py")
    assert first.id != second.id


# --------------------------------------------- the three that carried numbers

def test_the_drift_finding_survives_the_suite_growing(tmp_path):
    """One directory, rewritten in place.

    Deliberately not two temporary directories. With no project marker the
    portable path falls back to the last two segments, so the directory's
    own name lands in the id and two tmpdirs differ for a reason that has
    nothing to do with what is being tested. That is how this test failed
    first time.
    """
    from ghost_buster.mechanical import run_all

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
    (tmp_path / "README.md").write_text(
        "# thing\n\nThe test suite has 12 tests, all passing.\n")

    def measure(tests):
        (tmp_path / "test_main.py").write_text(
            "".join("def test_%02d():\n    assert True\n\n\n" % i
                    for i in range(tests)))
        findings = run_all(sorted(tmp_path.iterdir()))
        drift = [f for f in findings if f.detector == "doc_test_count_drift"]
        assert drift, "the drift finding did not fire at %d tests" % tests
        return drift[0]

    before, after = measure(30), measure(33)
    assert "30" in before.summary and "33" in after.summary, (
        "the summaries did not move, so this proves nothing")
    assert before.id == after.id, (
        "the same stale claim was given two identities because the suite grew")


def test_a_document_edited_to_a_different_wrong_number_is_a_new_finding(tmp_path):
    """The boundary, through the real detector.

    The documented number IS part of what the claim says. Editing a README
    from 12 to 13, still wrong, is a different claim and a different
    finding. Only the MEASURED side was taken out of the identity, and a
    key that dropped the claim as well would collapse every stale count in
    a document into one.
    """
    from ghost_buster.mechanical import run_all

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
    (tmp_path / "test_main.py").write_text(
        "".join("def test_%02d():\n    assert True\n\n\n" % i
                for i in range(30)))

    def measure(documented):
        (tmp_path / "README.md").write_text(
            "# thing\n\nThe test suite has %d tests, all passing.\n" % documented)
        drift = [f for f in run_all(sorted(tmp_path.iterdir()))
                 if f.detector == "doc_test_count_drift"]
        assert drift, "the drift finding did not fire at %d" % documented
        return drift[0]

    assert measure(12).id != measure(13).id


def test_the_project_finding_survives_a_new_test_file(tmp_path):
    from ghost_buster.project import scan

    def build(count):
        for existing in tmp_path.glob("test_*.py"):
            existing.unlink()
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n')
        for index in range(count):
            (tmp_path / ("test_%d.py" % index)).write_text(
                "def test_x():\n    assert True\n")
        return [f for f in scan(tmp_path)[0]
                if f.detector == "no_ci_configuration"]

    one, two = build(1), build(2)
    assert one and two, "no_ci_configuration did not fire"
    assert one[0].id == two[0].id, (
        "the repository still has no CI; only the count of affected files moved")


def test_the_correlation_survives_the_measurement_moving():
    from ghost_buster.correlate import run_connectors
    from ghost_buster.schema import Finding as F

    def drift():
        return F(detector="doc_test_count_drift", category=Category.DOC_DRIFT,
                 layer=Layer.MECHANICAL, severity=Severity.MINOR,
                 status=Status.CONFIRMED,
                 summary="'README.md' claims 12 test(s)", detail="",
                 attributes={"documented_count": "12", "writable": "yes",
                             "claim_context": "The test suite has "},
                 evidence=Evidence(file="README.md", line_start=1, line_end=1))

    class Report:
        ran, errored, blocked = True, 0, 0
        def __init__(self, n): self.collected = self.passed = n

    first = run_connectors([drift()], test_report=Report(30))
    later = run_connectors([drift()], test_report=Report(33))
    assert first and later
    assert first[0].id == later[0].id, (
        "the claim is contradicted either way; only the measurement moved")


def test_a_different_claim_is_a_different_finding():
    """The boundary. The documented number IS part of what the claim says,
    so a document edited from 12 to 13 is a new claim and a new finding.
    Only the measured side was taken out of the identity."""
    twelve = _finding("s", identity_key="claims 12 test(s), stale")
    thirteen = _finding("s", identity_key="claims 13 test(s), stale")
    assert twelve.id != thirteen.id


def test_the_round_trip_keeps_the_id():
    """A baseline stores ids. One that changed on read would be inert."""
    finding = _finding("claims 12, and 30 exist", identity_key="claims 12")
    restored = Finding.from_dict(finding.as_dict())
    assert restored.id == finding.id
