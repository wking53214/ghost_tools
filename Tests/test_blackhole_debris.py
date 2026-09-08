"""Debris archaeology: a flattened file keeps its interface in token order.

Measured on 2026-09-08 against TOUCHSTONE's `quorum_state_governance_source.py`
(14,162 bytes, zero newlines): the tool classified it DESTROYED, listed the
seven class names correctly, and then wrote "the evidence constrains no
shape". Every `class` and `def` header, with its parameter list and return
annotation, was still there in order. This file guards the fix.
"""
from __future__ import annotations

from pathlib import Path

from blackhole_extrapolator import EvidenceKind, detect_debris_structure, scan
from blackhole_extrapolator.cli import main
from blackhole_extrapolator.detect import debris_structure
from blackhole_extrapolator.extrapolate import extrapolate, group_by_target

ORIGINAL = '''
from typing import Any, Dict

def canonical(state: Dict[str, Any]) -> str:
    return ""

class Ledger:
    """Example: `def not_real(x): ...` lives in this docstring."""
    def __init__(self, path: str):
        self.path = path
    def append(self, event: Dict[str, Any]) -> None:
        pass

class Engine:
    def __init__(self, ledger: Ledger, ratio: float = 0.66):
        self.ledger = ledger
    def decide(self, proposals) -> Dict[str, Any]:
        return {}

def run(cycles: int = 5) -> Dict[str, Any]:
    return {}
'''
FLATTENED = " ".join(ORIGINAL.split("\n"))


def _flat(tmp_path: Path, name: str = "thing_source.py") -> Path:
    path = tmp_path / name
    path.write_text(FLATTENED)
    return path


def test_headers_come_back_in_order_with_owners_and_signatures():
    structure = debris_structure(FLATTENED)
    rendered = [(o, n, p, r) for o, n, p, r in structure]
    assert rendered[0] == ("", "canonical", "state: Dict[str, Any]", "-> str")
    assert ("", "Ledger", "", "") in rendered
    assert ("Ledger", "__init__", "self, path: str", "") in rendered
    assert ("Ledger", "append", "self, event: Dict[str, Any]", "-> None") in rendered
    assert ("Engine", "__init__", "self, ledger: Ledger, ratio: float = 0.66", "") in rendered
    assert ("Engine", "decide", "self, proposals", "-> Dict[str, Any]") in rendered
    assert rendered[-1] == ("", "run", "cycles: int = 5", "-> Dict[str, Any]")
    # The docstring example is indistinguishable from live code and is kept,
    # attributed to nothing: the tool says so instead of guessing.
    assert ("", "not_real", "x", "") in rendered


def test_flattened_file_yields_structure_evidence_and_a_parsing_file_does_not(tmp_path):
    flat = _flat(tmp_path)
    (tmp_path / "fine.py").write_text(ORIGINAL)
    found = list(detect_debris_structure(flat))
    assert len(found) == 1 and found[0].kind is EvidenceKind.DEBRIS_STRUCTURE
    assert "2 class(es), 4 method(s)" in found[0].detail
    assert "    Engine.decide(self, proposals) -> Dict[str, Any]" in found[0].detail
    assert list(detect_debris_structure(tmp_path / "fine.py")) == []


def test_recovered_interface_lands_in_the_void_as_must_define(tmp_path):
    flat = _flat(tmp_path)
    evidence = scan(tmp_path)
    grouped = group_by_target(evidence)
    assert list(grouped) == [str(flat)], "every mark of one destroyed file is one void"
    void = extrapolate(summary="x", anchors=[], evidence=grouped[str(flat)])
    assert "Ledger" in void.must_define
    assert "Ledger.append(self, event: Dict[str, Any]) -> None" in void.must_define
    assert "run(cycles: int = 5) -> Dict[str, Any]" in void.must_define
    assert "the interface itself" not in " ".join(void.undeterminable)
    assert any("bodies behind the recovered signatures" in u for u in void.undeterminable)
    assert void.shape_confidence >= 0.6


def test_companion_with_no_shared_names_is_called_an_ancestor_not_a_loss(tmp_path):
    flat = _flat(tmp_path)
    (tmp_path / "thing_adapter.py").write_text("class LedgerModule: ...\nclass EngineModule: ...\n")
    found = list(detect_debris_structure(flat))
    assert "companion `thing_adapter.py` parses and shares 0 of 2 class name(s)" in found[0].detail
    assert "ancestor" in found[0].detail
    # The companion's name must not steal the grouping.
    assert list(group_by_target(scan(tmp_path))) == [str(flat)]


def test_companion_that_keeps_the_names_says_compare_first(tmp_path):
    flat = _flat(tmp_path)
    (tmp_path / "thing_adapter.py").write_text("class Ledger: ...\n")
    found = list(detect_debris_structure(flat))
    assert "shares 1 of 2 class name(s) (['Ledger'])" in found[0].detail
    assert "compare before treating this as lost" in found[0].detail


def test_cli_prints_the_recovered_signatures(tmp_path, capsys):
    _flat(tmp_path)
    main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "must define  Engine.__init__(self, ledger: Ledger, ratio: float = 0.66)" in out
    assert "the evidence constrains no shape" not in out
