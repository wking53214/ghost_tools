"""The same file in several places, no longer saying the same thing.

WHAT duplicate_file CANNOT SEE

`duplicate_file` groups files by content hash, so it finds copies that are
byte-identical and nothing else. The moment somebody fixes a bug in one copy
and not the others, the hashes diverge and the group disappears from the
report -- exactly when it starts mattering. The detector goes quiet at the
point the problem begins.

Measured 2026-09-10 across 24 live repositories: 111 groups of files share a
complete top-level name set, and 29 of those groups have drifted. None of
the 29 is visible to `duplicate_file`.

    citadel_v1.1_copy1.py  9,011b  |  citadel_v1.2.py  9,420b  |  citadel_v1.1_copy2.py  10,062b
    test_api_server_v2.py  vendored into four places: 36,312 x3 and 39,263
    ast_graph_extractor    five copies, 5,982b to 11,283b

WHAT COUNTS AS THE SAME FILE

The same set of top-level definitions, by name, with at least
MINIMUM_DEFINITIONS of them. Equality of the whole set rather than overlap,
because two unrelated modules sharing three helper names is a coincidence
and two modules sharing all fourteen is a copy.

WHAT COUNTS AS DRIFT

Each definition is hashed by its STRUCTURE -- ast.dump without attributes --
so reformatting, comments and line numbers do not register as drift and a
changed condition does. That splits the groups in two, and the split is the
finding rather than a heuristic about intent:

  every definition structurally identical    the copies still agree, and the
                                             difference is whitespace,
                                             comments or imports. DUPLICATION,
                                             MINOR: a tidiness problem.

  some definition differs                    two implementations of one
                                             thing that no longer agree, and
                                             a fix applied to one did not
                                             reach the others. PARALLEL
                                             IMPLEMENTATION, MAJOR.

That second verdict is why this module exists. Until now the
parallel_implementation category had exactly one producer, semantic.py,
whose findings are REASONED by construction because an LLM produced them.
This is the mechanical half, and it is CONFIRMED because a structural hash
either matches or it does not.

WHAT IT DOES NOT DO

Report a byte-identical group. That is `duplicate_file`'s finding, and two
detectors reporting one fact is how a report doubles its own noise -- the
same reason `duplicate_file` was given a group of its own in v0.9, when
`near_duplicate_function` was drowning in it.

Guess whether the copies are deliberate. `citadel_v1.1` beside
`citadel_v1.2` may well be an intended archive. The finding says which
definitions differ and leaves the judgement where it belongs.
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from . import corpus
from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "drifted_copy"

# Below this, a shared name set is a coincidence rather than a copy. Three
# is the smallest number that stops `main`/`setup`/`run` trios from grouping
# unrelated scripts.
MINIMUM_DEFINITIONS = 3

# How many differing definitions to name before summarising the rest.
SHOWN = 6


def _structure(node: ast.AST) -> str:
    """A definition's shape, with formatting and position removed.

    `include_attributes=False` is what makes reformatting invisible and a
    changed condition visible. Without it every copy differs, because
    line numbers always do.
    """
    return hashlib.sha256(
        ast.dump(node, annotate_fields=True, include_attributes=False).encode()
    ).hexdigest()


def _definitions(path: Path) -> Dict[str, str] | None:
    tree = corpus.parse(path)
    if tree is None:
        return None
    return {node.name: _structure(node) for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}


@dataclass(frozen=True)
class Copies:
    """One group of files defining the same names, and where they disagree."""

    paths: Tuple[Path, ...]
    agreed: Tuple[str, ...]
    differing: Tuple[str, ...]

    @property
    def has_drifted(self) -> bool:
        return bool(self.differing)

    @property
    def definitions(self) -> int:
        return len(self.agreed) + len(self.differing)


def find_copies(files: Sequence[Path]) -> List[Copies]:
    """Groups of files sharing a full top-level name set, byte-identical
    groups excluded."""
    by_names: Dict[frozenset, List[Tuple[Path, Dict[str, str]]]] = defaultdict(list)
    for path in (Path(f) for f in files):
        definitions = _definitions(path)
        if definitions is None or len(definitions) < MINIMUM_DEFINITIONS:
            continue
        by_names[frozenset(definitions)].append((path, definitions))

    out: List[Copies] = []
    for names, members in by_names.items():
        if len(members) < 2:
            continue
        digests = {_file_digest(path) for path, _ in members}
        if len(digests) == 1:
            continue          # duplicate_file's finding, not this one
        differing = sorted(
            name for name in names
            if len({definitions[name] for _, definitions in members}) > 1)
        out.append(Copies(
            paths=tuple(sorted(path for path, _ in members)),
            agreed=tuple(sorted(set(names) - set(differing))),
            differing=tuple(differing),
        ))
    return sorted(out, key=lambda c: str(c.paths[0]))


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unreadable:" + str(path)


def detect_drifted_copies(files: Sequence[Path]) -> List[Finding]:
    findings: List[Finding] = []
    for group in find_copies(files):
        drifted = group.has_drifted
        shown = ", ".join(f"`{n}`" for n in group.differing[:SHOWN])
        more = (f" (+{len(group.differing) - SHOWN} more)"
                if len(group.differing) > SHOWN else "")
        where = "\n".join(f"  {p}" for p in group.paths)
        findings.append(Finding(
            detector=DETECTOR,
            category=(Category.PARALLEL_IMPLEMENTATION if drifted
                      else Category.DUPLICATION),
            layer=Layer.MECHANICAL,
            severity=Severity.MAJOR if drifted else Severity.MINOR,
            status=Status.CONFIRMED,
            summary=(
                f"{len(group.paths)} copies of {group.paths[0].name} define the "
                f"same {group.definitions} name(s); "
                + (f"{len(group.differing)} of them differ"
                   if drifted else "all of them agree")
            ),
            detail=(
                f"{where}\n\n"
                + (f"These copies no longer agree. {shown}{more} "
                   f"{'differs' if len(group.differing) == 1 else 'differ'} "
                   "structurally between them, so a change made to one did not "
                   "reach the others. Comments, formatting and line numbers are "
                   "excluded from the comparison, so this is a difference in "
                   "what the code does.\n"
                   if drifted else
                   "Every definition is structurally identical; the files differ "
                   "only in comments, formatting or imports. That is a tidiness "
                   "problem rather than a behavioural one, which is why it is "
                   "MINOR.\n")
                + "Byte-identical copies are reported by `duplicate_file` "
                  "instead and are deliberately not repeated here. Whether the "
                  "copies are meant to exist is yours to judge: a `_v1.1` "
                  "beside a `_v1.2` may be an intended archive. What this says "
                  "is which definitions stopped matching."
            ),
            evidence=Evidence(file=str(group.paths[0]),
                              related_files=[str(p) for p in group.paths]),
            attributes={"copies": str(len(group.paths)),
                        "differing": str(len(group.differing))},
        ))
    return findings
