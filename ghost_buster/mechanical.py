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
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

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

def _shape(n: ast.AST):
    """AST shape of one node with Name/Constant/Attribute leaf values
    erased -- the single normalization both _structural_fingerprint
    (whole functions) and _block_fingerprint (statement runs within one
    function) build on, so there is exactly one definition of "same
    shape" in this file rather than two that could drift apart.
    """
    if isinstance(n, ast.Name):
        return ("Name",)
    if isinstance(n, ast.Constant):
        return ("Constant", type(n.value).__name__)
    if isinstance(n, ast.Attribute):
        return ("Attribute", _shape(n.value))
    fields = []
    for field_name, value in ast.iter_fields(n):
        if isinstance(value, ast.AST):
            fields.append(_shape(value))
        elif isinstance(value, list):
            fields.append(tuple(
                _shape(v) if isinstance(v, ast.AST) else v for v in value
            ))
        else:
            fields.append(value if isinstance(value, (int, float, bool, type(None))) else None)
    return (type(n).__name__, tuple(fields))


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
    return hashlib.sha256(repr(_shape(node)).encode("utf-8")).hexdigest()


def _block_fingerprint(stmts: List[ast.stmt]) -> str:
    """Same normalization as _structural_fingerprint, applied to a run of
    statements rather than a whole function -- see
    detect_intra_function_duplicate_blocks for why this exists."""
    return hashlib.sha256(
        repr(tuple(_shape(s) for s in stmts)).encode("utf-8")
    ).hexdigest()


def _is_test_file(path: Path) -> bool:
    """A test module by the same convention mutation.py uses, plus a
    tests/ or test/ directory component."""
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part.lower() in ("tests", "test") for part in path.parts[:-1])


def _identical_file_groups(files: List[Path]) -> List[List[Path]]:
    """Groups of 2+ scanned files with byte-identical content. Measured on
    the first whole-library run (37 repositories): 31 such groups, almost
    all a module vendored verbatim from a sibling repo (sentinel_os and
    gsa-815 share queue_staffing_bayes_integration.py; sentinel_os and
    observe-perceive share perceive_consolidated.py). Every function in
    such a file fingerprinted identically to its twin, so one duplicated
    file was surfacing as N near_duplicate_function findings that said
    nothing about the real event -- the whole file is a copy."""
    by_hash: Dict[str, List[Path]] = {}
    for path in files:
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if not content:
            # Two empty __init__.py files are not a duplication; measured:
            # 4 of the first 35 groups on the library were exactly that.
            continue
        by_hash.setdefault(hashlib.sha256(content).hexdigest(), []).append(path)
    return [group for group in by_hash.values() if len(group) > 1]


@register("duplicate_file")
def detect_duplicate_files(files: List[Path]) -> List[Finding]:
    """One finding per group of byte-identical scanned files -- the
    signal near_duplicate_function was drowning in until v0.9 (see
    _identical_file_groups). A vendored verbatim copy of a sibling repo's
    module is the "parallel unreconciled implementation" risk in its
    purest form: two copies, one of which will be fixed and the other
    won't. MAJOR for that reason. A file that appears twice only because
    a symlinked directory was scanned twice is not this -- the CLI
    collects each real path once, so it never reaches here."""
    findings: List[Finding] = []
    for group in _identical_file_groups(files):
        group = sorted(group)
        names = ", ".join(str(p) for p in group)
        size = group[0].stat().st_size
        findings.append(Finding(
            detector="duplicate_file",
            category=Category.DUPLICATION,
            layer=Layer.MECHANICAL,
            severity=Severity.MAJOR,
            status=Status.CONFIRMED,
            summary=f"{len(group)} files are byte-identical ({size} bytes): {names}",
            detail=(
                "Same content, byte for byte. Typical real cause: a module copied "
                "verbatim from a sibling repository, or a whole directory duplicated "
                "instead of imported. Whichever copy gets the next fix, the other "
                "won't."
            ),
            evidence=Evidence(file=str(group[0]), related_files=[str(p) for p in group[1:]]),
        ))
    return findings


