"""structure.py -- what this repository actually is, from evidence only.

THE ONE RULE

An observed file, symbol, import, declaration or execution result is
EVIDENCE. A statement about architectural responsibility, cohesion,
coupling, quality or intended design is INTERPRETATION. This module
emits evidence and refuses to emit interpretation, because the moment
the two are mixed a reader cannot tell which they are holding.

That is not a stylistic preference. The usual way to guess a module's
architectural role is its name -- `services/`, `adapters/`, `core/`,
`utils/` -- and a name is a claim its author made, not a fact about the
code. A structural model built on those names reports the architecture
somebody intended, which is precisely the thing worth checking against
the architecture they built.

So this module answers: what exists, where does it live, what does it
expose, what does it import, what imports it, where does execution
enter, what crosses which external boundary, what state lives outside a
function call, and what is verified. It does NOT answer: what is domain
logic, what is orchestration, whether a boundary is well placed, or
whether any of it is any good.

WHAT IT CANNOT SEE, IT NAMES

Dynamic imports, getattr dispatch, decorator-based registration,
plugin discovery and anything resolved at runtime are recorded in
`unresolved` rather than guessed at. A model that quietly omits what it
could not follow reads exactly like a model of a system with no dynamic
behaviour.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import corpus
from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "structure"

#: Standard-library and builtin modules that cross an external boundary,
#: grouped by the boundary they cross. Membership is evidence that the
#: module CAN reach that boundary, never that it does so on any given
#: call path -- the model says "imports subprocess", not "runs commands".
_BOUNDARIES: Dict[str, Tuple[str, ...]] = {
    "filesystem": ("shutil", "tempfile", "glob", "fileinput"),
    "network": ("socket", "http", "urllib", "ftplib", "smtplib", "requests",
                "httpx", "aiohttp", "websockets"),
    "subprocess": ("subprocess", "multiprocessing", "pty"),
    "database": ("sqlite3", "psycopg", "psycopg2", "pymysql", "sqlalchemy",
                 "asyncpg", "redis", "pymongo"),
    "randomness": ("random", "secrets"),
    "serialization": ("pickle", "marshal", "shelve"),
}

#: Boundaries whose modules are imported far more often than they are
#: crossed, so the IMPORT is not the evidence -- the call is.
#:
#: `pathlib` was in the filesystem list above until it was measured: 37 of
#: this project's 68 modules import it, and most only manipulate paths as
#: strings-with-methods without ever touching a disk. `sys` was in the
#: environment list and is imported by nearly everything. `datetime` is
#: usually a type, not a clock read. A model claiming those 37 modules
#: cross the filesystem is not wrong so much as useless, and a model whose
#: numbers cannot be acted on is the failure mode this module exists to
#: avoid.
_BOUNDARY_CALLS: Dict[str, Tuple[str, ...]] = {
    "filesystem": ("read_text", "write_text", "read_bytes", "write_bytes",
                   "mkdir", "rmdir", "unlink", "rename", "touch", "iterdir",
                   "rglob", "walk", "listdir", "remove", "makedirs", "stat"),
    "environment": ("getenv", "putenv", "environ"),
    "clock": ("now", "today", "utcnow", "monotonic", "perf_counter"),
    "randomness": ("uuid4", "uuid1", "token_hex", "token_bytes", "randint",
                   "choice", "shuffle", "random"),
}

#: Calls that reach a boundary without importing anything.
_BUILTIN_BOUNDARY_CALLS = {"open": "filesystem", "input": "stdin", "eval": "dynamic",
                           "exec": "dynamic", "compile": "dynamic", "__import__": "dynamic"}

_DATA_MODEL_BASES = frozenset({
    "BaseModel", "NamedTuple", "TypedDict", "Enum", "IntEnum", "StrEnum",
    "Protocol", "ABC", "Struct",
})
_DATA_MODEL_DECORATORS = frozenset({"dataclass", "attrs", "define", "frozen", "attr"})


@dataclass
class ModuleFacts:
    """One importable module, as observed. Every field is evidence."""
    dotted: str
    path: str
    is_package: bool = False
    public_names: List[str] = field(default_factory=list)   # __all__, if declared
    exported: List[str] = field(default_factory=list)       # top-level non-underscore defs
    internal: List[str] = field(default_factory=list)       # top-level _underscore defs
    imports_internal: List[str] = field(default_factory=list)
    imports_external: List[str] = field(default_factory=list)
    boundaries: List[str] = field(default_factory=list)
    module_state: List[str] = field(default_factory=list)   # mutable top-level bindings
    bindings: List[str] = field(default_factory=list)       # public top-level names bound
    reexports: List[str] = field(default_factory=list)      # names bound by a top-level import
    star_imports: List[str] = field(default_factory=list)   # `from X import *` targets
    guarded: List[str] = field(default_factory=list)        # imported inside try/except ImportError
    data_models: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)   # main(), __main__ guard
    raises: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)


@dataclass
class StructuralModel:
    """The repository, as observed. `unresolved` is load-bearing: a model
    that silently omits what it could not follow reads exactly like a
    model of a system with no dynamic behaviour."""
    root: str = ""
    ran: bool = False
    reason: str = ""
    distribution: Optional[str] = None
    declared_dependencies: List[str] = field(default_factory=list)
    dependency_sources: List[str] = field(default_factory=list)
    #: `[build-system].requires`. A declaration, but only for code that
    #: runs at build time: the frontend installs these into an isolated
    #: environment that no runtime import can see.
    build_requires: List[str] = field(default_factory=list)
    #: Modules that run at build time, not at import time -- setup.py and
    #: friends. Their imports are satisfied by `build_requires`.
    build_modules: List[str] = field(default_factory=list)
    #: What each packaging file declares, field by field, for the
    #: `parallel packaging metadata` check.
    packaging_declarations: Dict[str, Dict[str, str]] = field(default_factory=dict)
    console_scripts: Dict[str, str] = field(default_factory=dict)
    packages: List[str] = field(default_factory=list)
    modules: List[ModuleFacts] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)
    boundaries: Dict[str, List[str]] = field(default_factory=dict)
    test_modules: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    #: package name -> "file:line" for names parked in a comment in a
    #: dependency file. Evidence about an unresolvable name, never a
    #: declaration: see commented_out_dependencies.
    commented_out: Dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False) + "\n"


# --------------------------------------------------------------- packaging

@dataclass
class PyprojectFacts:
    """What pyproject.toml declares. A record rather than a tuple because
    the tuple had grown to four positions and was about to grow to six."""
    name: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    scripts: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    #: `[build-system].requires`, verbatim.
    build_requires: List[str] = field(default_factory=list)
    #: `[project]` fields that setup.py also declares, for drift detection.
    declarations: Dict[str, str] = field(default_factory=dict)


#: The fields a package can declare in two places at once. Compared as
#: strings after `_normalise_declaration`, because `[project]` and
#: `setup()` spell the same value differently often enough that a raw
#: comparison would report drift where there is none.
_PACKAGING_FIELDS = ("name", "version", "description", "requires-python", "dependencies")

#: Files that run when the package is BUILT, not when it is imported.
#: Their imports are satisfied by `[build-system].requires`.
_BUILD_TIME_FILES = frozenset({"setup.py"})

#: setup() keyword -> the `[project]` key that means the same thing.
_SETUP_TO_PROJECT = {
    "name": "name",
    "version": "version",
    "description": "description",
    "python_requires": "requires-python",
    "install_requires": "dependencies",
}


def _normalise_declaration(key: str, value) -> str:
    """One spelling for a declared value, so that only real disagreement
    reads as disagreement.

    `name` is compared the way a package index compares it (PEP 503:
    case-folded, runs of `-_.` collapsed), because `fortress-kernel` and
    `Fortress_Kernel` install the same thing. A dependency list is
    compared as a sorted set of requirement strings with whitespace
    stripped, because ordering is not a declaration.
    """
    if value is None:
        return ""
    if key == "name":
        import re as _re
        return _re.sub(r"[-_.]+", "-", str(value)).strip().lower()
    if isinstance(value, (list, tuple)):
        return ", ".join(sorted(str(v).strip() for v in value))
    return str(value).strip()


def _read_pyproject(root: Path) -> PyprojectFacts:
    import tomllib
    p = root / "pyproject.toml"
    if not p.is_file():
        return PyprojectFacts()
    try:
        with p.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as e:
        return PyprojectFacts(
            notes=[f"pyproject.toml could not be read: {type(e).__name__}: {e}"])
    project = data.get("project") or {}
    deps = [str(d) for d in (project.get("dependencies") or [])]
    # Optional dependencies are still declarations. Reading only
    # `project.dependencies` reported six packages as undeclared on a real
    # repository that declares every one of them under an extra.
    for extra in (project.get("optional-dependencies") or {}).values():
        deps.extend(str(d) for d in extra)
    for group in (data.get("dependency-groups") or {}).values():
        deps.extend(str(d) for d in group if isinstance(d, str))
    scripts = {str(k): str(v) for k, v in (project.get("scripts") or {}).items()}
    notes = []
    if project.get("dynamic"):
        # Declared dynamic: the real values live in the build backend, not here.
        notes.append(
            f"pyproject declares {project['dynamic']} as dynamic; those values are "
            f"resolved by the build backend and are not visible to this scan"
        )
    build = data.get("build-system") or {}
    build_requires = [str(r) for r in (build.get("requires") or [])]
    declarations = {
        key: _normalise_declaration(key, project[key])
        for key in _PACKAGING_FIELDS if key in project
    }
    return PyprojectFacts(
        name=project.get("name"), dependencies=deps, scripts=scripts, notes=notes,
        build_requires=build_requires, declarations=declarations,
    )


def _read_setup_py(root: Path) -> Optional[Dict[str, str]]:
    """What a literal `setup(...)` call in setup.py declares, or None.

    Only literal keyword arguments are read. A value computed at import
    time -- `version=read_version()`, `install_requires=parse(reqs)` -- is
    not a declaration this scan can compare against anything, and
    guessing at one would manufacture the disagreement the caller is
    about to report. None means "no setup.py, or nothing literal in it",
    which reads as "nothing to compare" at the call site rather than as
    "compared and agreed".
    """
    p = root / "setup.py"
    if not p.is_file():
        return None
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "setup":
            continue
        for kw in node.keywords:
            key = _SETUP_TO_PROJECT.get(kw.arg or "")
            if key is None:
                continue
            try:
                value = ast.literal_eval(kw.value)
            except (ValueError, SyntaxError):
                continue        # computed, so not a declaration to compare
            out[key] = _normalise_declaration(key, value)
    return out or None


def _requirements_files(root: Path) -> List[Path]:
    return sorted(p for p in root.glob("requirements*.txt") if p.is_file())


def _read_requirements(paths: List[Path]) -> List[str]:
    out = []
    for p in paths:
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if line and not line.startswith("-"):
                    out.append(line)
        except OSError:
            continue
    return out


def commented_out_dependencies(root: Path) -> Dict[str, str]:
    """Package name -> "file:line", for names parked in a COMMENT in a
    dependency file. Never a declaration; evidence about a name.

    WHY A SCANNER READS THE COMMENTS (v1.8.0)

    `unresolvable dependency` below asks whether an imported name refers
    to anything at all, and it is the slopsquat check: a name a model
    invented, which an attacker can register because the invented names
    are predictable. It is a MAJOR finding with a paragraph about package
    fabrication attached, and it is right to be loud.

    A dependency somebody deliberately commented out produces exactly the
    same evidence. Measured on ATS 2026-09-17: `openai`,
    `sentence-transformers` and `voyageai`, each imported lazily by the
    one backend that uses it, each sitting commented out in
    requirements.txt directly above the code importing it, each reported
    as a name referring to nothing. Correct on the evidence the scan had
    -- and the evidence that separates the two cases was in the same file
    it had already read and thrown away at the `#`.

    The distinction is worth drawing because a hallucinated name never
    appears in a dependency file. Somebody typed this one there.

    IT DOES NOT CLEAR THE FINDING, and must not. A commented-out
    dependency is not installed by anything, so the import still fails at
    the first call; the reader is told where to look rather than told to
    stop looking. Severity is unchanged for the same reason: what changes
    is what the reader does next, not how bad it is.

    ONLY THE FIRST TOKEN of a comment is read, because that is where a
    commented-out requirement puts the name -- `# openai>=1.0`,
    `# sentence-transformers   # which backend`. Reading every token
    instead swept up the prose: a line reading `# Optional - only needed
    if you inject one` contributed `optional`, `only`, `needed`, `if`,
    `you` and `inject`, each of which would then answer for an import of
    that name. Substring matching is wrong for the same reason in the
    other direction: `ai` must not match `openai`, so the token is
    normalised the way `requirement_name` normalises a declaration and
    compared whole.
    """
    out: Dict[str, str] = {}
    for path in _requirements_files(root) + [root / "pyproject.toml"]:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            _, hash_, comment = line.partition("#")
            if not hash_:
                continue
            first = re.split(r"[\s,\[\]'\"()]+", comment.strip(), maxsplit=1)[0]
            name = requirement_name(first)
            # One character is not a package anybody parked on purpose, and
            # a bare number is a version fragment.
            if len(name) > 1 and not name.replace("-", "").isdigit():
                out.setdefault(name, f"{path.name}:{number}")
    return out


def requirement_name(spec: str) -> str:
    """The distribution name from a requirement string, lowercased with
    separators normalised -- 'ruff==0.15.22' and 'Ruff' are one package."""
    for sep in ("[", "=", ">", "<", "!", "~", ";", " "):
        spec = spec.split(sep, 1)[0]
    return spec.strip().lower().replace("_", "-").replace(".", "-")


# ------------------------------------------------------------ module facts

def _boundary_for(module: str) -> Optional[str]:
    top = module.split(".", 1)[0]
    for boundary, names in _BOUNDARIES.items():
        if top in names or module in names:
            return boundary
    return None


def _is_mutable_literal(node) -> bool:
    """A top-level binding to a container is state anything can reach and
    change. A binding to a string, number or tuple is a constant."""
    return isinstance(node, (ast.List, ast.Dict, ast.Set, ast.ListComp,
                             ast.DictComp, ast.SetComp))


def _model_kind(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name in _DATA_MODEL_BASES:
            return True
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name in _DATA_MODEL_DECORATORS:
            return True
    return False


def analyse_module(path: Path, root: Path, package_roots: Set[str]) -> Optional[ModuleFacts]:
    tree = corpus.parse(path)
    if tree is None:
        return None   # unassessable_file reports this; see mechanical.py

    rel = path.relative_to(root)
    dotted = ".".join(rel.with_suffix("").parts)
    facts = ModuleFacts(
        dotted=dotted, path=str(rel), is_package=(path.name == "__init__.py"),
    )

    for node in tree.body:
        # __all__ is the only DECLARED public surface. Everything else is
        # inference from a leading underscore, which is a convention.
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    facts.public_names = [
                        e.value for e in getattr(node.value, "elts", [])
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                elif isinstance(t, ast.Name):
                    if _is_mutable_literal(node.value):
                        facts.module_state.append(t.id)
                    # A public module-level constant is an export like any
                    # other. Collecting only defs and classes reported
                    # MINIMUM_MATCH_LENGTH as missing from a package that
                    # exports it on line one of a real repository.
                    if not t.id.startswith("_"):
                        facts.bindings.append(t.id)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.startswith("_"):
                facts.bindings.append(node.target.id)
        # A NAME BOUND BY AN IMPORT IS IMPORTABLE FROM THIS MODULE. That is
        # how a package presents a public surface: `__init__.py` pulls names
        # up out of submodules and callers write `from pkg import Name`.
        #
        # Collecting only definitions made every re-export invisible.
        # Measured 2026-09-10 joining two real repositories: four names that
        # a package re-exports through its `__init__` -- two by an explicit
        # line, two through a star-import -- were reported as a CRITICAL
        # "does not export them" against an import that runs fine.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    if isinstance(node, ast.ImportFrom) and node.module:
                        facts.star_imports.append(node.module)
                    continue
                bound = alias.asname or alias.name.split(".", 1)[0]
                if not bound.startswith("_"):
                    facts.reexports.append(bound)

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            (facts.internal if node.name.startswith("_") else facts.exported).append(node.name)
            if isinstance(node, ast.ClassDef) and _model_kind(node):
                facts.data_models.append(node.name)
            if node.name == "main":
                facts.entry_points.append(f"{dotted}:main")

    # An import written with a fallback is a boundary its author declared,
    # not a name that might be invented. Recorded here so the slopsquat
    # check can tell the two apart -- see derive_findings.
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
                _catches_import(h) for h in node.handlers):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Import):
                    facts.guarded.extend(a.name.split(".", 1)[0] for a in inner.names)
                elif isinstance(inner, ast.ImportFrom) and inner.module and not inner.level:
                    facts.guarded.append(inner.module.split(".", 1)[0])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _record_import(facts, alias.name, package_roots)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                facts.imports_internal.append("." * node.level + (node.module or ""))
            elif node.module:
                _record_import(facts, node.module, package_roots)
        elif isinstance(node, ast.Raise) and node.exc is not None:
            exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = exc.attr if isinstance(exc, ast.Attribute) else getattr(exc, "id", "")
            if name and name not in facts.raises:
                facts.raises.append(name)
        elif isinstance(node, ast.Call):
            fn = getattr(node.func, "id", "")
            if fn in _BUILTIN_BOUNDARY_CALLS:
                b = _BUILTIN_BOUNDARY_CALLS[fn]
                if b in ("dynamic",):
                    facts.unresolved.append(f"{dotted} calls {fn}() -- resolved at runtime")
                elif b not in facts.boundaries:
                    facts.boundaries.append(b)
            attr = node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if attr:
                for boundary, names in _BOUNDARY_CALLS.items():
                    if attr in names and boundary not in facts.boundaries:
                        facts.boundaries.append(boundary)
            if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) > 1:
                if not isinstance(node.args[1], ast.Constant):
                    facts.unresolved.append(
                        f"{dotted} uses getattr with a computed name -- the target "
                        f"cannot be resolved statically")
        elif isinstance(node, ast.Attribute) and node.attr == "environ":
            if "environment" not in facts.boundaries:
                facts.boundaries.append("environment")
        elif isinstance(node, ast.If):
            test = node.test
            if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"):
                facts.entry_points.append(f"{dotted}:__main__ guard")

    facts.boundaries = sorted(set(facts.boundaries))
    facts.bindings = sorted(set(facts.bindings))
    facts.guarded = sorted(set(facts.guarded))
    facts.imports_internal = sorted(set(facts.imports_internal))
    facts.imports_external = sorted(set(facts.imports_external))
    facts.unresolved = sorted(set(facts.unresolved))
    return facts


def _catches_import(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if t is None:
        return True
    names = [t] if not isinstance(t, ast.Tuple) else list(t.elts)
    for n in names:
        name = n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", "")
        if name in ("ImportError", "ModuleNotFoundError", "Exception", "BaseException"):
            return True
    return False


def _record_import(facts: ModuleFacts, module: str, package_roots: Set[str]) -> None:
    top = module.split(".", 1)[0]
    if top in package_roots:
        facts.imports_internal.append(module)
    else:
        facts.imports_external.append(module)
    boundary = _boundary_for(module)
    if boundary and boundary not in facts.boundaries:
        facts.boundaries.append(boundary)


# ------------------------------------------------------------------ scan

#: Directories that hold packages without being one themselves. The src
#: layout is mainstream, and a scan that does not know it reports a
#: repository as importing a package it actually provides.
#:
#: Measured across a 37-repository library: TIE holds src/tie/__init__.py
#: and GEMS holds src/gems/__init__.py, and both were reported as reaching
#: for an unresolvable outside package called after themselves. A repo
#: importing itself is the clearest possible false positive.
_PACKAGE_PARENTS = ("src", "lib", "python")


def _package_roots(root: Path) -> Set[str]:
    """Top-level importable names this repository defines. Used only to
    split imports into internal and external -- not to claim anything
    about layering."""
    roots = set()

    def _scan(d: Path) -> None:
        try:
            children = list(d.iterdir())
        except OSError:
            return
        for child in children:
            if child.is_dir() and (child / "__init__.py").is_file():
                roots.add(child.name)
            elif child.is_file() and child.suffix == ".py":
                roots.add(child.stem)

    _scan(root)
    for parent in _PACKAGE_PARENTS:
        d = root / parent
        if d.is_dir() and not (d / "__init__.py").is_file():
            _scan(d)
    return roots


def build_model(root, files) -> StructuralModel:
    root = Path(root).resolve()
    model = StructuralModel(root=str(root))
    if not root.is_dir():
        model.reason = f"{root} is not a directory"
        return model
    model.ran = True

    facts = _read_pyproject(root)
    name, deps, scripts = facts.name, facts.dependencies, facts.scripts
    model.distribution = name
    model.console_scripts = scripts
    model.unresolved.extend(facts.notes)
    model.build_requires = sorted({requirement_name(r) for r in facts.build_requires} - {""})
    if facts.declarations:
        model.packaging_declarations["pyproject.toml"] = facts.declarations
    setup_declarations = _read_setup_py(root)
    if setup_declarations is not None:
        model.packaging_declarations["setup.py"] = setup_declarations
    if deps:
        model.dependency_sources.append("pyproject.toml:project.dependencies")
    req_files = _requirements_files(root)
    req_deps = _read_requirements(req_files)
    if req_deps:
        model.dependency_sources.extend(str(p.relative_to(root)) for p in req_files)
    model.declared_dependencies = sorted({requirement_name(d) for d in deps + req_deps} - {""})
    model.commented_out = commented_out_dependencies(root)

    roots = _package_roots(root)
    model.packages = sorted(roots)

    for path in sorted(p for p in files if p.suffix == ".py"):
        # `files` may be relative to the working directory while `root` is
        # resolved absolute. Resolving both was NOT the first version of
        # this loop, and the result was every module silently skipped, a
        # model reporting 0 modules, and four false "entry point target
        # missing" findings for console scripts whose targets were simply
        # never scanned. Silence read as absence, in the module written to
        # stop exactly that.
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        facts = analyse_module(resolved, root, roots)
        if facts is None:
            continue
        model.modules.append(facts)
        model.entry_points.extend(facts.entry_points)
        model.unresolved.extend(facts.unresolved)
        relative = Path(facts.path)
        if "test" in relative.name or "tests" in relative.parts:
            model.test_modules.append(facts.dotted)
        elif relative.name in _BUILD_TIME_FILES and len(relative.parts) == 1:
            model.build_modules.append(facts.dotted)

    for facts in model.modules:
        for boundary in facts.boundaries:
            model.boundaries.setdefault(boundary, []).append(facts.dotted)
    model.boundaries = {k: sorted(v) for k, v in sorted(model.boundaries.items())}

    for script, target in sorted(scripts.items()):
        model.entry_points.append(f"console_script {script} -> {target}")
    model.entry_points = sorted(set(model.entry_points))
    model.unresolved = sorted(set(model.unresolved))
    return model


# --------------------------------------------------------------- findings

def _finding(model: StructuralModel, kind: str, severity: Severity, file: str,
             summary: str, detail: str, attributes: dict,
             identity_key: Optional[str] = None) -> Finding:
    return Finding(
        detector=DETECTOR, category=Category.ARCHITECTURE, layer=Layer.MECHANICAL,
        severity=severity, status=Status.CONFIRMED,
        summary=f"{kind}: {summary}", evidence=Evidence(file=file),
        detail=detail, attributes=dict(attributes, kind=kind),
        identity_key=identity_key,
    )


def _external_imports(model: StructuralModel, stdlib: Set[str]) -> Dict[str, List[str]]:
    """package name -> the modules that import it, for everything the
    repository reaches for and does not provide.

    Two exemptions, and they are not the same exemption. A TEST module's
    imports are skipped outright: test-only tools live in dev extras this
    scan cannot see. A BUILD-TIME module's imports are skipped only when
    `[build-system].requires` declares them -- setup.py importing
    setuptools was reported as an undeclared dependency on a repository
    that declares it in the one correct place, because a PEP 517 frontend
    installs that list into an isolated environment before setup.py is
    ever imported. A build requirement a build-time file imports and
    nobody declared is still reported.
    """
    imported: Dict[str, List[str]] = {}
    build_declared = set(model.declared_dependencies) | set(model.build_requires)
    for facts in model.modules:
        if facts.dotted in model.test_modules:
            continue
        at_build_time = facts.dotted in model.build_modules
        for module in facts.imports_external:
            top = module.split(".", 1)[0]
            if top in stdlib or top.startswith("_"):
                continue
            package = top.lower().replace("_", "-")
            if at_build_time and package in build_declared:
                continue
            imported.setdefault(package, []).append(facts.dotted)
    return imported


def _packaging_findings(model: StructuralModel) -> List[Finding]:
    """setup.py and pyproject.toml declaring the same package, differently.

    Two files that both say what this package is called, what version it
    is, and what it depends on are two answers to one question, and which
    one an installer believes depends on how it was invoked: a PEP 517
    frontend reads pyproject.toml, `python setup.py` reads setup.py, and
    an older pip reads whichever it finds first. Nobody edits both.

    So the finding is graded by whether they still agree. Disagreeing is
    MAJOR: one of the two answers is already wrong and the package
    installs differently depending on the route. Agreeing is MINOR --
    nothing is broken today, and the defect is that keeping it that way
    is a thing somebody has to remember, with no check that they did.
    """
    declared = model.packaging_declarations
    pyproject = declared.get("pyproject.toml")
    setup = declared.get("setup.py")
    if not pyproject or not setup:
        return []
    shared = sorted(set(pyproject) & set(setup))
    if not shared:
        return []
    drifted = [k for k in shared if pyproject[k] != setup[k]]
    root = Path(model.root)
    if drifted:
        lines = "; ".join(
            f"{k}: pyproject.toml says {pyproject[k]!r}, setup.py says {setup[k]!r}"
            for k in drifted
        )
        return [_finding(
            model, "parallel packaging metadata", Severity.MAJOR,
            str(root / "setup.py"),
            f"setup.py and pyproject.toml declare {len(shared)} of the same "
            f"field(s) and {len(drifted)} disagree -- {lines}",
            "Two files declare this package and they no longer say the same "
            "thing. Which one is true depends on how the package is built: a "
            "PEP 517 frontend (`pip install .`, `build`) reads pyproject.toml "
            "and never executes setup.py's arguments; a direct `python setup.py "
            "...` reads setup.py and never opens pyproject.toml. So both "
            "answers ship, and the one a given user gets is decided by their "
            "tooling rather than by anyone here.\n\n"
            "The fix is almost always to delete the duplicate rather than to "
            "reconcile it: move anything setup.py declares that pyproject.toml "
            "does not into `[project]`, and leave setup.py out entirely, or "
            "reduce it to a bare `setup()` call that reads its arguments from "
            "pyproject.toml.\n\nScope limit: only literal values are "
            "compared. A version computed at import time is not a declaration "
            "this scan can read, and is not counted on either side.",
            {"fields": ", ".join(shared), "drifted": ", ".join(drifted)},
            identity_key="parallel packaging metadata",
        )]
    return [_finding(
        model, "parallel packaging metadata", Severity.MINOR,
        str(root / "setup.py"),
        f"setup.py and pyproject.toml both declare {', '.join(shared)}, and "
        f"agree today",
        "Nothing is broken right now: both files say the same thing. The "
        "defect is that they will only keep saying it for as long as "
        "everybody who edits one remembers the other, and nothing here "
        "checks that they did. This is reported at MINOR for exactly that "
        "reason -- it is a maintenance obligation nobody agreed to, not a "
        "bug. It becomes MAJOR the day the two answers differ.\n\n"
        "Scope limit: only literal values are compared, so a field whose "
        "value is computed at import time is not counted on either side.",
        {"fields": ", ".join(shared)},
        identity_key="parallel packaging metadata",
    )]


def derive_findings(model: StructuralModel) -> List[Finding]:
    """Only what the evidence establishes on its own. Nothing here is a
    judgement about architecture; each is a contradiction between two
    observed facts."""
    if not model.ran:
        return []
    out: List[Finding] = []
    # Before the guard below: packaging metadata is read from the files
    # themselves, so it is knowable even when no module was scanned, and
    # skipping it there would be an unreported blind spot.
    out.extend(_packaging_findings(model))
    if not model.modules:
        # Nothing was scanned, so "this symbol does not exist" and "this
        # symbol was not looked at" are indistinguishable. Reporting the
        # first would be inventing evidence.
        model.unresolved.append(
            "no modules were scanned, so entry-point targets and dependency "
            "usage could not be checked"
        )
        return out
    by_dotted = {m.dotted: m for m in model.modules}

    # 1. A console script whose target does not exist.
    for script, target in sorted(model.console_scripts.items()):
        module, _, symbol = target.partition(":")
        facts = by_dotted.get(module) or by_dotted.get(module + ".__init__")
        if facts is None:
            reason = f"module '{module}' was not found in the scanned set"
        elif symbol and symbol not in facts.exported and symbol not in facts.internal:
            reason = f"module '{module}' defines no top-level '{symbol}'"
        else:
            continue
        out.append(_finding(
            model, "entry point target missing", Severity.MAJOR,
            str(Path(model.root) / "pyproject.toml"),
            f"console script '{script}' points at '{target}', but {reason}",
            "An installed console script that cannot import its target fails at "
            "the moment somebody runs it, which is after install, after CI, and "
            "usually in front of the person you least wanted to show it to. "
            "Two observed facts contradict each other here: the declaration and "
            "the code.\n\nScope limit: a target reached by dynamic import or "
            "re-export from a package __init__ that this scan could not follow "
            "would look identical. Check before deleting the declaration.",
            {"script": script, "target": target},
        ))

    # 2. Imported and never declared.
    declared = set(model.declared_dependencies)
    stdlib = _stdlib_names()
    imported = _external_imports(model, stdlib)

    mapping = _import_to_distribution()

    # 3. A name that refers to nothing real -- the slopsquat surface.
    #
    # The 2026 attack, and the one this toolkit was closest to catching
    # without actually catching it. A model asked for working code emits an
    # import for a package it has invented: USENIX tested 16 models over
    # 576,000 samples and found 38% of hallucinated names are conflations
    # of two real packages, 13% typo variants, 51% pure fabrication. The
    # names are PREDICTABLE, so attackers register them and wait.
    #
    # `undeclared dependency` above asks whether an import is declared.
    # This asks something harder and more useful: whether the name refers
    # to anything at all. A package that is not standard library, not
    # installed here, not provided by this repository or any joined one,
    # and not declared anywhere is a name with nothing behind it. Today it
    # is an ImportError. The day somebody registers it, it is theirs.
    # Every package anyone reached for behind a fallback. Its author knew it
    # might be absent and wrote code for that case, which is the opposite of
    # a name a model invented believing it was real. boundary.py reports
    # these as `boundary provider absent`; repeating them here at MAJOR
    # would be the same fact twice, louder.
    guarded = {g.lower().replace("_", "-") for m in model.modules for g in m.guarded}
    local = {m.dotted.split(".", 1)[0] for m in model.modules}
    unresolvable = sorted(
        pkg for pkg in imported
        if pkg not in declared and pkg not in mapping and pkg not in guarded
        and pkg.replace("-", "_") not in local
    )
    for package in unresolvable:
        # A name somebody parked in a comment in a dependency file is still
        # undeclared -- nothing installs a comment -- but it is not the
        # invented name this finding's detail is mostly about, and the
        # reader's next move is different. Severity is untouched: what
        # changes is where to look, not how bad it is.
        parked = model.commented_out.get(package)
        parked_note = (
            f"\n\nSOMEBODY TYPED THIS NAME ON PURPOSE: it appears commented "
            f"out at {parked}. A commented-out dependency is not a "
            f"declaration -- nothing installs a comment, so the import still "
            f"fails at the first call -- but a name a model invented does not "
            f"appear in a dependency file at all. Read this as the first "
            f"case: declare it (an extra, or a second requirements file) if "
            f"the import is meant to work, or delete the import if it is not."
        ) if parked else ""
        out.append(_finding(
            model, "unresolvable dependency", Severity.MAJOR,
            str(Path(model.root)),
            f"'{package}' is imported but is not standard library, not installed "
            f"here, not provided by this repository, and declared nowhere"
            + (f" (though commented out at {parked})" if parked else ""),
            "This name refers to nothing that can be found. Two readings, and "
            "the tool cannot tell them apart, which is exactly why it says so "
            "rather than choosing:\n\n"
            "  * The environment is incomplete -- the package is real and simply "
            "not installed where this scan ran. Install it, or declare it, and "
            "this finding goes away.\n"
            "  * The name was invented. A model asked for working code emitted "
            "an import for a package that does not exist. Measured across 16 "
            "models and 576,000 samples: 38% of such names are conflations of "
            "two real packages, 13% are typo variants, 51% are pure fabrication. "
            "Because the names are predictable, they get registered by people "
            "who want you to install them -- a hallucinated npm package spread "
            "through 237 repositories in January 2026 with nobody planting it, "
            "and a fabricated 'huggingface-cli' with no code was downloaded "
            "30,000 times in three months.\n\n"
            "Both readings are cheap to resolve and expensive to ignore. Look "
            "the name up in the registry before the next `pip install` does it "
            "for you." + parked_note,
            dict({"package": package,
                  "imported_by": ", ".join(sorted(imported[package])[:5])},
                 **({"commented_out_at": parked} if parked else {})),
        ))

    if model.dependency_sources:
        for package, users in sorted(imported.items()):
            if package in declared:
                continue
            distribution = mapping.get(package)
            if distribution is None:
                # Undecidable, not undeclared. Recorded so the gap is
                # visible instead of being reported as a fact.
                model.unresolved.append(
                    f"import '{package}' could not be mapped to a distribution "
                    f"name (not installed in the scanning environment), so "
                    f"whether it is declared cannot be established here"
                )
                continue
            if distribution in declared:
                continue
            out.append(_finding(
                model, "undeclared dependency", Severity.MAJOR,
                str(Path(model.root) / (model.dependency_sources[0].split(":")[0])),
                f"'{package}' (distribution '{distribution}') is imported by "
                f"{len(users)} module(s) and appears in no dependency declaration",
                "This is the works-on-my-machine failure: the package is installed "
                "in the environment it was written in and nowhere else. A fresh "
                "clone, a CI runner or a production image gets an ImportError at "
                "the first import.\n\nScope limit: a package installed as a "
                "transitive dependency of something declared will work by accident "
                "until that intermediate drops it. That is still undeclared.",
                {"package": package, "distribution": distribution, "imported_by": ", ".join(sorted(users)[:5])},
            ))

    return out


def _stdlib_names() -> Set[str]:
    import sys
    names = set(getattr(sys, "stdlib_module_names", ()))
    return names | {"__future__", "typing", "dataclasses"}


def _import_to_distribution() -> Dict[str, str]:
    """Import name -> distribution name, for what is installed here.

    WHY THIS IS NOT OPTIONAL, AND WHY IT IS NOT SUFFICIENT

    An import name is not a distribution name. `yaml` ships in PyYAML,
    `PIL` in pillow, `sklearn` in scikit-learn, `cv2` in opencv-python.
    Measured on a real repository, comparing import names directly against
    declared names reported six packages as undeclared that were all
    declared, one of them as `ccc` against a declaration of
    `cognitive-continuity-constitution`.

    This mapping is exact for packages installed in the environment doing
    the scanning. For a bare clone with nothing installed it is empty, and
    an unmappable import is then genuinely undecidable -- a missing
    declaration and an ordinary alias look identical. Those go to
    `unresolved` rather than becoming findings.
    """
    try:
        from importlib.metadata import packages_distributions
    except ImportError:
        return {}
    out = {}
    try:
        for import_name, dists in packages_distributions().items():
            for dist in dists:
                out[import_name.lower().replace("_", "-")] = \
                    dist.lower().replace("_", "-").replace(".", "-")
    except Exception:
        return {}
    return out


# ----------------------------------------------------------------- report

def render_model(model: StructuralModel) -> str:
    """The human-readable model. Every line is an observation; the closing
    section is what could not be observed."""
    if not model.ran:
        return f"structural model did not run: {model.reason}"
    L = [f"STRUCTURAL MODEL -- {model.root}", "=" * 72, ""]

    L.append("PACKAGING")
    L.append(f"  distribution      : {model.distribution or '(none declared)'}")
    L.append(f"  importable roots  : {', '.join(model.packages) or '(none)'}")
    L.append(f"  dependency sources: {', '.join(model.dependency_sources) or '(none found)'}")
    L.append(f"  declared deps     : {len(model.declared_dependencies)}")
    L.append("")

    L.append("EXECUTION ENTRY POINTS")
    for ep in model.entry_points or ["  (none found)"]:
        L.append(f"  {ep}" if not ep.startswith(" ") else ep)
    L.append("")

    L.append("EXTERNAL BOUNDARIES CROSSED")
    if not model.boundaries:
        L.append("  (none observed)")
    for boundary, modules in model.boundaries.items():
        L.append(f"  {boundary:14} {len(modules)} module(s): "
                 f"{', '.join(modules[:4])}{' ...' if len(modules) > 4 else ''}")
    L.append("")

    stateful = [m for m in model.modules if m.module_state]
    L.append(f"MODULE-LEVEL MUTABLE STATE ({len(stateful)} module(s))")
    for m in stateful[:10]:
        L.append(f"  {m.dotted}: {', '.join(m.module_state)}")
    if not stateful:
        L.append("  (none observed)")
    L.append("")

    declared_public = [m for m in model.modules if m.public_names]
    L.append("INTERFACE SURFACE")
    L.append(f"  modules             : {len(model.modules)}")
    L.append(f"  with a declared __all__: {len(declared_public)}")
    L.append(f"  data representations: "
             f"{sum(len(m.data_models) for m in model.modules)}")
    L.append(f"  test modules        : {len(model.test_modules)}")
    L.append("")

    L.append(f"UNRESOLVED ({len(model.unresolved)})")
    L.append("  Recorded rather than guessed. A model that omits what it could")
    L.append("  not follow reads like a model of a system with no dynamic behaviour.")
    for note in model.unresolved[:12] or ["  (nothing dynamic observed)"]:
        L.append(f"  - {note}" if not note.startswith(" ") else note)
    if len(model.unresolved) > 12:
        L.append(f"  ... and {len(model.unresolved) - 12} more")
    L.append("")

    L.append("NOT ANSWERED HERE, ON PURPOSE")
    L.append("  Which modules are domain logic, orchestration, adapters or")
    L.append("  infrastructure; whether any boundary is well placed; whether the")
    L.append("  structure is good. Those are interpretations. The only mechanical")
    L.append("  way to reach them is the directory name, and a name is a claim its")
    L.append("  author made -- not a fact about the code, and precisely the thing")
    L.append("  worth checking this model against.")
    return "\n".join(L)


def render_report(model: StructuralModel, findings: List[Finding]) -> str:
    """The one-line summary, on the same channel as every other check."""
    if not model.ran:
        return f"ghost_buster: structure scan did not run: {model.reason}"
    return (f"ghost_buster: structure scan mapped {len(model.modules)} module(s), "
            f"{len(model.entry_points)} entry point(s), "
            f"{len(model.boundaries)} external boundary kind(s), "
            f"{len(model.unresolved)} unresolved; {len(findings)} finding(s)")
