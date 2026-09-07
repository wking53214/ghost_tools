"""blackhole_extrapolator.

The tests that matter most are the ones asserting what the tool REFUSES to
claim. A void outline is useful exactly as long as nobody mistakes it for a
recovery, and everything that keeps that true is a constraint rather than a
capability.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from blackhole_extrapolator import (
    Anchor,
    EvidenceKind,
    NegativeEvidence,
    Void,
    VoidKind,
    detect_dangling_names,
    detect_missing_imports,
    detect_orphaned_tests,
    detect_unparseable,
    extrapolate,
    group_by_target,
    infer_usage_invariants,
    scan,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body))
    return path


# ---------------------------------------------------------------------------
# What the tool refuses to claim
# ---------------------------------------------------------------------------

def test_a_void_that_infers_something_must_state_what_it_cannot_determine():
    """The constraint the whole type exists for. An outline presented without
    its limits reads as a recovery, and a recovery is the one thing nobody can
    produce here."""
    with pytest.raises(ValueError, match="cannot determine"):
        Void(kind=VoidKind.NEVER_BUILT, summary="x", anchors=(), evidence=(),
             must_define=("attr",), undeterminable=())


def test_a_void_that_infers_nothing_may_say_nothing():
    """Naming an absence without constraining its shape is a legitimate
    result, not a failure."""
    void = Void(kind=VoidKind.NEVER_BUILT, summary="something is missing",
                anchors=(), evidence=())
    assert void.inferred_anything is False


def test_the_implementation_is_always_undeterminable():
    """Not a limitation of this implementation -- it is what an absence is.
    More callers refine the interface and never reveal the behaviour."""
    void = extrapolate(
        summary="x", kind=VoidKind.DESTROYED,
        evidence=[NegativeEvidence(EvidenceKind.DANGLING_REFERENCE,
                                   "`Thing` is used but never defined. "
                                   "Callers require attributes: read ['a']",
                                   "f.py", 1)],
    )
    joined = " ".join(void.undeterminable)
    assert "the implementation" in joined
    assert "no surviving caller exercises" in joined
    assert "whether the original was correct" in joined


def test_the_package_emits_no_code():
    """There is deliberately no generator anywhere. A file that fills the hole
    while carrying the name of what was lost is indistinguishable from a
    recovery, and the moment the tool can write one somebody will commit its
    output as though the original had been found."""
    import blackhole_extrapolator as pkg

    banned = {"generate", "emit", "stub", "scaffold", "synthesize",
              "reconstruct", "rebuild", "write_source", "fix"}
    exported = {name.lower() for name in pkg.__all__}
    assert not (banned & exported), f"code-emitting export: {banned & exported}"


def test_render_is_not_valid_source():
    """Someone who wants a stub can write one from the outline in a minute.
    Nobody can paste the outline into a file and have it look like the thing
    that was lost."""
    import ast

    void = extrapolate(
        summary="`Thing` is reached for and is not there",
        evidence=[NegativeEvidence(EvidenceKind.DANGLING_REFERENCE,
                                   "`Thing` is used but never defined. "
                                   "Callers require attributes: read ['a', 'b']",
                                   "f.py", 3)],
    )
    with pytest.raises(SyntaxError):
        ast.parse(void.render())


def test_shape_confidence_is_about_the_outline_not_the_reconstruction():
    """Two different questions, and conflating them turns a confident outline
    into a confident forgery. Confidence rises with corroborating evidence
    kinds; it never reaches certainty about contents."""
    one = extrapolate(summary="x", evidence=[
        NegativeEvidence(EvidenceKind.DANGLING_REFERENCE, "`T` used", "f.py", 1)])
    two = extrapolate(summary="x", evidence=[
        NegativeEvidence(EvidenceKind.DANGLING_REFERENCE, "`T` used", "f.py", 1),
        NegativeEvidence(EvidenceKind.ORPHANED_TEST, "test imports `T`", "t.py", 1)])
    assert two.shape_confidence > one.shape_confidence
    assert two.shape_confidence <= 1.0


# ---------------------------------------------------------------------------
# Reading the shape out of the absence
# ---------------------------------------------------------------------------

def test_callers_describe_the_interface_they_require(tmp_path):
    source = _write(tmp_path, "caller.py", """
        def check():
            if REGISTRY.threshold > 0.8:
                REGISTRY.counter = REGISTRY.counter + 1
            return REGISTRY.label
    """)
    evidence = [e for e in detect_dangling_names(source) if "REGISTRY" in e.detail]
    assert evidence
    detail = evidence[0].detail
    for attribute in ("threshold", "counter", "label"):
        assert attribute in detail
    assert "written" in detail and "counter" in detail.split("written")[1]


def test_a_written_attribute_is_distinguished_from_a_read_one(tmp_path):
    """An attribute only ever read could be a property, a constant, or a
    method. One that is assigned to is mutable state -- a much stronger
    constraint on what the missing thing must be."""
    source = _write(tmp_path, "c.py", """
        def f():
            x = STATE.readonly
            STATE.mutable = 1
    """)
    detail = [e for e in detect_dangling_names(source) if "STATE" in e.detail][0].detail
    assert "readonly" in detail.split("written")[0]
    assert "mutable" in detail.split("written")[1]


def test_invariants_follow_a_single_local_alias(tmp_path):
    """Callers almost never subscript an attribute in place -- they bind it to
    a local first. Found on the real SYSTEM_GLOBALS void: attribute names came
    out immediately and every type constraint was one assignment out of
    reach."""
    source = _write(tmp_path, "c.py", """
        def check():
            vectors = GLOBALS.trajectory
            if vectors["Resource_Scarcity"] > 0.8:
                return True
    """)
    invariants = infer_usage_invariants(source.read_text(), "GLOBALS")
    joined = " ".join(invariants)
    assert "trajectory" in joined
    assert "Resource_Scarcity" in joined
    assert "numeric" in joined


def test_a_rebound_alias_is_dropped_rather_than_followed(tmp_path):
    """Following a name that later points at something else would attribute a
    constraint to the missing object that belongs to whatever replaced it --
    worse than seeing no constraint at all."""
    source = _write(tmp_path, "c.py", """
        def f():
            v = GLOBALS.trajectory
            v = something_else()
            return v["Injected_Key"]
    """)
    invariants = infer_usage_invariants(source.read_text(), "GLOBALS")
    assert not any("Injected_Key" in i for i in invariants)


def test_a_clamped_write_reveals_type_and_bound(tmp_path):
    source = _write(tmp_path, "c.py", """
        def f(delta):
            STATE.debt = max(0.0, STATE.debt - delta)
    """)
    invariants = infer_usage_invariants(source.read_text(), "STATE")
    joined = " ".join(invariants)
    assert "debt" in joined and "writable" in joined and "floor" in joined


# ---------------------------------------------------------------------------
# Not inventing voids
# ---------------------------------------------------------------------------

def test_a_wildcard_import_suppresses_dangling_analysis(tmp_path):
    """After `from x import *` any name might legitimately be bound. Reporting
    those as voids buries the real ones in noise."""
    source = _write(tmp_path, "c.py", """
        from os.path import *
        def f():
            return join("a", "b")
    """)
    assert list(detect_dangling_names(source)) == []


def test_builtins_and_locals_are_not_voids(tmp_path):
    source = _write(tmp_path, "c.py", """
        def f(items):
            total = len(items)
            return [x for x in range(total) if isinstance(x, int)]
    """)
    assert list(detect_dangling_names(source)) == []


def test_a_conditionally_defined_name_is_not_a_void(tmp_path):
    """Over-collecting bound names is deliberate: a false void sends someone
    hunting for code that was never lost."""
    source = _write(tmp_path, "c.py", """
        import sys
        if sys.platform == "linux":
            HELPER = 1
        def f():
            return HELPER
    """)
    assert not [e for e in detect_dangling_names(source) if "HELPER" in e.detail]


def test_a_real_third_party_import_is_not_a_missing_module(tmp_path):
    source = _write(tmp_path, "c.py", "import json\nimport pathlib\n")
    assert list(detect_missing_imports(source, [tmp_path])) == []


# ---------------------------------------------------------------------------
# Destroyed artifacts
# ---------------------------------------------------------------------------

def test_a_flattened_file_is_recognised_as_destroyed(tmp_path):
    """The specimen case the tool is named for: real content whose line breaks
    were destroyed by a paste through a chat interface. The bytes survive and
    the program does not."""
    flattened = tmp_path / "flat.py"
    flattened.write_text("from __future__ import annotations import os "
                         + "def f(): return 1 " * 200)
    evidence = list(detect_unparseable(flattened))
    assert evidence
    assert "FLATTENED" in evidence[0].detail
    assert "not mechanically recoverable" in evidence[0].detail


def test_a_parseable_file_produces_no_destruction_evidence(tmp_path):
    ok = _write(tmp_path, "ok.py", "def f():\n    return 1\n")
    assert list(detect_unparseable(ok)) == []


def test_a_short_broken_file_is_not_called_flattened(tmp_path):
    """A syntax error is not the same event as a paste that destroyed every
    line break, and conflating them mislabels an ordinary typo as a lost
    artifact."""
    broken = _write(tmp_path, "b.py", "def f(:\n")
    evidence = list(detect_unparseable(broken))
    assert evidence and "FLATTENED" not in evidence[0].detail


# ---------------------------------------------------------------------------
# Orphaned tests
# ---------------------------------------------------------------------------

def test_an_orphaned_test_encodes_the_expected_interface(tmp_path):
    """Unusually strong evidence: a test says not only what the missing thing
    was called but what it was supposed to do."""
    test = _write(tmp_path, "test_gone.py",
                  "from vanished_module import Engine, run\n")
    evidence = list(detect_orphaned_tests([test], [tmp_path]))
    assert evidence
    assert "vanished_module" in evidence[0].detail
    assert "Engine" in evidence[0].detail and "run" in evidence[0].detail


# ---------------------------------------------------------------------------
# Grouping and classification
# ---------------------------------------------------------------------------

def test_marks_from_one_absence_group_into_one_void():
    """Reporting them separately turns a single missing module into four
    unrelated complaints, and loses that the callers together describe a
    bigger surface than any one of them does."""
    evidence = [
        NegativeEvidence(EvidenceKind.DANGLING_REFERENCE, "`Shared` used", "a.py", 1),
        NegativeEvidence(EvidenceKind.DANGLING_REFERENCE, "`Shared` used", "b.py", 2),
        NegativeEvidence(EvidenceKind.DANGLING_REFERENCE, "`Other` used", "c.py", 3),
    ]
    grouped = group_by_target(evidence)
    assert len(grouped["Shared"]) == 2
    assert len(grouped["Other"]) == 1


def test_an_outline_from_several_files_is_marked_partial():
    """An outline built from callers is a lower bound on what existed, never
    an inventory of it."""
    void = extrapolate(
        summary="x",
        evidence=[NegativeEvidence(EvidenceKind.DANGLING_REFERENCE, "`T` used", "a.py", 1)],
        also_referenced_elsewhere=True)
    assert void.partial and "lower bound" in void.partial_reason


def test_two_anchors_facing_one_gap_beat_one():
    """One anchor gives a silhouette. Two facing each other across the same
    gap give a contract, because whatever is missing must accept one side's
    output and produce the other's input."""
    evidence = [NegativeEvidence(EvidenceKind.DANGLING_REFERENCE, "`T` used", "a.py", 1)]
    one = extrapolate(summary="x", evidence=evidence,
                      anchors=[Anchor("A", "a.py", provides=("Event",))])
    two = extrapolate(summary="x", evidence=evidence, anchors=[
        Anchor("A", "a.py", provides=("Event",)),
        Anchor("B", "b.py", requires=("Verdict",))])
    assert two.shape_confidence > one.shape_confidence
    assert two.must_accept == ("Event",) and two.must_return == ("Verdict",)