@register("near_duplicate_function")
def detect_near_duplicate_functions(files: List[Path], min_lines: int = 10) -> List[Finding]:
    """Groups functions by structural fingerprint; any group with 2+
    members is a near-duplicate cluster. min_lines guards against every
    trivial one-line getter/setter fingerprinting identically and
    burying real findings -- small functions are supposed to look alike;
    that's not a ghost.

    Three calibrations from the first whole-library run (37 repositories,
    v0.9), each measured before it was adopted:
      - files that are byte-identical to another scanned file are
        represented once here (duplicate_file reports the file itself):
        625 findings became 418;
      - min_lines 6 became 10: 418 became 248. Nothing in the dropped
        band, sampled by hand, was more than two short functions that
        happened to share a shape;
      - a cluster made only of test functions is INFORMATIONAL, never
        MAJOR: test functions sharing a setup/assert shape is what a test
        suite looks like, and the README had already disclosed it as the
        detector's dominant noise. MAJOR findings went from 42 to 27.
    """
    representatives: List[Path] = []
    seen_twins = set()
    for group in _identical_file_groups(files):
        for path in sorted(group)[1:]:
            seen_twins.add(path)
    representatives = [p for p in files if p not in seen_twins]

    by_fingerprint: Dict[str, List[tuple]] = {}
    for path in representatives:
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
        # One label per OCCURRENCE, not per unique (file, name) pair --
        # v0.1.2 bug fix, found via a real run against HERALD's own test
        # suite: two distinct nested functions both happened to be named
        # `thread_b` in the same file (a legitimate, common pattern --
        # multiple similarly-shaped test functions each defining their
        # own locally-scoped helper of the same name). The original
        # `{f"{p.name}:{n.name}"}` SET silently collapsed both into one
        # identical string, producing a finding that claimed "2 functions
        # share..." while naming only one -- correct occurrence count,
        # misleading/incomplete label. Line numbers make every label
        # unique by construction; a plain list (not a set) means no
        # future case can silently lose an occurrence this way again.
        names = [f"{p.name}:{n.lineno}:{n.name}" for p, n in occurrences]
        primary_path, primary_node = occurrences[0]
        if all(_is_test_file(p) for p, _ in occurrences):
            severity = Severity.INFORMATIONAL
        elif len(occurrences) > 2:
            severity = Severity.MAJOR
        else:
            severity = Severity.MINOR
        findings.append(Finding(
            detector="near_duplicate_function",
            category=Category.DUPLICATION,
            layer=Layer.MECHANICAL,
            severity=severity,
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


# ---------------------------------------------------------------------------
# Detector: intra_function_duplicate_block -- v0.2, added for a real gap
# near_duplicate_function cannot see: repeated statement runs that live
# INSIDE one function (e.g. sibling if/elif branches that each hand-build
# the same shape of object) rather than being duplicated across two whole
# functions. near_duplicate_function fingerprints entire function bodies,
# so six near-identical ~9-line blocks inside one function's six verdict
# branches are invisible to it -- confirmed live: this exact pattern in
# HERALD's gate.py (six branches of submit(), each hand-constructing a
# GateDecision with the same authorization_mac=_sign_decision(...) call)
# was found by reading the code during triage, not by ghost_buster, and
# was flagged at the time as a v0.2 gap worth closing.
# ---------------------------------------------------------------------------

_BLOCK_FIELD_NAMES = ("body", "orelse", "finalbody")


def _stmt_blocks(func_node: ast.AST) -> Iterable[List[ast.stmt]]:
    """Every list-of-statements belonging to a function's OWN scope: its
    own body, plus the body/orelse/finalbody of every nested if/for/while/
    try/with inside it, plus each except-handler's body. Each is a
    candidate for "the same block repeated" -- a sibling if/elif branch is
    exactly one of these lists, which is the shape the gate.py case
    actually had.

    Recurses only through statement lists (body/orelse/finalbody/handler
    bodies), never through ast.walk -- ast.walk cannot be pruned, so using
    it here would still surface a nested function's inner blocks (they're
    descendants of func_node regardless of what a visitor does when it
    reaches the FunctionDef node itself). Recursing through the AST's own
    body/orelse/finalbody structure means a nested def/async def is simply
    never entered: it has no such field on the *statements around it* to
    recurse through, and is itself skipped explicitly below. That nested
    function is still analyzed -- as its own `func` in the caller's outer
    loop over the module -- just not folded into this function's set.

    Scope limit, not fixed here: constructs whose bodies aren't a plain
    list of statements (match-case bodies, comprehensions) are not
    descended into. Rare in practice and left as a known residual rather
    than adding a special case for every AST shape in a v0.2 detector.
    """
    def blocks_in(stmts: List[ast.stmt]) -> Iterable[List[ast.stmt]]:
        yield stmts
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for field_name in _BLOCK_FIELD_NAMES:
                value = getattr(stmt, field_name, None)
                if value:
                    yield from blocks_in(value)
            for handler in getattr(stmt, "handlers", []):
                if handler.body:
                    yield from blocks_in(handler.body)

    yield from blocks_in(func_node.body)


def _node_count(node: ast.AST) -> int:
    """Size of a statement's own subtree, in AST nodes -- the complexity
    signal _stmt_candidates uses instead of (or alongside) raw statement
    count. A single `return Decision(a=..., b=..., mac=sign(...))`
    statement can easily be 30-50 nodes; a bare `x = 1` is 3-4. Counting
    nodes catches "this one statement is doing a lot" in a way counting
    statements never can, since a statement count of 1 looks identical
    for both."""
    return 1 + sum(_node_count(c) for c in ast.iter_child_nodes(node))


def _stmt_candidates(
    func_node: ast.AST, min_statements: int, min_complexity: int
) -> Iterable[Tuple[int, List[ast.stmt]]]:
    """Every comparison unit worth fingerprinting inside one function,
    tagged with the index of the statement list it came from: whole
    sibling blocks of >= min_statements statements (a duplicated
    multi-statement branch body), AND individual statements whose own
    subtree has >= min_complexity nodes (a duplicated single complex
    statement -- see module comment above detect_intra_function_
    duplicate_blocks for why this second case was added: it is not an
    edge case, it is the shape the real motivating bug actually had).

    The block index is what lets the detector tell "the same statement in
    two different branches" (the gate.py shape) from "several similar
    statements in a row in one block" (an __init__ assigning seven
    attributes, a dict built one entry per line) -- see
    detect_intra_function_duplicate_blocks.
    """
    for block_index, block in enumerate(_stmt_blocks(func_node)):
        if len(block) >= min_statements:
            yield block_index, block
        for stmt in block:
            if _node_count(stmt) >= min_complexity:
                yield block_index, [stmt]


@register("intra_function_duplicate_block")
def detect_intra_function_duplicate_blocks(
    files: List[Path], min_statements: int = 3, min_complexity: int = 20
) -> List[Finding]:
    """Within each function independently, groups statement-list blocks
    (if/elif/else bodies, try/except/finally bodies, for/while bodies,
    with bodies) AND individual complex statements by structural
    fingerprint. A group of 2+ is the same "copy this, tweak the values,
    repeat" shape near_duplicate_function is blind to, because no single
    occurrence is a whole function.

    v0.2's first design only compared runs of >= min_statements sibling
    statements. Live-checked against the actual motivating case -- the
    six branches of HERALD gate.py's pre-fix submit(), each hand-building
    a GateDecision -- and it found NOTHING: every branch there was one
    `return GateDecision(...)` statement, a statement COUNT of 1, however
    deeply nested the call inside it. A pure statement-count floor is
    blind to "the interesting duplication is one large statement, not a
    run of several", so min_complexity (AST subtree size of a single
    statement) is compared alongside min_statements, not instead of it --
    both real shapes exist and neither subsumes the other.

    Deliberately scoped to ONE function at a time, not the whole file or
    repo: the confirmed real case was sibling branches within one
    function, and going wider (matching a unit in function A against one
    in function B) is a materially different, noisier claim -- "two
    functions happen to share a sub-shape" is a much weaker signal than
    "this one function repeats itself" -- left for a future version if
    it turns out to matter.

    Two calibrations from the first whole-library run (37 repositories,
    v0.9), each measured before it was adopted:
      - a single statement counts as repeated only across DISTINCT
        statement lists (different branch bodies), never within one.
        The motivating case was six branches each building the same
        object; what the detector was actually reporting, 643 times out
        of 655, was several similar statements in a row in one block --
        an __init__ assigning seven attributes, a dict built one entry
        per line. Those are how code is written, not a ghost. Findings
        went from 1,300 to 421 on the library;
      - min_complexity 15 became 20. The original gate.py's four branch
        returns measured 41, 26, 33 and 22 nodes, so 20 keeps every one
        of them (25 would have lost one); 421 became 221, MAJOR from 89
        to 46.
    Multi-statement blocks are unchanged: 30 findings on the library
    before and after, every one a real repeated branch body.
    """
    findings: List[Finding] = []
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            by_fingerprint: Dict[str, List[List[ast.stmt]]] = {}
            blocks_of: Dict[str, Set[int]] = {}
            for block_index, unit in _stmt_candidates(func, min_statements, min_complexity):
                fp = _block_fingerprint(unit)
                by_fingerprint.setdefault(fp, []).append(unit)
                blocks_of.setdefault(fp, set()).add(block_index)

            for fp, units in by_fingerprint.items():
                if len(units) < 2:
                    continue
                if len(units[0]) == 1 and len(blocks_of[fp]) < 2:
                    continue  # one block repeating a statement is a list, not a ghost
                spans = [f"{u[0].lineno}-{u[-1].lineno}" for u in units]
                first = units[0]
                shape_note = (
                    "single statement" if len(first) == 1
                    else f"{len(first)}-statement block"
                )
                findings.append(Finding(
                    detector="intra_function_duplicate_block",
                    category=Category.DUPLICATION,
                    layer=Layer.MECHANICAL,
                    severity=Severity.MAJOR if len(units) > 2 else Severity.MINOR,
                    status=Status.CONFIRMED,
                    summary=(
                        f"'{func.name}' repeats the same {shape_note} "
                        f"{len(units)} times (lines {', '.join(spans)}): "
                        "same shape, names/literals differ"
                    ),
                    detail=(
                        "Structural fingerprint match within one function, not a "
                        "whole-function match (near_duplicate_function's detection "
                        "is blind to this shape). Typical real cause: several "
                        "branches each hand-build the same kind of object or "
                        "perform the same sequence of calls -- worth a single "
                        "shared helper if the branches really are doing the same "
                        "thing, not just a coincidental resemblance."
                    ),
                    evidence=Evidence(
                        file=str(path), line_start=first[0].lineno,
                        line_end=first[-1].lineno,
                        related_files=[f"{path}:{s}" for s in spans[1:]],
                    ),
                ))
    return findings


# ---------------------------------------------------------------------------
# Detector: doc_test_count_drift -- v0.3. A mechanical, deterministic
# instance of doc/reality drift: a markdown file claims a specific number
# of tests exist ("135 tests passing"), and the number of test_* functions
# actually in the scanned .py files has since grown well past it.
#
# Found live, by hand, doing exactly the taxonomy-driven scrub this
# detector now automates: HERALD's README said "Version 0.3.0. 135 tests
# passing" while `python3 -m pytest --collect-only -q` reported 321.
# git log showed why -- 15 commits touched Tests/ after the README's last
# version-bump commit (an HMAX adversarial-test campaign), and the count
# claim was simply never revisited. This is the same "documentation
# describes a system that no longer exists" failure the semantic layer's
# doc_drift already names (same Category.DOC_DRIFT), but semantic doc_drift
# requires an LLM call AND a human-supplied code summary to compare
# against -- it cannot self-drive a whole-repo scrub. A number in a
# markdown file next to the word "test(s)" is instead a fully mechanical,
# zero-ambiguity check: no API key, no judgment call, Status.CONFIRMED.
# ---------------------------------------------------------------------------

_TEST_COUNT_CLAIM_RE = re.compile(
    r"\b(\d+)\s+tests?\b(?=\s*[,.]|\s+(?:passing|passed|collected))",
    re.IGNORECASE,
)


def _count_test_functions(files: List[Path]) -> int:
    """Static, conservative LOWER BOUND on the real test count: every
    function (module-level or a method) named test_* in the scanned .py
    files. A lower bound, not an exact match to pytest's own collection,
    because @pytest.mark.parametrize expands one function into several
    collected cases -- the true number can only be higher than this, never
    lower, which is exactly the property detect_doc_test_count_drift needs
    to flag an undercount claim without false-positiving on parametrize
    making a once-correct claim look artificially low.
    """
    count = 0
    for path in files:
        if path.suffix != ".py":
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    count += 1
    return count


@register("doc_test_count_drift")
def detect_doc_test_count_drift(
    files: List[Path], min_growth_ratio: float = 1.15, min_absolute_growth: int = 10
) -> List[Finding]:
    """Flags a markdown "N tests passing/collected" (or "N tests,") claim
    once the real, statically-counted test_* function count has grown well
    past it. Deliberately one-directional: only flags UNDERcounts (real >
    documented), never overcounts. _count_test_functions is a lower bound
    (see its docstring -- parametrize can only push the true count higher),
    so a documented number ABOVE the static count is not necessarily wrong
    and is not flagged; a documented number this far BELOW the static count
    is unambiguously stale regardless of parametrize.

    Both min_growth_ratio and min_absolute_growth must be cleared (an AND,
    not an OR) before flagging -- guards against flagging a doc that is
    merely a commit or two behind (normal, not a ghost) versus one that
    has been stale across an entire campaign of new tests (the real case
    this was built from: 135 documented vs. 256 statically counted, a
    parametrize-inclusive pytest run reporting 321).
    """
    md_files = [p for p in files if p.suffix.lower() == ".md"]
    if not md_files:
        return []
    actual = _count_test_functions(files)
    if actual == 0:
        return []

    findings: List[Finding] = []
    for path in md_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _TEST_COUNT_CLAIM_RE.finditer(text):
            documented = int(match.group(1))
            if documented == 0:
                continue
            if actual < documented * min_growth_ratio:
                continue
            if actual - documented < min_absolute_growth:
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(
                detector="doc_test_count_drift",
                category=Category.DOC_DRIFT,
                layer=Layer.MECHANICAL,
                severity=Severity.MINOR,
                status=Status.CONFIRMED,
                summary=(
                    f"'{path.name}' claims {documented} test(s), but at least "
                    f"{actual} test_* function(s) exist in the scanned .py files "
                    "-- this claim is stale"
                ),
                detail=(
                    "actual is a static AST lower bound (functions named test_*, "
                    "counted directly, no pytest run) -- the true collected count "
                    "can only be higher (pytest.mark.parametrize expands one "
                    "function into several cases), never lower, so this can only "
                    "under-flag, not over-flag. Confirm by running the real suite "
                    "and update the claim, or remove the specific number if it "
                    "will keep going stale."
                ),
                evidence=Evidence(file=str(path), line_start=line, line_end=line),
            ))
    return findings


# ---------------------------------------------------------------------------
# Detector: merge_conflict_marker -- an unresolved git conflict marker
# (<<<<<<< / ======= / >>>>>>>) left in a committed file.
# ---------------------------------------------------------------------------

_CONFLICT_OURS = re.compile(r"^<{7}(?:\s.*)?$")
_CONFLICT_SEP = re.compile(r"^={7}$")
_CONFLICT_THEIRS = re.compile(r"^>{7}(?:\s.*)?$")


def _next_matching(lines: List[str], pattern: "re.Pattern[str]", start: int) -> Optional[int]:
    """Index of the first line at or after `start` matching `pattern`, or
    None. Shared by both marker lookups below -- they are the same
    operation ("find the next line of this shape") against two different
    patterns, not two independent pieces of logic."""
    return next((j for j in range(start, len(lines)) if pattern.match(lines[j])), None)


@register("merge_conflict_marker")
def detect_merge_conflict_markers(files: List[Path]) -> List[Finding]:
    """Flags an unresolved conflict-marker triplet: a `<<<<<<<` line,
    followed later by a `=======` line, followed later by a `>>>>>>>`
    line, in that order, anywhere in the same file.

    THE ONE DETECTOR HERE THAT DOES NOT CALL _parse(), ON PURPOSE
    -------------------------------------------------------------------
    Every other detector in this module starts from an AST. A file that
    genuinely still has an unresolved conflict marker in it is, in
    virtually every real case, no longer valid Python -- the marker lines
    are not legal syntax, so `ast.parse()` raises and `_parse()` fails
    closed to None. Going through `_parse()` here would mean this
    detector finds nothing in exactly the files most likely to have the
    problem. So this one reads the file as plain text and never touches
    `ast` at all.

    WHY A TRIPLET, NOT ANY ONE MARKER LINE BY ITSELF
    -----------------------------------------------------
    `=======` alone is a real false-positive risk: a Setext-style Markdown
    H1 underline is any run of `=` characters, and one that happens to be
    exactly 7 long is indistinguishable from git's separator line on its
    own. Requiring the full shape in order -- the same discipline the
    widely-used `pre-commit-hooks` project's own check-merge-conflict hook
    uses, for the same reason -- means a lone `=======` proves nothing,
    but the triplet essentially never occurs by coincidence. A stray
    `<<<<<<<` with no `=======`/`>>>>>>>` after it (a truncated file, or a
    doc showing one marker line as an isolated example) is deliberately
    not flagged either, for the same reason.

    Each marker line must be the WHOLE line: exactly 7 of the character,
    then nothing or a space and a label, never "at least 7" and never
    "somewhere in the line". This is what keeps this detector from firing
    on prose that mentions `<<<<<<<` inline, in backticks, in the middle
    of a sentence -- text like that never starts a physical source line
    with the bare marker, so it never matches. Confirmed by running this
    detector against mechanical.py itself, this docstring included, after
    it was written.

    A diff3-style conflict (`git config merge.conflictstyle diff3`) adds
    a fourth marker line, `|||||||`, between `<<<<<<<` and `=======` --
    already handled without special-casing it, since finding `=======`
    only requires it to appear somewhere after `<<<<<<<`, not immediately
    after.
    """
    findings: List[Finding] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if not _CONFLICT_OURS.match(lines[i]):
                i += 1
                continue
            ours_line = i
            sep_line = _next_matching(lines, _CONFLICT_SEP, ours_line + 1)
            theirs_line = (
                _next_matching(lines, _CONFLICT_THEIRS, sep_line + 1)
                if sep_line is not None else None
            )
            if sep_line is None or theirs_line is None:
                i = ours_line + 1
                continue
            findings.append(Finding(
                detector="merge_conflict_marker",
                category=Category.MERGE_CONFLICT_MARKER,
                layer=Layer.MECHANICAL,
                severity=Severity.CRITICAL,
                status=Status.CONFIRMED,
                summary=f"unresolved merge conflict marker in {path.name}",
                detail=(
                    f"lines {ours_line + 1}-{theirs_line + 1}: a <<<<<<< / ======= / "
                    ">>>>>>> triplet is still in this file. Whatever is between the "
                    "markers is almost certainly not the intended content, and in a "
                    ".py file this line shape alone is very likely a syntax error."
                ),
                evidence=Evidence(
                    file=str(path), line_start=ours_line + 1, line_end=theirs_line + 1,
                    snippet=lines[ours_line][:200],
                ),
            ))
            i = theirs_line + 1
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
