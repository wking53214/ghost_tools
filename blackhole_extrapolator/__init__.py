"""blackhole_extrapolator -- rebuild dead things from what isn't there.

A black hole is never observed. It is inferred entirely from what it does to
the things around it, and its interior is not recoverable at any resolution.
This tool applies that to missing code: it reconstructs the *shape* of an
absence from the marks the absence left on the code that survived it.

    ghost_buster              finds things that are present and wrong
    ghost_writer              documents the ones worth documenting
    blackhole_extrapolator    outlines the ones that are not there at all

Not an adapter, and not a seam. Both of those connect two things that exist,
where you can read both sides and test the join. Here the connector itself
went up in smoke -- a flattened paste that no longer parses, a module three
files import and nothing provides, a name every caller expects and nothing
defines. There is nothing to read. The only evidence is the shape of the hole.

The output is a `Void`: a specification of an absence, carrying both what the
surrounding code forces to be true and -- always, enforced at construction --
what it cannot determine. There is no code generation anywhere in this
package, by design. A file that fills the hole while carrying the name of what
was lost is indistinguishable from a recovery and is not one.
"""

from .detect import (
    detect_dangling_names,
    detect_missing_imports,
    detect_orphaned_tests,
    detect_unparseable,
    scan,
)
from .extrapolate import extrapolate, group_by_target, infer_usage_invariants
from .schema import Anchor, EvidenceKind, NegativeEvidence, Void, VoidKind

__all__ = [
    "Anchor", "EvidenceKind", "NegativeEvidence", "Void", "VoidKind",
    "scan", "detect_dangling_names", "detect_missing_imports",
    "detect_orphaned_tests", "detect_unparseable",
    "extrapolate", "group_by_target", "infer_usage_invariants",
]
