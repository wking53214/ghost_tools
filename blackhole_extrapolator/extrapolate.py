"""Turning negative evidence into a bounded outline.

`detect.py` finds the marks an absence left. This decides what those marks
force to be true, and -- with equal care -- what they leave open.

The second half is the part that makes the tool usable rather than dangerous.
An outline offered without its limits is read as a recovery, and a recovery is
exactly what nobody can produce here. So `undeterminable` is populated on
every path through this module, and `Void.__post_init__` refuses to construct
a Void that inferred something and admitted nothing.

What can and cannot be inferred
--------------------------------
From callers you can recover an interface: names, arity, which attributes are
read, which are written, and often a type from how a value is used. Comparing
something against `0.8` makes it numeric; calling `max(0.0, x)` on it makes it
a float with a floor; subscripting it with a string makes it a mapping.

You cannot recover behaviour. `integrity_debt_balance` is decremented by a
drift delta and clamped at zero -- that is the caller's arithmetic, not the
missing object's. Whether the real object recomputed it, persisted it,
validated it, or emitted an event on change is invisible, and no amount of
additional callers makes it visible. That is not a limitation of this
implementation; it is what an absence is.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

from .schema import Anchor, EvidenceKind, NegativeEvidence, Void, VoidKind

# Confidence a single evidence kind contributes to how well the shape is
# pinned down. Not a probability that a reconstruction would be correct --
# those are different questions, and the docstring on Void.shape_confidence
# says so because conflating them turns a confident outline into a confident
# forgery.
_KIND_WEIGHT = {
    EvidenceKind.DANGLING_REFERENCE: 0.35,      # callers describe the interface
    EvidenceKind.ORPHANED_TEST: 0.30,           # tests describe interface AND behaviour
    EvidenceKind.MISSING_MODULE: 0.20,          # names it, sometimes its surface
    EvidenceKind.UNSATISFIED_REQUIREMENT: 0.15,
    EvidenceKind.UNCONSUMED_OUTPUT: 0.15,
    EvidenceKind.DOCUMENTED_NOT_IMPLEMENTED: 0.10,  # documents overstate
    EvidenceKind.SHAPE_COMPLEMENTARITY: 0.05,   # may be a connection never made
    # Names what existed and nothing about structure, so it constrains the
    # inventory strongly and the shape barely.
    EvidenceKind.DESTROYED_RESIDUE: 0.20,
    # Ordered headers with parameter lists: the interface, not the bodies.
    EvidenceKind.DEBRIS_STRUCTURE: 0.25,
}

_READS = re.compile(r"read \[([^\]]*)\]")
_WRITES = re.compile(r"written \[([^\]]*)\]")

# Things nothing outside the missing artifact can settle. Attached to every
# void because they are true of every void, and a reader who sees them listed
# stops expecting the tool to eventually overcome them.
_ALWAYS_UNDETERMINABLE = (
    "the implementation -- what the missing code actually did, as opposed to "
    "what its callers required of it",
    "any behaviour no surviving caller exercises",
    "internal state, lifecycle, persistence, and thread-safety",
    "whether the original was correct",
)


def _attributes_from_evidence(evidence: Iterable[NegativeEvidence]
                              ) -> tuple[set[str], set[str]]:
    """(read, written) attribute names recovered from dangling-reference detail."""
    reads: set[str] = set()
    writes: set[str] = set()
    for item in evidence:
        if item.kind is not EvidenceKind.DANGLING_REFERENCE:
            continue
        for pattern, sink in ((_READS, reads), (_WRITES, writes)):
            found = pattern.search(item.detail)
            if found:
                sink.update(
                    part.strip().strip("'\"")
                    for part in found.group(1).split(",") if part.strip()
                )
    return reads, writes


def _recovered_from_debris(evidence: Iterable[NegativeEvidence]) -> list[str]:
    """Signatures read back from DEBRIS_STRUCTURE detail, in token order.

    The first line of the detail is the summary and any `companion` line is
    commentary; everything else is one header per line, already rendered as
    `Class`, `Class.method(params) -> Ret` or `function(params)`.
    """
    out: list[str] = []
    for item in evidence:
        if item.kind is not EvidenceKind.DEBRIS_STRUCTURE:
            continue
        for line in item.detail.splitlines()[1:]:
            text = line.strip()
            if not text or text.startswith("companion "):
                continue
            if text.startswith("class "):
                text = text[len("class "):]
            if text not in out:
                out.append(text)
    return out


def infer_usage_invariants(source: str, target: str) -> list[str]:
    """Constraints the callers' own code forces on the missing thing.

    Read carefully: these are constraints on the *interface*, derived from how
    callers treat the values. `max(0.0, x)` proves the caller keeps the value
    non-negative. It does not prove the missing object did.
    """
    invariants: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return invariants

    seen: set[str] = set()

    def note(text: str) -> None:
        if text not in seen:
            seen.add(text)
            invariants.append(text)

    # Local aliases: `vectors = SYSTEM_GLOBALS.current_trajectory_vectors`.
    #
    # Without this the strongest constraints are invisible, because callers
    # almost never subscript an attribute in place -- they bind it to a local
    # first and work with that. Found on the real SYSTEM_GLOBALS void: the
    # attribute names came out immediately and every type constraint was one
    # assignment out of reach.
    #
    # Single assignment only, and dropped entirely if the local is ever
    # rebound. Following a name that later points at something else would
    # attribute a constraint to the missing object that belongs to whatever
    # replaced it, which is worse than seeing no constraint at all.
    alias_to_attr: dict[str, str] = {}
    rebound: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        if (isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == target):
            if tgt.id in alias_to_attr and alias_to_attr[tgt.id] != node.value.attr:
                rebound.add(tgt.id)
            alias_to_attr[tgt.id] = node.value.attr
        elif tgt.id in alias_to_attr:
            rebound.add(tgt.id)
    for name in rebound:
        alias_to_attr.pop(name, None)

    def attr_of(node: ast.AST) -> str | None:
        """Which attribute of the missing thing this expression refers to,
        whether directly or through a single local alias."""
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == target):
            return node.attr
        if isinstance(node, ast.Name):
            return alias_to_attr.get(node.id)
        return None

    for node in ast.walk(tree):
        # target.attr[<str>] -> that attribute is a mapping with those keys
        if isinstance(node, ast.Subscript):
            attr = attr_of(node.value)
            key = node.slice
            if attr and isinstance(key, ast.Constant) and isinstance(key.value, str):
                note(f"`{attr}` is a mapping; observed key {key.value!r}")

        # a value drawn from target.attr compared against a number -> numeric
        if isinstance(node, ast.Compare):
            left = node.left
            attr = None
            if isinstance(left, ast.Subscript):
                attr = attr_of(left.value)
                container = True
            else:
                attr = attr_of(left)
                container = False
            if attr:
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant) and isinstance(
                            comparator.value, (int, float)):
                        where = f"values in `{attr}`" if container else f"`{attr}`"
                        note(f"{where} are numeric (compared against "
                             f"{comparator.value})")

        # target.attr = max(0.0, ...) -> writable float with a floor
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in {"max", "min"}):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == target):
                    bound = node.value.args[0] if node.value.args else None
                    if isinstance(bound, ast.Constant):
                        word = "floor" if node.value.func.id == "max" else "ceiling"
                        note(f"`{tgt.attr}` is writable and numeric; callers "
                             f"hold it to a {word} of {bound.value}")
    return invariants


def extrapolate(
    *,
    summary: str,
    evidence: Sequence[NegativeEvidence],
    anchors: Sequence[Anchor] = (),
    kind: VoidKind = VoidKind.NEVER_BUILT,
    target: str | None = None,
    sources: Sequence[Path] = (),
    also_referenced_elsewhere: bool = False,
) -> Void:
    """Build the outline of one absence.

    `target` and `sources` are optional and only enable the invariant pass:
    given the name of the missing thing and the files that reach for it, the
    callers' own arithmetic and subscripting constrain its shape further.
    """
    reads, writes = _attributes_from_evidence(evidence)

    invariants: list[str] = []
    if target:
        for path in sources:
            try:
                invariants.extend(
                    infer_usage_invariants(path.read_text(errors="replace"), target))
            except OSError:
                continue
    # de-duplicate while keeping order
    invariants = list(dict.fromkeys(invariants))

    recovered = _recovered_from_debris(evidence)
    # Callers' attributes are sorted; recovered headers keep their token
    # order, which is the only structure a flattened file has left.
    must_define = tuple(sorted(reads | writes)) + tuple(
        item for item in recovered if item not in reads and item not in writes)
    must_accept = tuple(sorted(
        item for anchor in anchors for item in anchor.provides))
    must_return = tuple(sorted(
        item for anchor in anchors for item in anchor.requires))

    undeterminable = list(_ALWAYS_UNDETERMINABLE)
    if writes:
        undeterminable.append(
            f"what the missing thing did on write to {sorted(writes)} -- "
            "validation, persistence, or notification would all look "
            "identical from here"
        )
    if kind is VoidKind.DESTROYED:
        undeterminable.append(
            "how far the surviving callers exercised the original: an outline "
            "built from callers is a lower bound on what existed, never an "
            "inventory of it"
        )
    if recovered:
        undeterminable.append(
            "the bodies behind the recovered signatures; whether every header "
            "was live code rather than a docstring example; and the class a "
            "method belongs to, which is read from token order and is wrong "
            "for a paste that interleaved two files"
        )
    if kind is VoidKind.UNREALISED:
        undeterminable.append(
            "whether this connection was ever intended -- both sides fitting "
            "is not evidence that anything joined them"
        )
    if not must_define and not invariants:
        undeterminable.append(
            "the interface itself -- the evidence names an absence but does "
            "not constrain its shape"
        )

    kinds_present = {item.kind for item in evidence}
    confidence = min(1.0, sum(_KIND_WEIGHT.get(k, 0.0) for k in kinds_present))
    if len(anchors) >= 2:
        # Two anchors facing the same gap give a contract rather than a
        # silhouette: whatever is missing must accept one side's output and
        # produce the other's input.
        confidence = min(1.0, confidence + 0.15)
    if invariants:
        confidence = min(1.0, confidence + 0.10)

    return Void(
        kind=kind,
        summary=summary,
        anchors=tuple(anchors),
        evidence=tuple(evidence),
        must_define=must_define,
        must_accept=must_accept,
        must_return=must_return,
        invariants=tuple(invariants),
        undeterminable=tuple(undeterminable),
        shape_confidence=round(confidence, 3),
        partial=also_referenced_elsewhere,
        partial_reason=(
            "other files outside this analysis also reference the missing "
            "thing, so this outline is a lower bound on its surface"
            if also_referenced_elsewhere else ""
        ),
    )


def group_by_target(evidence: Sequence[NegativeEvidence]) -> dict[str, list[NegativeEvidence]]:
    """Cluster evidence by the name of the thing that is missing.

    Marks left by one absence in several files belong to one void. Reporting
    them separately turns a single missing module into four unrelated
    complaints and loses the fact that the callers, taken together, describe
    a bigger surface than any one of them does.
    """
    grouped: dict[str, list[NegativeEvidence]] = defaultdict(list)
    for item in evidence:
        if item.kind in (EvidenceKind.DESTROYED_RESIDUE, EvidenceKind.DEBRIS_STRUCTURE):
            # A destroyed file is its own void; its detail may name a
            # companion file, which is context, not the target.
            grouped[item.file].append(item)
            continue
        found = re.search(r"`([A-Za-z_][A-Za-z0-9_.]*)`", item.detail)
        grouped[found.group(1) if found else item.file].append(item)
    return dict(grouped)
