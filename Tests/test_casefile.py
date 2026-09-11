"""The surgeon's case file: dispositions become priors, outcomes are kept.

The property that matters most is the one about what a prior is NOT: it
never hides a finding. A detector that stopped reporting something because
a human suppressed it three times is a detector that stops reporting the
fourth time it is real.
"""
from __future__ import annotations

import pytest

from ghost_buster.casefile import (
    BROKE,
    HEALED,
    Casefile,
    Prior,
    shape_of,
)
from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status


def _finding(detector="swallowed_exception", attrs=None, disposition=None, note=""):
    f = Finding(
        detector=detector, category=Category.VACUOUS_CHECK, layer=Layer.MECHANICAL,
        severity=Severity.MAJOR, status=Status.CONFIRMED, summary="x",
        evidence=Evidence(file="m.py"), attributes=attrs or {},
    )
    f.disposition = disposition
    f.disposition_note = note
    return f


# ------------------------------------------------------------ learning

def test_dispositions_become_cases(tmp_path):
    cf = Casefile(tmp_path / "cases.json")
    n = cf.record_dispositions([
        _finding(disposition="suppress", note="optional dep"),
        _finding(disposition="fix"),
        _finding(disposition="document"),
        _finding(disposition=None),          # undecided teaches nothing
    ])
    assert n == 3
    assert len(cf) == 3
    assert cf.prior("swallowed_exception").counts == {"false": 1, "real": 2}


def test_document_is_a_real_finding(tmp_path):
    """Explained rather than fixed is still real."""
    cf = Casefile(tmp_path / "c.json")
    cf.record_dispositions([_finding(disposition="document")])
    assert cf.prior("swallowed_exception").counts == {"real": 1}


def test_outcomes_are_recorded_and_unknown_ones_refused(tmp_path):
    cf = Casefile(tmp_path / "c.json")
    f = _finding()
    cf.record_outcome(f, HEALED, "nbsp repair")
    cf.record_outcome(f, BROKE, "reverted")
    assert cf.prior("swallowed_exception").counts == {HEALED: 1, BROKE: 1}
    with pytest.raises(ValueError):
        cf.record_outcome(f, "cured")


def test_the_case_file_survives_a_round_trip(tmp_path):
    path = tmp_path / "c.json"
    cf = Casefile(path)
    cf.record_dispositions([_finding(disposition="suppress", note="why")])
    cf.save()
    again = Casefile(path)
    assert len(again) == 1
    assert again.cases[0].note == "why"
    assert again.cases[0].outcome == "false"


# --------------------------------------------------------------- shape

def test_shape_is_the_kind_not_the_instance():
    a = _finding(attrs={"caught": "Exception"})
    b = _finding(attrs={"caught": "Exception"})
    c = _finding(attrs={"caught": "ImportError"})
    a.evidence = Evidence(file="a.py")
    b.evidence = Evidence(file="b.py")
    assert shape_of(a) == shape_of(b)
    assert shape_of(a) != shape_of(c)
    assert shape_of(_finding(attrs={})) == "swallowed_exception"


def test_a_shape_prior_beats_a_detector_prior_when_it_exists(tmp_path):
    cf = Casefile(tmp_path / "c.json")
    cf.record_dispositions([
        _finding(attrs={"caught": "ImportError"}, disposition="suppress"),
        _finding(attrs={"caught": "ImportError"}, disposition="suppress"),
        _finding(attrs={"caught": "Exception"}, disposition="fix"),
    ])
    narrow = cf.prior("swallowed_exception", shape_of(_finding(attrs={"caught": "ImportError"})))
    assert narrow.shape is not None
    assert narrow.counts == {"false": 2}
    assert narrow.false_rate == 1.0
    broad = cf.prior("swallowed_exception", shape_of(_finding(attrs={"caught": "OSError"})))
    assert broad.shape is None, "an unseen shape falls back to the detector"
    assert broad.counts == {"false": 2, "real": 1}


def test_no_history_says_so():
    p = Prior("x", None, {})
    assert p.seen == 0
    assert p.false_rate is None
    assert p.render() == "no history"


# ----------------------------------------------------- never hides anything

def test_annotate_returns_a_prior_for_every_finding_and_drops_none(tmp_path):
    """The loop informs; it never filters. Three suppressions do not make
    the fourth occurrence disappear."""
    cf = Casefile(tmp_path / "c.json")
    cf.record_dispositions([_finding(disposition="suppress")] * 3)
    fresh = [_finding(), _finding(detector="dead_end_call")]
    priors = cf.annotate(fresh)
    assert set(priors) == {f.id for f in fresh}
    assert priors[fresh[0].id].counts == {"false": 3}
    assert priors[fresh[1].id].seen == 0
    assert "3 false" in priors[fresh[0].id].render()