def test_an_unrealised_connection_says_it_may_never_have_existed():
    """Both sides fitting is not evidence that anything joined them."""
    void = extrapolate(
        summary="x", kind=VoidKind.UNREALISED,
        evidence=[NegativeEvidence(EvidenceKind.SHAPE_COMPLEMENTARITY,
                                   "`A` emits what `B` needs", "a.py", 1)])
    assert any("never intended" in u or "not evidence" in u
               for u in void.undeterminable)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def test_void_ids_are_content_hashes_not_counters():
    """A counter renumbers every run depending on detector order, which makes
    a void impossible to track across runs or suppress once reviewed."""
    def build():
        return extrapolate(summary="`T` is missing", evidence=[
            NegativeEvidence(EvidenceKind.DANGLING_REFERENCE, "`T` used", "a.py", 1)])

    assert build().id == build().id
    assert build().id.startswith("void-")

    other = extrapolate(summary="`U` is missing", evidence=[
        NegativeEvidence(EvidenceKind.DANGLING_REFERENCE, "`U` used", "a.py", 1)])
    assert other.id != build().id


def test_scan_finds_evidence_across_a_tree(tmp_path):
    _write(tmp_path, "a.py", "def f():\n    return MISSING_THING.value\n")
    _write(tmp_path, "b.py", "def g():\n    return 1\n")
    kinds = {e.kind for e in scan(tmp_path)}
    assert EvidenceKind.DANGLING_REFERENCE in kinds


