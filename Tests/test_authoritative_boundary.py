"""A model's claim never becomes a deterministic decision.

The semantic layer has no caller and no flag today, so nothing REASONED
reaches a gate, a baseline or the ledger. That is an absence, not a
boundary: readiness filtered by detector name, the baseline by nothing,
and FindingHistory has no status field at all, so a claim folded in would
read as a measurement ever after.

These tests hold the boundary as code, against the day the layer is wired
-- which is exactly the day nobody will re-read this docstring.
"""
from __future__ import annotations

from ghost_buster.baseline import Baseline
from ghost_buster.ledger import RAN, Ledger
from ghost_buster.readiness import assess
from ghost_buster.schema import (
    AUTHORITATIVE, Category, Evidence, Finding, Layer, Severity, Status, authoritative,
)


def _finding(detector, status, *, layer=Layer.MECHANICAL, file="src/mod.py", summary="a finding"):
    return Finding(
        detector=detector, category=Category.DEAD_CODE, layer=layer,
        severity=Severity.MAJOR, status=status, summary=summary, detail="",
        evidence=Evidence(file=file),
    )


def _reasoned(detector="parallel_implementation", summary="two modules may be parallel"):
    return _finding(detector, Status.REASONED, layer=Layer.SEMANTIC, summary=summary)


# ----------------------------------------------------------- the vocabulary

def test_a_measurement_and_a_reviewed_claim_are_authoritative():
    assert Status.CONFIRMED in AUTHORITATIVE
    assert Status.CONFIRMED_BY_REVIEW in AUTHORITATIVE, (
        "a human who verified a REASONED finding has made it evidence"
    )


def test_an_unverified_claim_is_not():
    assert Status.REASONED not in AUTHORITATIVE
    assert Status.REJECTED not in AUTHORITATIVE


def test_the_filter_keeps_order_and_drops_only_claims():
    kept = _finding("dead_code", Status.CONFIRMED)
    claim = _reasoned()
    also = _finding("long_function", Status.CONFIRMED)
    assert authoritative([kept, claim, also]) == [kept, also]


# ------------------------------------------------------------- the gate

def test_a_claim_cannot_fail_a_readiness_criterion():
    """The criteria key on detector names today, so a semantic detector
    could not fail one by accident. This pins that it could not do so
    deliberately either, if a future criterion ever named one."""
    claim = _reasoned(detector="unassessable_file", summary="this file may not parse")
    verdict = assess([claim], {"tests": RAN, "secrets": RAN})
    parses = next(c for c in verdict.criteria if c.name == "parses completely")
    assert parses.met is True
    assert verdict.candidate


def test_a_measurement_still_fails_the_same_criterion():
    """The control. Without it, the test above would pass against a gate
    that had stopped reading findings at all."""
    real = _finding("unassessable_file", Status.CONFIRMED)
    verdict = assess([real], {"tests": RAN, "secrets": RAN})
    parses = next(c for c in verdict.criteria if c.name == "parses completely")
    assert parses.met is False
    assert not verdict.candidate


# ---------------------------------------------------------- the baseline

def test_a_claim_cannot_be_accepted_into_the_baseline(tmp_path):
    path = tmp_path / "baseline.json"
    Baseline(path).accept([_reasoned()])
    assert Baseline(path).size == 0, "a model's claim bought silence"


def test_a_measurement_is_still_accepted(tmp_path):
    path = tmp_path / "baseline.json"
    Baseline(path).accept([_finding("dead_code", Status.CONFIRMED)])
    assert Baseline(path).size == 1


# ------------------------------------------------------------- the ledger

def test_the_ledger_does_not_remember_a_claim(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.record([_reasoned(), _finding("dead_code", Status.CONFIRMED)],
                  checks={"tests": RAN}, commit="abc123", tool_version="test")
    remembered = {h.detector for h in ledger.findings.values()}
    assert remembered == {"dead_code"}, (
        "FindingHistory has no status field, so anything remembered here "
        "reads as a measurement forever after"
    )


def test_the_ledger_counts_what_it_was_given(tmp_path):
    """The claim is filtered from memory, not from the run's own count:
    the ledger must not under-report what the scan found."""
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.record([_reasoned(), _finding("dead_code", Status.CONFIRMED)],
                  checks={"tests": RAN}, commit="abc123", tool_version="test")
    assert ledger.runs[-1].counts["found"] == 2
