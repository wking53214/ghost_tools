"""Optional CNS adapter — works with or without cns installed."""
from __future__ import annotations

import importlib

import pytest

from ghost_buster.schema import Status
from ghost_buster import cns_adapter


def test_cns_available_when_installed():
    avail = cns_adapter.cns_available()
    # Soft: if cns is installed in the environment this is True; if not, False.
    # Deployment CI may or may not pin CNS. Both are valid.
    assert isinstance(avail.ok, bool)


def test_translate_confirmed_shape():
    r = cns_adapter.translate_status(Status.CONFIRMED, {"path": "a.py", "id": "1"})
    assert r.translation.source_value == "confirmed"
    assert r.translation.cns_outcome == "pass"
    assert r.translation.information_lost
    if r.translation.cns_present:
        assert r.translation.authority == "cns.gate"
        assert r.gate_result is not None
        assert r.gate_result.subject_digest == r.translation.subject_digest
        assert r.translation.subject_digest
    else:
        assert r.translation.authority == "advisory_only"
        assert r.gate_result is None
        assert r.translation.subject_digest == ""


@pytest.mark.parametrize(
    "status,outcome",
    [
        (Status.CONFIRMED, "pass"),
        (Status.CONFIRMED_BY_REVIEW, "pass"),
        (Status.SUPPRESSED, "pass"),
        (Status.REASONED, "retry"),
        (Status.REJECTED, "terminal_breach"),
    ],
)
def test_mapping_table(status, outcome):
    r = cns_adapter.translate_status(status, {"path": "x.py"})
    assert r.translation.cns_outcome == outcome


def test_unknown_status_is_retry():
    r = cns_adapter.translate_status("not-a-status", {"path": "x.py"})
    assert r.translation.cns_outcome == "retry"


def test_advisory_when_cns_forced_missing(monkeypatch):
    monkeypatch.setattr(
        cns_adapter,
        "cns_available",
        lambda: cns_adapter.CnsAvailability(ok=False, missing=("cns.gate",), error="forced"),
    )
    r = cns_adapter.translate_status(Status.CONFIRMED, {"path": "a.py"})
    assert r.translation.cns_present is False
    assert r.gate_result is None
    assert r.translation.authority == "advisory_only"


def test_digest_stable_when_cns_present():
    if not cns_adapter.cns_available().ok:
        pytest.skip("cns not installed")
    s = {"path": "a.py", "n": 1}
    a = cns_adapter.translate_status(Status.CONFIRMED, s)
    b = cns_adapter.translate_status(Status.CONFIRMED, s)
    assert a.translation.subject_digest == b.translation.subject_digest