# ---------------------------------------------------------------------------
# Destroyed residue -- the debris field
# ---------------------------------------------------------------------------

def test_debris_survives_in_a_file_that_no_longer_parses(tmp_path):
    """You cannot see inside the object; the debris field is measurable."""
    from blackhole_extrapolator import detect_destroyed_residue

    flat = tmp_path / "flat.py"
    flat.write_text("class Alpha: def run(self): pass class Beta: def stop(self): pass "
                    + "x " * 300)
    evidence = list(detect_destroyed_residue(flat))
    assert evidence
    assert "Alpha" in evidence[0].detail and "Beta" in evidence[0].detail


def test_residue_is_not_read_from_a_file_that_parses(tmp_path):
    """On a working module the AST is authoritative, and regex over source
    text cannot tell a class definition from the same word in a docstring."""
    from blackhole_extrapolator import detect_destroyed_residue

    ok = tmp_path / "ok.py"
    ok.write_text('"""Mentions class Ghost in prose."""\nVALUE = 1\n')
    assert list(detect_destroyed_residue(ok)) == []


def test_a_file_that_parses_to_nothing_is_still_destroyed(tmp_path):
    """Parsing is not proof of survival, and this is not hypothetical.

    TOUCHSTONE's canonical silent-pass specimen is a flattened file whose
    single line begins with `#`, so Python reads the whole 11,700 bytes as
    one comment: it imports cleanly, raises nothing, defines zero names. The
    first version of this detector returned early on it -- fooled by exactly
    the property that specimen exists to catch, on the first real run against
    the corpus."""
    from blackhole_extrapolator import detect_destroyed_residue

    commented = tmp_path / "silent.py"
    commented.write_text("# class Alpha: def run(self): pass class Beta: pass "
                         + "filler " * 200)
    evidence = list(detect_destroyed_residue(commented))
    assert evidence, "a module that parses to nothing was treated as intact"
    assert "Alpha" in evidence[0].detail


