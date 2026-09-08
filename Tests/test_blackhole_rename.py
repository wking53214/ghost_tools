"""Rename candidates: Jon is looking for Sally, and Sally is now Karen.

Guarded by the TOUCHSTONE case found on 2026-09-08: superseded specimens
call `initialize_hybrid_cluster` and unpack three values; the flattened
quorum file declares `initialize_network_cluster` returning a three-tuple
whose elements flow into the next call's typed parameters.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from blackhole_extrapolator import EvidenceKind, scan
from blackhole_extrapolator.cli import main
from blackhole_extrapolator.extrapolate import extrapolate, group_by_target
from blackhole_extrapolator.rename import signatures_from_debris, signatures_from_tree
import ast

KAREN = '''
from typing import Any, Dict, List, Tuple

class Node:
    def __init__(self, ident: str):
        self.ident = ident
    def propose(self) -> Dict[str, Any]:
        return {}

class Engine:
    def __init__(self, node_list: List[Node], ratio: float = 0.66):
        self.node_list = node_list
    def decide(self) -> Dict[str, Any]:
        return {}

def initialize_network_cluster(node_count: int, log_path: str = "/tmp/x") -> Tuple[List[Node], Dict[str, bytes]]:
    return [], {}
'''

JON = '''
nodes, keys = initialize_hybrid_cluster(node_count=3)
engine = Engine(nodes)
'''


def _write(root: Path, files: dict) -> None:
    for name, body in files.items():
        (root / name).write_text(textwrap.dedent(body))


def _renames(evidence):
    return [e for e in evidence if e.kind is EvidenceKind.RENAME_CANDIDATE]


def test_flattened_karen_is_found_from_jons_call_shape(tmp_path):
    _write(tmp_path, {"karen_source.py": " ".join(KAREN.split("\n")), "jon.py": JON})
    found = _renames(scan(tmp_path))
    assert len(found) == 1, [e.detail for e in found]
    detail = found[0].detail
    assert detail.startswith("`initialize_hybrid_cluster` may be `initialize_network_cluster(")
    assert "keyword ['node_count'] are parameters" in detail
    assert "2 values unpacked and it returns a 2-tuple" in detail
    assert "unpacked value 0 (`List[Node]`) is passed to `Engine` parameter `node_list`" in detail
    assert "names share ['cluster', 'initialize']" in detail
    assert "Not by name" in detail


def test_live_code_rename_that_missed_a_caller_is_found_too(tmp_path):
    _write(tmp_path, {"karen.py": KAREN, "jon.py": JON})
    found = _renames(scan(tmp_path))
    assert len(found) == 1 and "from karen.py" in found[0].detail


def test_class_rename_is_matched_on_keywords_and_methods(tmp_path):
    _write(tmp_path, {
        "karen.py": KAREN,
        "jon.py": "e = QuorumEngine(node_list=[], ratio=0.5)\nprint(e.decide())\n",
    })
    found = _renames(scan(tmp_path))
    assert len(found) == 1
    assert "`QuorumEngine` may be `Engine(" in found[0].detail
    assert "['decide'] are methods of the class" in found[0].detail


def test_a_coincidence_of_arity_alone_is_not_a_candidate(tmp_path):
    _write(tmp_path, {"karen.py": KAREN, "jon.py": "x = Nowhere(3)\n"})
    assert _renames(scan(tmp_path)) == []


def test_incompatible_arity_is_never_a_candidate(tmp_path):
    # Right keywords, but more arguments than the candidate can take.
    _write(tmp_path, {"karen.py": KAREN, "jon.py": "nodes, keys = initialize_hybrid_cluster(1, 2, 3, node_count=3)\n"})
    assert _renames(scan(tmp_path)) == []


def test_candidate_sits_in_the_undefined_names_void_and_is_flagged_undeterminable(tmp_path, capsys):
    _write(tmp_path, {"karen.py": KAREN, "jon.py": JON})
    evidence = scan(tmp_path)
    grouped = group_by_target(evidence)
    assert "initialize_hybrid_cluster" in grouped
    kinds = {e.kind for e in grouped["initialize_hybrid_cluster"]}
    assert kinds == {EvidenceKind.DANGLING_REFERENCE, EvidenceKind.RENAME_CANDIDATE}
    void = extrapolate(summary="x", anchors=[], evidence=grouped["initialize_hybrid_cluster"])
    assert any("rename candidate(s)" in u and "coincidence of shape" in u for u in void.undeterminable)
    assert void.kind.value == "never_built"
    main([str(tmp_path), "--json"])
    voids = json.loads(capsys.readouterr().out)
    target = next(v for v in voids if "initialize_hybrid_cluster" in v["summary"])
    assert any(e["kind"] == "rename_candidate" for e in target["evidence"])


def test_signatures_are_read_from_debris_and_from_trees():
    tree = ast.parse(KAREN)
    from_tree = {s.name: s for s in signatures_from_tree(Path("karen.py"), tree)}
    assert from_tree["Engine"].is_class and from_tree["Engine"].members == {"__init__", "decide"}
    assert [p[0] for p in from_tree["Engine"].params] == ["node_list", "ratio"]
    assert from_tree["Engine"].params[1][2] is True          # ratio has a default
    assert from_tree["initialize_network_cluster"].return_elements == ["List[Node]", "Dict[str, bytes]"]
    from blackhole_extrapolator.schema import NegativeEvidence
    debris = NegativeEvidence(
        kind=EvidenceKind.DEBRIS_STRUCTURE, file="flat.py",
        detail="ordered debris recovers the interface: ...\n"
               "    class Engine\n"
               "    Engine.__init__(self, node_list: List[Node], ratio: float = 0.66)\n"
               "    Engine.decide(self) -> Dict[str, Any]\n"
               "    run(cycles: int = 5) -> Tuple[int, str]\n"
               "    companion `flat_adapter.py` parses and shares 0 of 1 class name(s)")
    from_debris = {s.name: s for s in signatures_from_debris([debris])}
    assert set(from_debris) == {"Engine", "run"}
    assert from_debris["Engine"].members == {"__init__", "decide"}
    assert from_debris["Engine"].required == 1
    assert from_debris["run"].return_elements == ["int", "str"]
