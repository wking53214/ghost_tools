"""mechanical.py -- Layer 1: deterministic, AST-based detectors.

Every detector here is a pure function of the files on disk: same input,
same output, every time. No API calls, no LLM, nothing probabilistic --
which is exactly why every finding this layer produces is Status.CONFIRMED
(see schema.py's module docstring for why that's enforced, not just a
convention).

Stdlib only (ast, hashlib) -- no third-party dependency for v0.1. This
intentionally does NOT try to out-do purpose-built tools like vulture,
radon, or jscpd; it exists to prove the detector-registry pattern end to
end with real, working, non-trivial detectors. Swapping in (or adding)
a real dedicated tool behind the same Finding-producing interface later
is a compatible change, not a rewrite.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Set

from .schema import Category, Evidence, Finding, Layer, Severity, Status

DetectorFn = Callable[[List[Path]], List[Finding]]

_REGISTRY: Dict[str, DetectorFn] = {}


def register(name: str):
    def decorator(fn: DetectorFn) -> DetectorFn:
        _REGISTRY[name] = fn
        return fn
    return decorator


def registered_detectors() -> Dict[str, DetectorFn]:
    return dict(_REGISTRY)


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Detector: dead_code -- module-level functions/classes defined but never
# referenced anywhere else in the scanned file set.
# ---------------------------------------------------------------------------

@register("dead_code")
def detect_dead_code(files: List[Path]) -> List[Finding]:
    """Flags a module-level def/class whose name never appears as an
    identifier anywhere else in the scanned set.

    DELIBERATELY CONSERVATIVE, false-negatives over false-positives:
    - dunder methods, test_* functions, and anything starting with
      leading underscore-free public names re-exported via __all__ are
      excluded from consideration as "never referenced" even if a
      naive scan would miss the reference (dynamic dispatch, string-based
      lookup, decorators, __all__ export).
    - CLASSES DECLARING Protocol OR ABC AS A BASE ARE EXCLUDED ENTIRELY
      (v0.1.1, added after a real false-positive run against ANVIL): an
      interface/Protocol class's whole purpose is often to have ZERO
      references within the file that defines it -- external implementers
      are the intended consumers, and this detector has no visibility
      into other repos. Flagging every Protocol/ABC as "dead" produced
      pure noise on real code (GovernanceModule(Protocol) in ANVIL.py,
      confirmed). Matched by simple base-expression name, not real type
      resolution -- this is an AST-only tool by design.
    - A STRING CONSTANT USED AS A SUBSCRIPT KEY counts as a reference too
      (v0.1.1, same ANVIL run): `registry["SomeName"]` is a real,
      extremely common dynamic-dispatch pattern (dict-based registries,
      plugin lookups, and -- the exact case found live -- a validation
      harness that loads a module via exec() into a dict and pulls names
      out by string key rather than a normal import). This does not
      attempt to trace exec()/importlib specifically; it generalizes past
      that one case to anything keying a lookup by a name-shaped string
      literal, which covers considerably more real dynamic-dispatch code
      than special-casing exec() alone would.
    - A name is "referenced" if it appears as an ast.Name/ast.Attribute,
      OR as a string-constant ast.Subscript key, ANYWHERE else in the
      corpus, including in the same file (covers self-reference,
      recursive helpers, internal use) -- this detector only flags things
      that look completely unreferenced, not merely privately-scoped.
    - Only module-level defs are considered (not methods) -- a method
      that's part of a class's public interface can be legitimately
      "unreferenced" in-repo (called by external consumers), and
      flagging every unused method would produce overwhelming noise for
      a v0.1. This is a real, disclosed scope limit, not an oversight.
    - Residual, still disclosed and not fixed by the above: getattr-by-
      string and decorator-based registration (this tool's own
      @register pattern is the concrete example -- it self-flags on
      ghost_buster's own codebase, see README) are still untraced.
    """
    definitions: Dict[str, List[Path]] = {}
    referenced_names: Set[str] = set()
    exported_names: Set[str] = set()

    def _is_protocol_or_abc(class_node: ast.ClassDef) -> bool:
        for base in class_node.bases:
            base_name = base.id if isinstance(base, ast.Name) else (
                base.attr if isinstance(base, ast.Attribute) else None
            )
            if base_name in ("Protocol", "ABC"):
                return True
        return False

    parsed = {}
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        parsed[path] = tree

    for path, tree in parsed.items():
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue
                if node.name.startswith("test_") or node.name.startswith("Test"):
                    continue
                if isinstance(node, ast.ClassDef) and _is_protocol_or_abc(node):
                    continue
                definitions.setdefault(node.name, []).append(path)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    exported_names.add(elt.value)

    for path, tree in parsed.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                referenced_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced_names.add(node.attr)
            elif isinstance(node, ast.Subscript):
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    referenced_names.add(key.value)

    findings: List[Finding] = []
    for name, def_paths in definitions.items():
        if name in exported_names:
            continue
        if name in referenced_names:
            continue
        for path in def_paths:
            findings.append(Finding(
                detector="dead_code",
                category=Category.DEAD_CODE,
                layer=Layer.MECHANICAL,
                severity=Severity.MINOR,
                status=Status.CONFIRMED,
                summary=f"'{name}' is defined but never referenced anywhere in the scanned set",
                detail=(
                    "No ast.Name, ast.Attribute, or string-subscript-key node "
                    "anywhere in the scanned files resolves to this identifier. "
                    "Scope limit: getattr-by-string and decorator-based "
                    "registration are still not traced, so this can false-"
                    "positive on names only reached that way -- confirm before "
                    "deleting."
                ),
                evidence=Evidence(file=str(path)),
            ))
    return findings


# ---------------------------------------------------------------------------
# Detector: long_function -- functions whose body exceeds a line-count
# threshold, a cheap, real proxy for the "Long Method" smell.
# ---------------------------------------------------------------------------

@register("long_function")
def detect_long_functions(files: List[Path], threshold: int = 80) -> List[Finding]:
    """Flags any function/method whose body spans more than `threshold`
    source lines (end_lineno - lineno). Not cyclomatic complexity (that
    needs control-flow-graph construction, out of scope for v0.1's
    stdlib-only constraint) -- line count is a cruder but real, honest
    proxy, and is disclosed as such in every finding's detail text.
    """
    findings: List[Finding] = []
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno is None:
                    continue
                length = node.end_lineno - node.lineno
                if length > threshold:
                    findings.append(Finding(
                        detector="long_function",
                        category=Category.COMPLEXITY,
                        layer=Layer.MECHANICAL,
                        severity=Severity.MINOR if length < threshold * 2 else Severity.MAJOR,
                        status=Status.CONFIRMED,
                        summary=f"'{node.name}' spans {length} lines (threshold {threshold})",
                        detail=(
                            "Line-count proxy for the 'Long Method' smell, not true "
                            "cyclomatic complexity -- a long function that's mostly "
                            "a flat sequence of simple statements is a weaker "
                            "signal than a short function with deep branching. "
                            "Treat as a prompt to look, not a verdict."
                        ),
                        evidence=Evidence(
                            file=str(path), line_start=node.lineno, line_end=node.end_lineno,
                        ),
                    ))
    return findings


# ---------------------------------------------------------------------------
# Detector: near_duplicate_function -- functions with structurally
# identical bodies (same AST shape modulo names/literals) in different
# locations.
# ---------------------------------------------------------------------------

def _structural_fingerprint(node: ast.AST) -> str:
    """A hash of a function body's AST *shape*, with all Name/Constant/
    Attribute leaf values erased -- two functions with the same control
    flow and statement structure but different variable names or literal
    values fingerprint identically. This is deliberately coarser than a
    real clone-detection tool (no token-level near-miss handling, no
    minimum-size normalization) -- it catches the "copy-pasted then
    renamed" shape, which is the specific pattern the research flagged
    as the hard-to-find near-duplicate case, and nothing subtler.
    """
    def shape(n: ast.AST):
        if isinstance(n, ast.Name):
            return ("Name",)
        if isinstance(n, ast.Constant):
            return ("Constant", type(n.value).__name__)
        if isinstance(n, ast.Attribute):
            return ("Attribute", shape(n.value))
        fields = []
        for field_name, value in ast.iter_fields(n):
            if isinstance(value, ast.AST):
                fields.append(shape(value))
            elif isinstance(value, list):
                fields.append(tuple(
                    shape(v) if isinstance(v, ast.AST) else v for v in value
                ))
            else:
                fields.append(value if isinstance(value, (int, float, bool, type(None))) else None)
        return (type(n).__name__, tuple(fields))

    return hashlib.sha256(repr(shape(node)).encode("utf-8")).hexdigest()


@register("near_duplicate_function")
def detect_near_duplicate_functions(files: List[Path], min_lines: int = 6) -> List[Finding]:
    """Groups functions by structural fingerprint; any group with 2+
    members is a near-duplicate cluster. min_lines guards against every
    trivial one-line getter/setter fingerprinting identically and
    burying real findings -- small functions are supposed to look alike;
    that's not a ghost.
    """
    by_fingerprint: Dict[str, List[tuple]] = {}
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno is None:
                    continue
                if (node.end_lineno - node.lineno) < min_lines:
                    continue
                fp = _structural_fingerprint(node)
                by_fingerprint.setdefault(fp, []).append((path, node))

    findings: List[Finding] = []
    for fp, occurrences in by_fingerprint.items():
        if len(occurrences) < 2:
            continue
        names = sorted({f"{p.name}:{n.name}" for p, n in occurrences})
        primary_path, primary_node = occurrences[0]
        findings.append(Finding(
            detector="near_duplicate_function",
            category=Category.DUPLICATION,
            layer=Layer.MECHANICAL,
            severity=Severity.MAJOR if len(occurrences) > 2 else Severity.MINOR,
            status=Status.CONFIRMED,
            summary=(
                f"{len(occurrences)} functions share identical AST structure "
                f"(names/literals differ, control flow and shape don't): {', '.join(names)}"
            ),
            detail=(
                "Structural fingerprint match, not textual diff -- this is the "
                "'copy-pasted then renamed' shape specifically. Confirm these are "
                "actually solving the same problem before merging; some structural "
                "matches are coincidental (e.g. two unrelated simple validators)."
            ),
            evidence=Evidence(
                file=str(primary_path), line_start=primary_node.lineno,
                line_end=primary_node.end_lineno,
                related_files=[str(p) for p, _ in occurrences[1:]],
            ),
        ))
    return findings


def run_all(files: Iterable[Path]) -> List[Finding]:
    """Run every registered mechanical detector against the given file
    list. Detectors are independent and order-independent by design
    (see registered_detectors)."""
    file_list = list(files)
    findings: List[Finding] = []
    for name, fn in registered_detectors().items():
        findings.extend(fn(file_list))
    return findings