def test_an_empty_file_is_not_reported_as_destroyed(tmp_path):
    """Nothing there and nothing lost are different states."""
    from blackhole_extrapolator import detect_destroyed_residue

    empty = tmp_path / "empty.py"
    empty.write_text("\n  \n")
    assert list(detect_destroyed_residue(empty)) == []


def test_residue_states_what_it_cannot_support(tmp_path):
    """Names only. Structure, nesting, and which tokens were live code rather
    than docstring examples are all destroyed, and a reader who is not told
    that will read an inventory as an architecture."""
    from blackhole_extrapolator import detect_destroyed_residue

    flat = tmp_path / "f.py"
    flat.write_text("class A: def b(self): pass " + "z " * 300)
    detail = list(detect_destroyed_residue(flat))[0].detail
    assert "Names only" in detail
    assert "docstring examples" in detail


# ---------------------------------------------------------------------------
# Dangling references in debris
# ---------------------------------------------------------------------------

def test_dangling_references_are_recovered_from_an_unparseable_file(tmp_path):
    """detect_dangling_names needs an AST and returns nothing without one --
    which silently excludes exactly the files most likely to be surrounded by
    voids.

    Found by hand on a real archive skeleton: 2.7 KB, indentation flattened to
    a uniform one space so nesting depth is gone and no mechanical repair is
    possible, instantiating seven types it never defines and calling methods
    on them. All legible; none of it reachable through the AST path."""
    from blackhole_extrapolator import detect_dangling_in_debris

    broken = tmp_path / "skeleton.py"
    broken.write_text(
        "class Pipeline:\n"
        " def init(self) -> None:\n"
        " self.filter = KalmanFilter()\n"
        " def tick(self, snap: VitalSnapshot):\n"
        " self.filter.predict()\n"
        " self.filter.update(snap)\n"
    )
    evidence = list(detect_dangling_in_debris(broken))
    found = {e.detail.split("`")[1] for e in evidence}
    assert "KalmanFilter" in found
    assert "VitalSnapshot" in found          # type annotation counts

    kalman = next(e for e in evidence if "KalmanFilter" in e.detail)
    assert "predict" in kalman.detail and "update" in kalman.detail


