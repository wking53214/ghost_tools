"""What a void is, and what may be said about one.

A black hole is never observed. It is inferred entirely from what it does to
the things around it -- the orbits it bends, the light it lenses, an absence
whose properties are fixed by its periphery and nothing else. Its mass and
spin are recoverable that way. Its interior is not, ever, and no amount of
better instruments changes that.

This module holds the same distinction for missing code, because the whole
value of the tool depends on not blurring it:

    inferred        what the surrounding code forces to be true
    undeterminable  what the surrounding code cannot decide, named explicitly

`ghost_buster` finds things that are present and wrong. This finds things that
are absent and shaped. The two share a discipline -- stable content-hash IDs,
evidence pointing at real files and lines, no counters -- and deliberately do
not share the `Finding` type. A Finding says "here is a problem in this code".
A Void says "here is the outline of something that is not in this code", which
is a different claim with different rules about what may be asserted.

Not an adapter, and not a seam
------------------------------
Adapter construction and seam building both connect two things that exist. You
can read both sides, run both sides, and test the join against both.

A void has no such luxury. The connector itself went up in smoke -- a flattened
paste that no longer parses, a module referenced by three files and present in
none, a name every caller expects and nothing defines. There is nothing to
read. The only evidence is the shape of the hole.

So a Void is a specification of an absence. It is never an implementation, and
this module provides no way to emit one: a file that fills the hole while
claiming to be what was there is the single worst outcome available here,
because it is indistinguishable from recovery and is not recovery.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class EvidenceKind(str, Enum):
    """The ways an absence leaves a mark on what remains.

    Each kind is a different way of seeing the hole. Together they constrain
    its shape; none of them ever reveals its contents.
    """

    # A name used and never defined. The strongest signal there is: callers
    # tell you the attribute names, the operations, and often the types.
    DANGLING_REFERENCE = "dangling_reference"

    # Something produces a value nothing reads. Whatever consumed it is gone.
    UNCONSUMED_OUTPUT = "unconsumed_output"

    # Something requires an input nothing in reach produces.
    UNSATISFIED_REQUIREMENT = "unsatisfied_requirement"

    # An import of a module that does not exist anywhere.
    MISSING_MODULE = "missing_module"

    # A test exercising something that is not there. Tests are unusually good
    # evidence: they encode the expected interface AND the expected behaviour.
    ORPHANED_TEST = "orphaned_test"

    # Documentation, comments or a README describing something with no
    # implementation. Weaker -- documents overstate -- but it names things.
    DOCUMENTED_NOT_IMPLEMENTED = "documented_not_implemented"

    # Two components whose shapes fit and which nothing connects. The weakest
    # kind, and the only one that may indicate a useful connection that never
    # existed rather than one that was lost.
    SHAPE_COMPLEMENTARITY = "shape_complementarity"

    # Identifier tokens still sitting in a file that no longer parses. The
    # debris field of a destroyed artifact: it names what was there and
    # nothing about how any of it fitted together.
    DESTROYED_RESIDUE = "destroyed_residue"


class VoidKind(str, Enum):
    """What sort of absence this is, which decides how much may be claimed."""

    # It existed and was destroyed: a flattened paste, a deleted module still
    # referenced. Reconstruction has a target, even if unreachable.
    DESTROYED = "destroyed"

    # It was referenced but may never have existed. Callers still constrain
    # its shape; there may be nothing to be faithful to.
    NEVER_BUILT = "never_built"

    # Both sides exist and fit, nothing joins them. Not lost -- unbuilt, and
    # possibly deliberately.
    UNREALISED = "unrealised"


def _stable_id(*parts: str) -> str:
    """Content hash, matching ghost_buster's discipline.

    A counter renumbers every run depending on detector order, which makes
    a void impossible to track across runs or suppress once reviewed.
    """
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"void-{digest[:12]}"


@dataclass(frozen=True)
class NegativeEvidence:
    """One mark the absence left on something that still exists.

    `file` and `line` point at the surviving code, never at the missing
    thing -- there is no file to point at, and pretending otherwise is how a
    void report starts reading like a bug report about a file nobody can open.
    """

    kind: EvidenceKind
    detail: str
    file: str
    line: Optional[int] = None
    observed: str = ""     # the literal text that shows the mark

    def as_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["kind"] = self.kind.value
        return out


@dataclass(frozen=True)
class Anchor:
    """A surviving thing with a hole facing it.

    Anchors are what make the shape inferable at all. One anchor gives you a
    silhouette; two facing each other across the same gap give you a contract,
    because whatever is missing must accept what one emits and produce what
    the other needs.
    """

    name: str
    file: str
    provides: tuple[str, ...] = ()   # names/shapes it exposes toward the void
    requires: tuple[str, ...] = ()   # names/shapes it needs from the void

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Void:
    """The inferred outline of something that is not there.

    Read the two lists together or not at all. `inferred` without
    `undeterminable` is a specification pretending to be a recovery, and that
    is the failure this whole type exists to prevent.
    """

    kind: VoidKind
    summary: str
    anchors: tuple[Anchor, ...]
    evidence: tuple[NegativeEvidence, ...]

    # What the surrounding code forces to be true.
    must_define: tuple[str, ...] = ()      # names callers require to exist
    must_accept: tuple[str, ...] = ()      # inputs the producing side emits
    must_return: tuple[str, ...] = ()      # outputs the consuming side needs
    invariants: tuple[str, ...] = ()       # constraints visible in usage

    # What the surrounding code cannot decide. Never empty in practice; a
    # void reporting nothing undeterminable has stopped being honest.
    undeterminable: tuple[str, ...] = ()

    # How much of the shape the evidence actually pins down -- NOT a claim
    # about whether a reconstruction would be correct. Those are different
    # questions and conflating them is how a confident outline becomes a
    # confident forgery.
    shape_confidence: float = 0.0

    # A lower bound flag: other voids referencing the same absent thing mean
    # this outline is partial by construction.
    partial: bool = False
    partial_reason: str = ""

    id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _stable_id(
            self.kind.value, self.summary,
            *(a.file for a in self.anchors),
        ))
        if not 0.0 <= self.shape_confidence <= 1.0:
            raise ValueError(
                f"shape_confidence must be 0.0-1.0, got {self.shape_confidence}")
        if self.inferred_anything and not self.undeterminable:
            raise ValueError(
                "a Void that infers something must also state what it cannot "
                "determine -- an outline presented without its limits reads as "
                "a recovery, which is the one thing this type must never be "
                "mistaken for"
            )

    @property
    def inferred_anything(self) -> bool:
        return bool(self.must_define or self.must_accept
                    or self.must_return or self.invariants)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "summary": self.summary,
            "anchors": [a.as_dict() for a in self.anchors],
            "evidence": [e.as_dict() for e in self.evidence],
            "inferred": {
                "must_define": list(self.must_define),
                "must_accept": list(self.must_accept),
                "must_return": list(self.must_return),
                "invariants": list(self.invariants),
            },
            "undeterminable": list(self.undeterminable),
            "shape_confidence": self.shape_confidence,
            "partial": self.partial,
            "partial_reason": self.partial_reason,
        }

    def render(self) -> str:
        """A human-readable outline.

        Deliberately not valid source in any language. Someone who wants a
        stub can write one from this in a minute; nobody can paste this into
        a file and have it look like the thing that was lost.
        """
        lines = [
            f"VOID {self.id}  [{self.kind.value}]",
            f"  {self.summary}",
            "",
            f"  anchors ({len(self.anchors)}):",
        ]
        for anchor in self.anchors:
            lines.append(f"    - {anchor.name}  ({anchor.file})")
            if anchor.requires:
                lines.append(f"        needs:    {', '.join(anchor.requires)}")
            if anchor.provides:
                lines.append(f"        provides: {', '.join(anchor.provides)}")

        lines += ["", f"  INFERRED  (shape confidence {self.shape_confidence:.2f}):"]
        for label, values in (("must define", self.must_define),
                              ("must accept", self.must_accept),
                              ("must return", self.must_return),
                              ("invariants", self.invariants)):
            for value in values:
                lines.append(f"    {label:<12} {value}")
        if not self.inferred_anything:
            lines.append("    (nothing -- the evidence constrains no shape)")

        lines += ["", "  UNDETERMINABLE:"]
        for item in self.undeterminable:
            lines.append(f"    - {item}")

        if self.partial:
            lines += ["", f"  PARTIAL: {self.partial_reason}"]

        lines += ["", f"  negative evidence ({len(self.evidence)}):"]
        for item in self.evidence:
            where = f"{item.file}:{item.line}" if item.line else item.file
            lines.append(f"    [{item.kind.value}] {where}")
            lines.append(f"        {item.detail}")

        lines += [
            "",
            "  This is a specification of an absence, inferred from surrounding",
            "  code. It is not a recovery of what was there, and the difference",
            "  is not recoverable by trying harder.",
        ]
        return "\n".join(lines)
