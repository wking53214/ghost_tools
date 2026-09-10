"""boundary.py -- the seam between two repositories.

WHAT NEITHER REPOSITORY'S CI CAN SEE

A cross-repository boundary is the one place where both sides are blind.
Repository A imports three names from B behind a guard, and when B is
absent the import fails quietly and A's tests skip. B has no idea A
exists at all. So A's CI proves nothing about the seam because it never
runs it, and B's CI proves nothing because it never heard of it. The
contract is verified at exactly one moment: when somebody joins them.

Measured on a real pair. observe-perceive reaches CCC like this:

    def _import_ccc():
        ccc_path = os.path.join(os.path.dirname(__file__), "..", "CCC")
        if os.path.isdir(ccc_path) and ccc_path not in sys.path:
            sys.path.insert(0, ccc_path)
        try:
            from ccc import Actor, CCCSystem, EpistemicStatus
        except ImportError:
            return None, None, None

Three named symbols, a sibling-checkout path, a fallback to None, and 54
tests across the repository that skip when that fallback fires. Every one
of those is a test in STASIS: written, committed, and never executed
until the two checkouts sit side by side.

WHAT THIS MODULE ESTABLISHES, AND WHAT IT CANNOT

It can resolve a named import against what the other repository actually
exports, because both are observable. It can tell whether any test in
either repository so much as mentions a boundary symbol, which is the
mechanical form of "is a new test needed here".

It cannot check a duck-typed contract. The adapter above says so itself:
"CCC's intake is structural: anything carrying .conclusion, .method,
.source_material ... can be recorded." No static analysis resolves that,
and pretending otherwise would be inventing evidence. Those go to
`unresolved`, named.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status
from .structure import _PACKAGE_PARENTS, _stdlib_names, StructuralModel, build_model

DETECTOR = "boundary"

#: A test whose reason names a missing checkout is dormant, not broken.
_DORMANT_REASON = re.compile(
    r"(?:not available|unavailable|not resolvable|missing|not installed|"
    r"beside this checkout|checkout)", re.IGNORECASE)


@dataclass
class GuardedImport:
    """`from pkg import a, b` inside a try/except ImportError -- a boundary
    the author declared by writing a fallback for it."""
    repo: str
    module: str            # the importing module, dotted
    package: str           # the top-level package being reached for
    source: str = ""       # the exact module named, e.g. "ccc.matching"
    names: List[str] = field(default_factory=list)
    line: Optional[int] = None
    guarded: bool = True


@dataclass
class DormantTest:
    repo: str
    module: str
    reason: str
    line: Optional[int] = None


@dataclass
class JoinedModel:
    repos: List[str] = field(default_factory=list)
    ran: bool = False
    reason: str = ""
    #: package name -> (repo root, every name any of its modules exports)
    provides: Dict[str, Tuple[str, Set[str]]] = field(default_factory=dict)
    #: exact dotted module -> the names IT exports. Resolving `from
    #: ccc.matching import X` against the union of every ccc module would
    #: accept a name that lives in a different submodule entirely.
    provides_module: Dict[str, Set[str]] = field(default_factory=dict)
    opaque_modules: Set[str] = field(default_factory=set)
    reaches: List[GuardedImport] = field(default_factory=list)
    dormant_tests: List[DormantTest] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)


def _dotted(path: Path, root: Path) -> str:
    return ".".join(path.relative_to(root).with_suffix("").parts)


def guarded_imports(tree: ast.AST, repo: str, module: str) -> Tuple[List[GuardedImport], List[str]]:
    """Every import written with a fallback, plus notes on the ones whose
    target cannot be named."""
    out, notes = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches_import = any(
            _handler_catches_import(h) for h in node.handlers
        )
        if not catches_import:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom) and inner.module and not inner.level:
                out.append(GuardedImport(
                    repo=repo, module=module, package=inner.module.split(".", 1)[0],
                    source=inner.module,
                    names=[a.name for a in inner.names], line=inner.lineno,
                ))
            elif isinstance(inner, ast.Import):
                for alias in inner.names:
                    out.append(GuardedImport(
                        repo=repo, module=module, package=alias.name.split(".", 1)[0],
                        names=[], line=inner.lineno,
                    ))
            elif isinstance(inner, ast.Call):
                fn = getattr(inner.func, "id", "") or getattr(inner.func, "attr", "")
                if fn in ("import_module", "__import__"):
                    notes.append(
                        f"{repo}:{module} reaches a dependency through {fn}() at line "
                        f"{inner.lineno}; the target is computed at runtime and the "
                        f"symbols it provides cannot be resolved here")
    return out, notes


def _handler_catches_import(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if t is None:
        return True                      # bare except: catches ImportError too
    names = [t] if not isinstance(t, ast.Tuple) else list(t.elts)
    for n in names:
        name = n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", "")
        if name in ("ImportError", "ModuleNotFoundError", "Exception", "BaseException"):
            return True
    return False


def dormant_tests(tree: ast.AST, repo: str, module: str) -> List[DormantTest]:
    """A test that skips because something is not here. The reason string is
    the evidence -- a skip with no reason is a different finding entirely,
    and testsuite.py already rates it MAJOR."""
    out = []
    for node in ast.walk(tree):
        reason = None
        if isinstance(node, ast.Call):
            fn = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
            if fn in ("skip", "skipTest", "skipif"):
                for arg in list(node.args) + [k.value for k in node.keywords
                                              if k.arg == "reason"]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        reason = arg.value
                        break
        if reason and _DORMANT_REASON.search(reason):
            out.append(DormantTest(repo=repo, module=module, reason=reason,
                                   line=getattr(node, "lineno", None)))
    return out


def _is_stdlib(package: str) -> bool:
    """A guarded import of a standard-library module is not a cross-repo
    boundary. It is the ordinary way to support more than one Python
    version -- `try: from importlib.metadata import x / except ImportError`
    -- and this project does exactly that, so the very first self-scan
    after the boundary check landed reported ghost_tools as reaching for
    an outside package called `importlib`."""
    return package.split(".", 1)[0] in _stdlib_names()


def build_joined_model(roots: Sequence, files_by_root: Dict[str, List[Path]]) -> JoinedModel:
    joined = JoinedModel(repos=[str(Path(r).resolve()) for r in roots])
    if len(joined.repos) < 2:
        joined.reason = "a boundary needs at least two repositories"
        return joined
    joined.ran = True

    models: Dict[str, StructuralModel] = {}
    for root in joined.repos:
        files = files_by_root.get(root, [])
        models[root] = build_model(root, files)

    # What each repository PROVIDES: its importable top-level packages and,
    # for each, every top-level name any of its modules exports.
    # A MODULE UNDER src/ STILL BELONGS TO ITS PACKAGE. `packages` reports
    # `gems` while every module is dotted `src.gems.*`, so a first-segment
    # comparison matched nothing and the repository was recorded as providing
    # NOTHING AT ALL -- which made every name imported from it "missing" and
    # every such import a CRITICAL. Measured 2026-09-10 joining two real
    # repositories: two criticals, both against imports that run fine.
    def _normalise(dotted: str) -> str:
        """Drop layout directories and the __init__ suffix, so a module is
        named the way an importer would name it."""
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]
        elif dotted == "__init__":
            return ""
        parts = [p for p in dotted.split(".") if p]
        while parts and parts[0] in _PACKAGE_PARENTS:
            parts.pop(0)
        return ".".join(parts)

    # A NAME A MODULE RE-EXPORTS IS A NAME IT PROVIDES. Collecting only
    # definitions treated `__init__.py` as though it exported nothing, which
    # is the opposite of what an `__init__.py` is usually for.
    def _surface(m) -> Set[str]:
        return set(m.exported) | set(m.public_names) | set(m.bindings) | set(m.reexports)

    #: Modules whose surface cannot be enumerated because a star-import
    #: points somewhere this scan could not resolve. Their contents are
    #: unknowable, so a name is never reported missing from them.
    opaque: Set[str] = set()

    for root, model in models.items():
        # Index by the LAST dotted segment as well, so `gems.contracts`
        # resolves whether the scan saw it as `gems.contracts` or as
        # `src.gems.contracts` under a src layout.
        by_tail: Dict[str, Set[str]] = {}
        for m in model.modules:
            tail = _normalise(m.dotted)
            if not tail:
                continue
            by_tail.setdefault(tail, set()).update(_surface(m))
            by_tail.setdefault(tail.split(".")[-1], set()).update(_surface(m))

        for package in model.packages:
            names: Set[str] = set()
            for m in model.modules:
                normalised = _normalise(m.dotted)
                if not normalised or normalised.split(".", 1)[0] != package:
                    continue
                surface = _surface(m)

                # Expand `from X import *` against the joined set where X is
                # resolvable, and mark the module opaque where it is not.
                for target in m.star_imports:
                    resolved = by_tail.get(target) or by_tail.get(target.split(".")[-1])
                    if resolved is None:
                        opaque.add(normalised)
                        joined.unresolved.append(
                            f"{normalised} re-exports everything from '{target}', "
                            f"which this scan could not resolve; its public "
                            f"surface is therefore not enumerable and no name "
                            f"will be reported missing from it")
                    else:
                        surface |= resolved

                names.update(surface)
                joined.provides_module[normalised] = surface
                if m.is_package:
                    names.update(n.split(".")[-1] for n in m.imports_internal)
            joined.provides[package] = (root, names)

    joined.opaque_modules = opaque

    # What each repository REACHES FOR.
    for root, model in models.items():
        root_path = Path(root)
        for m in model.modules:
            path = root_path / m.path
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            imports, notes = guarded_imports(tree, root, m.dotted)
            joined.reaches.extend(i for i in imports if not _is_stdlib(i.package))
            joined.unresolved.extend(notes)
            joined.dormant_tests.extend(dormant_tests(tree, root, m.dotted))

    joined.unresolved = sorted(set(joined.unresolved))
    return joined


def _finding(kind: str, severity: Severity, file: str, summary: str,
             detail: str, attributes: dict, line=None) -> Finding:
    return Finding(
        detector=DETECTOR, category=Category.ARCHITECTURE, layer=Layer.MECHANICAL,
        severity=severity, status=Status.CONFIRMED,
        summary=f"{kind}: {summary}",
        evidence=Evidence(file=file, line_start=line, line_end=line),
        detail=detail, attributes=dict(attributes, kind=kind),
    )


def _test_corpus(files_by_root: Dict[str, List[Path]]) -> str:
    """Every test file in the joined set, concatenated. Crude on purpose: a
    symbol's NAME appearing nowhere in any test is strong evidence nothing
    exercises it, while its appearing somewhere proves only that it is
    mentioned. This check is built to be sure about absence and modest
    about presence."""
    chunks = []
    for files in files_by_root.values():
        for p in files:
            name = p.name
            if not (name.startswith("test_") or name.endswith("_test.py")
                    or "tests" in p.parts or "test" in p.parts):
                continue
            try:
                chunks.append(p.read_text(encoding="utf-8"))
            except OSError:
                continue
    return "\n".join(chunks)


def derive_findings(joined: JoinedModel, files_by_root: Dict[str, List[Path]]) -> List[Finding]:
    if not joined.ran:
        return []
    out: List[Finding] = []
    corpus = _test_corpus(files_by_root)

    for reach in joined.reaches:
        provider = joined.provides.get(reach.package)
        file = str(Path(reach.repo) / reach.module.replace(".", "/")) + ".py"

        if provider is None:
            out.append(_finding(
                "boundary provider absent", Severity.MINOR, file,
                f"'{reach.module}' reaches for '{reach.package}', which no "
                f"repository in this joined set provides",
                "The seam is declared and the other side is not here. Either the "
                "join is incomplete -- add the repository that provides this "
                "package -- or the dependency is external and this is simply how "
                "it degrades, in which case nothing is wrong and the fallback is "
                "doing its job.\n\nReported MINOR because both readings are "
                "common, and because the fallback means nothing crashes today. "
                "What it costs is that every test behind this guard stays "
                "dormant, and a dormant test proves nothing.",
                {"package": reach.package, "reaching_module": reach.module},
                reach.line,
            ))
            continue

        provider_root, exported = provider
        if provider_root == reach.repo:
            continue    # reaching for itself; not a boundary

        # `from ccc.matching import X` must be resolved against ccc.matching,
        # not against every module in ccc. The union is the right answer only
        # for `from ccc import X`, where a package __init__ may re-export it.
        if reach.source and reach.source != reach.package:
            exact = joined.provides_module.get(reach.source)
            if exact is None:
                joined.unresolved.append(
                    f"{reach.module} imports from '{reach.source}', which was "
                    f"not found as a module in the joined set; it may be a "
                    f"subpackage laid out in a way this scan did not follow")
                continue
            exported = exact | joined.provides_module.get(reach.package, set())

        # A module whose surface could not be enumerated cannot be shown to
        # be missing anything. Abstain rather than accuse: this check is
        # CRITICAL, and a critical that is wrong costs more than one that is
        # absent.
        if reach.source in joined.opaque_modules or reach.package in joined.opaque_modules:
            continue

        missing = [n for n in reach.names if n not in exported]
        if missing:
            out.append(_finding(
                "cross repo import unresolved", Severity.CRITICAL, file,
                f"'{reach.module}' imports {', '.join(missing)} from "
                f"'{reach.package}', which does not export "
                f"{'them' if len(missing) > 1 else 'it'}",
                "Neither repository's CI can catch this. The importing side "
                "guards the import and skips its tests when the other is absent, "
                "so it never runs the seam; the providing side has never heard of "
                "the importer. The contract is checked at exactly one moment -- "
                "when somebody joins the two -- and this says it will fail then."
                "\n\nScope limit: a name re-exported through a package __init__ "
                "by a mechanism this scan could not follow, or provided "
                "dynamically, would look identical. Confirm before deleting the "
                "import.",
                {"package": reach.package, "missing": ", ".join(missing),
                 "provider": provider_root, "reaching_module": reach.module},
                reach.line,
            ))
            continue

        untested = [n for n in reach.names if n and not re.search(rf"\b{re.escape(n)}\b", corpus)]
        if untested:
            out.append(_finding(
                "boundary symbol untested", Severity.MAJOR, file,
                f"'{reach.module}' imports {', '.join(untested)} from "
                f"'{reach.package}', and no test in either repository mentions "
                f"{'them' if len(untested) > 1 else 'it'}",
                "This is the mechanical form of 'is a new test needed here'. The "
                "symbol crosses a repository boundary, both sides resolve, and "
                "nothing anywhere exercises it -- not a live test, not a dormant "
                "one waiting for the join. The seam works today by luck and "
                "nobody would learn otherwise until it stopped.\n\nA test for "
                "this belongs on the importing side, guarded the same way the "
                "import is, so that it lies dormant alone and runs on join.\n\n"
                "Scope limit: presence of a name in the test corpus proves only "
                "that it is mentioned. This check is built to be certain about "
                "ABSENCE and modest about presence.",
                {"package": reach.package, "untested": ", ".join(untested),
                 "reaching_module": reach.module},
                reach.line,
            ))

    for dormant in joined.dormant_tests:
        file = str(Path(dormant.repo) / dormant.module.replace(".", "/")) + ".py"
        out.append(_finding(
            "dormant boundary test", Severity.INFORMATIONAL, file,
            f"'{dormant.module}' holds a test that skips: {dormant.reason!r}",
            "Inventory, not a complaint. A test written for a seam and waiting "
            "for the other side is exactly right, and it is strictly better than "
            "no test. It is reported so that it can be COUNTED and AGED: the "
            "ledger raises persistent_finding once a dormant test has gone ten "
            "runs without ever waking, and a test that has never once executed "
            "is indistinguishable from a test that does not exist.",
            {"reason": dormant.reason, "module": dormant.module}, dormant.line,
        ))
    return out


def render_report(joined: JoinedModel, findings: List[Finding]) -> str:
    if not joined.ran:
        return f"ghost_buster: boundary scan did not run: {joined.reason}"
    crossings = len([r for r in joined.reaches
                     if joined.provides.get(r.package, ("", set()))[0] not in ("", r.repo)])
    return (f"ghost_buster: boundary scan joined {len(joined.repos)} repositories, "
            f"{crossings} cross-repo import(s), {len(joined.dormant_tests)} dormant "
            f"test(s), {len(joined.unresolved)} unresolved; {len(findings)} finding(s)")


def render_single_repo_notice(root, files: List[Path]) -> Optional[str]:
    """What a ONE-repo scan should say when it is looking at half a system.

    A repository full of guarded imports and dormant tests is not a whole
    thing, and a scan that reports it as clean is telling a half-truth. This
    is the line that names the other half.
    """
    root = Path(root).resolve()
    model = build_model(root, files)
    reaches, dormant = [], 0
    for m in model.modules:
        path = root / m.path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        found, _ = guarded_imports(tree, str(root), m.dotted)
        reaches.extend(f for f in found
                       if f.package not in model.packages and not _is_stdlib(f.package))
        dormant += len(dormant_tests(tree, str(root), m.dotted))
    packages = sorted({r.package for r in reaches})
    if not packages and not dormant:
        return None
    bits = []
    if packages:
        bits.append(f"reaches for {len(packages)} package(s) it does not provide "
                    f"({', '.join(packages[:5])}{' ...' if len(packages) > 5 else ''})")
    if dormant:
        bits.append(f"holds {dormant} dormant test(s)")
    return (f"ghost_buster: this repository {' and '.join(bits)}. Those seams are "
            f"UNCHECKED in a single-repo scan -- re-run with --join <path-to-each> "
            f"to verify them.")