def test_debris_dangling_is_not_run_on_a_file_that_parses(tmp_path):
    """Where an AST exists it is authoritative and regex would be strictly
    worse."""
    from blackhole_extrapolator import detect_dangling_in_debris

    ok = tmp_path / "ok.py"
    ok.write_text("class A:\n    def f(self):\n        self.x = Missing()\n")
    assert list(detect_dangling_in_debris(ok)) == []


def test_a_name_mentioned_only_in_prose_is_not_evidence(tmp_path):
    """Narrow on purpose: constructor calls, annotations and method calls on
    a bound field. A capitalised word in a docstring is not a reach for
    something."""
    from blackhole_extrapolator import detect_dangling_in_debris

    broken = tmp_path / "b.py"
    broken.write_text('"""Discusses SomeGrandTheory at length."""\n'
                      "class A:\n def f(self):\n self.x = RealThing()\n")
    found = {e.detail.split("`")[1] for e in detect_dangling_in_debris(broken)}
    assert "RealThing" in found
    assert "SomeGrandTheory" not in found


def test_a_type_defined_in_the_same_debris_is_not_a_void(tmp_path):
    from blackhole_extrapolator import detect_dangling_in_debris

    broken = tmp_path / "b.py"
    broken.write_text("class Helper:\n pass\n"
                      "class Main:\n def init(self):\n self.h = Helper()\n")
    found = {e.detail.split("`")[1] for e in detect_dangling_in_debris(broken)}
    assert "Helper" not in found


def test_a_type_imported_in_the_same_debris_is_not_a_void(tmp_path):
    """Found on the first real specimen this was pointed at.

    quorum_state_governance_source.py -- 14 KB, zero newlines -- reported
    `Any` as missing code. Its `from typing import (...)` was sitting in the
    same debris a few hundred bytes away. Only class definitions counted as
    "defined", so every imported type read as an absence.

    A name the file imports is resolved by that import. If the module itself
    is gone that is a MISSING_MODULE void, reported once against the module
    rather than once per name it supplied.
    """
    from blackhole_extrapolator import detect_dangling_in_debris

    broken = tmp_path / "flat.py"
    broken.write_text(
        "from typing import ( Any, Dict, Optional ) "
        "from dataclasses import dataclass, field "
        "import hashlib "
        "class Kernel: def run(self, payload: Any, opts: Dict) -> Optional: "
        "self.engine = QuorumEngine() self.engine.decide()"
    )
    found = {e.detail.split("`")[1] for e in detect_dangling_in_debris(broken)}

    assert "Any" not in found
    assert "Dict" not in found
    assert "Optional" not in found
    # The genuine void is still reported.
    assert "QuorumEngine" in found


def test_an_import_list_does_not_swallow_the_next_statement(tmp_path):
    """With the line breaks gone, `from a import b from c import d` is one run
    of characters. A greedy word match would treat `class`, `def` and the next
    module name as imported names and suppress real voids."""
    from blackhole_extrapolator import detect_dangling_in_debris
    from blackhole_extrapolator.detect import _debris_imported_names

    text = ("from dataclasses import dataclass, field "
            "from datetime import datetime, timezone "
            "class Thing: def f(self): self.a = Ledger()")
    names = _debris_imported_names(text)

    assert {"dataclass", "field", "datetime", "timezone"} <= names
    assert "class" not in names and "from" not in names
    assert "Thing" not in names and "Ledger" not in names

    broken = tmp_path / "flat2.py"
    broken.write_text(text)
    found = {e.detail.split("`")[1] for e in detect_dangling_in_debris(broken)}
    assert "Ledger" in found


@pytest.mark.parametrize("text,expected", [
    # The common shape in real debris: a bare import running straight into a
    # definition, with no punctuation between them.
    ("from typing import Any, Dict class Foo: def g(self): self.x = Ledger()",
     {"Any", "Dict"}),
    ("from typing import Optional def h(p: Optional): pass", {"Optional"}),
    ("from typing import Any; x = Thing()", {"Any"}),
    ("from typing import ( Any, Dict, ) class K: pass", {"Any", "Dict"}),
])
def test_an_import_list_ends_where_the_next_definition_begins(text, expected):
    """Both directions of this are failures and they are not symmetric.

    Dropping a name puts back the false positive the import handling exists to
    remove. Absorbing `class`/`def` or the name after it suppresses a real
    void, which is the worse direction and the silent one.
    """
    from blackhole_extrapolator.detect import _debris_imported_names

    names = _debris_imported_names(text)
    assert expected <= names
    assert not ({"class", "def", "Foo", "K", "Ledger", "Thing"} & names)
