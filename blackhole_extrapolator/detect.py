"""Reading an absence out of the code that survived it.

Every detector here works the same way: walk what is present, find the places
where it reaches for something that is not, and record the shape of the reach.
The reach is the evidence. A caller writing `SYSTEM_GLOBALS.integrity_debt_balance
= max(0.0, ...)` has told you the missing object has that attribute, that the
attribute is writable, and that it is a float with a floor -- without any of
that being written down anywhere.

Mechanical only. Everything in this module is deterministic AST analysis over
real files: same input, same output, no model, no judgement. The inference
step in `extrapolate.py` is where anything resembling reasoning happens, and
it is kept separate precisely so the evidence can be trusted independently of
the conclusion drawn from it.

A note on false voids
---------------------
The dangerous error here is not missing a void -- it is inventing one. A name
that looks undefined because it comes from a wildcard import, a builtin, or a
conditional definition is not an absence, and reporting it as one sends
someone hunting for code that was never lost. Every detector below is
deliberately conservative and each records what it deliberately ignores.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .schema import EvidenceKind, NegativeEvidence

_BUILTINS = frozenset(dir(builtins))

# Names that are conventionally defined by the runtime or by tooling rather
# than by the module, and whose absence therefore means nothing.
_AMBIENT = frozenset({
    "__name__", "__file__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "self", "cls",
})


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name this module defines, imports, or binds at any scope.

    Deliberately over-collects. A name bound anywhere -- inside a function, in
    a comprehension, under a conditional -- counts as defined, because the
    cost of a false void (someone searching for code that was never lost) is
    much higher than the cost of missing one.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            for arg in getattr(node, "args", ast.arguments(
                    posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[])).args:
                bound.add(arg.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    # A wildcard import can bind anything. Everything after
                    # this is unknowable, so the module is not analysed for
                    # dangling references at all -- see detect_dangling_names.
                    bound.add("*")
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return bound


def _attribute_uses(tree: ast.Module, target: str) -> list[tuple[str, int, bool]]:
    """(attribute, line, is_written) for every `target.attr` in the module.

    The write flag matters more than it looks: an attribute only ever read
    could be a property, a constant, or a method. One that is assigned to is
    mutable state, which is a much stronger constraint on what the missing
    thing must be.
    """
    uses: list[tuple[str, int, bool]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == target):
            continue
        uses.append((node.attr, node.lineno, isinstance(node.ctx, ast.Store)))
    return uses


def detect_dangling_names(path: Path, source: str | None = None
                          ) -> Iterator[NegativeEvidence]:
    """Names a module uses and nothing defines.

    The strongest negative-space signal available: the callers describe the
    missing thing's interface in the act of using it.

    Modules containing a wildcard import are skipped entirely. After
    `from x import *` any name might be legitimately bound, and reporting
    those as voids would bury the real ones in noise.
    """
    text = source if source is not None else path.read_text(errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # A file that does not parse cannot be analysed this way. It may
        # itself be a destroyed artifact -- see detect_unparseable.
        return

    bound = _bound_names(tree)
    if "*" in bound:
        return

    seen: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
            continue
        name = node.id
        if name in bound or name in _BUILTINS or name in _AMBIENT or name in seen:
            continue
        seen.add(name)

        uses = _attribute_uses(tree, name)
        if uses:
            reads = sorted({a for a, _, w in uses if not w})
            writes = sorted({a for a, _, w in uses if w})
            detail = (
                f"`{name}` is used but never defined or imported. Callers "
                f"require attributes: read {reads or '[]'}"
                + (f", written {writes}" if writes else "")
            )
        else:
            detail = f"`{name}` is used but never defined or imported."

        yield NegativeEvidence(
            kind=EvidenceKind.DANGLING_REFERENCE,
            detail=detail,
            file=str(path),
            line=node.lineno,
            observed=text.splitlines()[node.lineno - 1].strip()[:160]
            if 0 < node.lineno <= len(text.splitlines()) else "",
        )


def detect_missing_imports(path: Path, search_roots: Sequence[Path],
                           source: str | None = None) -> Iterator[NegativeEvidence]:
    """Imports of modules that exist nowhere under the search roots.

    Distinguished from a dangling name because the evidence is different: an
    import names the missing thing directly, and `from x import a, b, c` also
    enumerates part of its public surface.
    """
    text = source if source is not None else path.read_text(errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return

    available: set[str] = set()
    for root in search_roots:
        if not root.is_dir():
            continue
        for candidate in root.rglob("*.py"):
            available.add(candidate.stem)
            available.add(candidate.parent.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            names = [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            module = node.names[0].name.split(".")[0]
            names = []
        else:
            continue
        if not module or module in available:
            continue
        try:                       # a real third-party or stdlib module
            __import__(module)
            continue
        except Exception:          # noqa: BLE001
            pass
        detail = f"module `{module}` is imported and exists nowhere in the search roots"
        if names:
            detail += f"; its expected surface includes {sorted(names)}"
        yield NegativeEvidence(
            kind=EvidenceKind.MISSING_MODULE, detail=detail,
            file=str(path), line=node.lineno,
        )


def detect_unparseable(path: Path, source: str | None = None
                       ) -> Iterator[NegativeEvidence]:
    """A file that no longer parses.

    The specimen case this tool was named for. `quorum_state_governance_source.py`
    is 14 KB of real content flattened onto a single line by a paste through a
    chat interface: the bytes survive and the program does not. Nothing can be
    read out of it directly, but its size, its surviving identifier-shaped
    tokens, and whatever still references it all constrain what it was.
    """
    text = source if source is not None else path.read_text(errors="replace")
    try:
        ast.parse(text)
        return
    except SyntaxError as exc:
        newlines = text.count("\n")
        flattened = newlines == 0 and len(text) > 500
        detail = (
            f"file does not parse ({exc.msg} at line {exc.lineno}); "
            f"{len(text)} bytes, {newlines} newlines"
        )
        if flattened:
            detail += (
                " -- FLATTENED: all line breaks destroyed, so indentation and "
                "therefore block structure are gone. Contents are not "
                "mechanically recoverable; only the shape of what referenced "
                "it is."
            )
        yield NegativeEvidence(
            kind=EvidenceKind.MISSING_MODULE, detail=detail,
            file=str(path), line=exc.lineno,
        )


def detect_orphaned_tests(test_paths: Iterable[Path],
                          search_roots: Sequence[Path]) -> Iterator[NegativeEvidence]:
    """Tests exercising something that is not there.

    Unusually strong evidence, because a test encodes both the expected
    interface and the expected behaviour -- it says not only what the missing
    thing was called but what it was supposed to do.
    """
    available: set[str] = set()
    for root in search_roots:
        if not root.is_dir():
            continue
        for candidate in root.rglob("*.py"):
            try:
                tree = ast.parse(candidate.read_text(errors="replace"))
            except SyntaxError:
                continue
            available.add(candidate.stem)
            available.update(_bound_names(tree))

    for path in test_paths:
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            module = (getattr(node, "module", None)
                      or node.names[0].name).split(".")[0]
            if module in available:
                continue
            try:
                __import__(module)
                continue
            except Exception:  # noqa: BLE001
                pass
            wanted = [a.name for a in node.names] if isinstance(node, ast.ImportFrom) else []
            yield NegativeEvidence(
                kind=EvidenceKind.ORPHANED_TEST,
                detail=(f"test imports `{module}`, which does not exist; the "
                        f"test encodes the expected interface"
                        + (f" {sorted(wanted)}" if wanted else "")),
                file=str(path), line=node.lineno,
            )


def scan(root: Path) -> list[NegativeEvidence]:
    """Every mechanical negative-space signal under `root`."""
    root = Path(root)
    sources = [p for p in root.rglob("*.py")
               if ".git" not in p.parts and "__pycache__" not in p.parts]
    tests = [p for p in sources
             if p.name.startswith("test_") or "test" in p.parent.name.lower()]

    evidence: list[NegativeEvidence] = []
    for path in sources:
        text = path.read_text(errors="replace")
        evidence.extend(detect_unparseable(path, text))
        evidence.extend(detect_dangling_names(path, text))
        evidence.extend(detect_missing_imports(path, [root], text))
    evidence.extend(detect_orphaned_tests(tests, [root]))
    return evidence
