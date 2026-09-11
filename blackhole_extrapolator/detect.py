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
import importlib.util
import sys
import re
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


# Directories never descended into. site-packages is the load-bearing one:
# it catches an installed-package tree whatever the enclosing virtualenv is
# called. Without this a scan of a repo with a 5 GB venv in its working tree
# walks the venv -- measured: sentinel_os did not finish in two minutes, and
# the analysis of its own 51k lines takes about seven seconds.
_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "site-packages", ".venv", "venv", "env",
    "node_modules", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox",
    "build", "dist", ".eggs",
})


def _source_files(root: Path) -> list[Path]:
    """Every .py under root worth analysing."""
    return [p for p in root.rglob("*.py") if not _SKIP_DIRS & set(p.parts)]


def _available_modules(search_roots: Sequence[Path]) -> set[str]:
    """Every module name importable from these roots.

    Packages count. A directory containing __init__.py is importable by its
    directory name, and omitting that reported every `import ccc` in a
    perfectly healthy repository as a test orphaned by a missing module --
    measured at 25 false positives out of 25 signals on a clean, fully-tested
    package. A detector with that hit rate does not get read twice.
    """
    available: set[str] = set()
    for root in search_roots:
        if not root.is_dir():
            continue
        for path in _source_files(root):
            available.add(path.stem)
            if path.name == "__init__.py":
                available.add(path.parent.name)
        # A directory with Python anywhere beneath it is importable as a
        # namespace package too. Beneath, not directly inside: ecology's
        # `src/` holds only sub-packages, and `import src.rag` was reported
        # missing 38 times on the first full-library run.
        for path in root.rglob("*/"):
            if path.is_dir() and not _SKIP_DIRS & set(path.parts) and \
                    any(not _SKIP_DIRS & set(p.parts) for p in path.rglob("*.py")):
                available.add(path.name)
    return available


# WHY `__import__` IS NOT THE TEST
#
# Until 2026-09-10 a module was considered real if `__import__` succeeded.
# That asks "is it installed on the machine running the scan", which is a
# fact about a container, not about the code. Measured across a
# 37-repository library on a runner with no scientific stack: `matplotlib`,
# `torch`, `cv2`, `sentence_transformers`, `pandas`, `joblib`, `lightgbm`
# and `openai` were all reported as absences whose shape should be
# reconstructed. Run the same scan on a laptop with those installed and the
# voids evaporate.
#
# So resolution is checked against things that do not move: the standard
# library for this interpreter, the builtins, the typing vocabulary, and
# only then what happens to be installed.
_STDLIB = frozenset(sys.stdlib_module_names)
# `Dict` and `Any` used unimported are not modules at all, and an outline of
# their "shape" is nonsense. They are here so the report says `import` and
# not `void`.
_TYPING_NAMES = frozenset({
    "Any", "AnyStr", "Awaitable", "Callable", "ClassVar", "Coroutine",
    "Dict", "Final", "FrozenSet", "Generator", "Generic", "Iterable",
    "Iterator", "List", "Literal", "Mapping", "NamedTuple", "NoReturn",
    "Optional", "Protocol", "Sequence", "Set", "Tuple", "Type", "TypeVar",
    "TypedDict", "Union",
})


def resolution(name: str) -> str | None:
    """Why a name this tree does not define is nonetheless not missing.

    Returns a phrase naming where it lives, or None when nothing here can
    account for it. The order is deliberate: the checks that hold on every
    machine come before the one that depends on this one.
    """
    if name in _STDLIB:
        return "the standard library"
    if name in _TYPING_NAMES:
        return "typing"
    if name in _BUILTINS:
        return "builtins"
    try:
        if importlib.util.find_spec(name) is not None:
            return "installed in this environment"
    except (ImportError, ValueError, ModuleNotFoundError):
        pass
    return None


def _normalise_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name.strip().lower())


# Distribution names that provide a differently named top-level module. The
# generic rule below (the first token of the distribution name) covers
# psycopg2-binary, opentelemetry-api, google-generativeai and most others;
# these are the common ones it cannot.
_IMPORT_ALIASES = {
    "pyyaml": "yaml", "pillow": "PIL", "beautifulsoup4": "bs4",
    "scikit_learn": "sklearn", "python_dateutil": "dateutil",
    "python_dotenv": "dotenv", "attrs": "attr", "pyjwt": "jwt",
}


def _import_names(dist: str) -> set[str]:  # ghost_buster: name-disagreement -- `dist` is `token` at every call site
    """Top-level module names a declared distribution plausibly provides."""
    name = _normalise_dist(dist)
    return {name, name.split("_", 1)[0], _IMPORT_ALIASES.get(name, name)}


def _declared_dependencies(root: Path) -> set[str]:
    """Top-level names a project says it depends on, from requirements files
    and pyproject, normalised the way pip does. Best effort: the import name
    and the distribution name usually match, and when they do not the module
    is reported as unresolved rather than guessed."""
    names: set[str] = set()
    # Requirements files anywhere in the tree, not only at the root:
    # sentinel_os keeps its own one directory down. `-r other.txt` includes
    # are followed relative to the including file; GSA-815's requirements
    # is a single include pointing into a submodule.
    seen: set[Path] = set()
    queue = [req for req in root.rglob("requirements*.txt")
             if not _SKIP_DIRS & set(req.relative_to(root).parts)]
    queue += list(root.glob("requirements/*.txt"))
    while queue:
        req = queue.pop().resolve()
        if req in seen or not req.is_file():
            continue
        seen.add(req)
        for line in req.read_text(errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            include = re.match(r"^(?:-r|--requirement)\s+(\S+)", line)
            if include:
                queue.append(req.parent / include.group(1))
                continue
            # URLs, editable installs and pip options are not distributions.
            # `http` alone also skipped `httpx<0.28`, so the one dependency
            # sentinel_os pins with a comment read as its one void.
            if line.startswith(("-", "git+", "http://", "https://")):
                continue
            token = re.split(r"[<>=!~;\[\s]", line, 1)[0]
            if token:
                names |= _import_names(token)  # ghost_buster: name-disagreement -- `token` is `dist` in the signature
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(errors="replace")
        # `dependencies = [...]` plus every list in [project.optional-dependencies]:
        # an optional extra is still a declared provider, not a lost module.
        blocks = re.findall(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
        optional = re.search(r"\[project\.optional-dependencies\](.*?)(?:\n\[|\Z)", text, re.S)
        if optional:
            blocks += re.findall(r"=\s*\[(.*?)\]", optional.group(1), re.S)
        for block in blocks:
            for token in re.findall(r"[\"']([A-Za-z0-9_.\-]+)", block):
                names |= _import_names(token)  # ghost_buster: name-disagreement -- `token` is `dist` in the signature
    return names


def _submodules(root: Path) -> list[tuple[str, bool]]:
    """(path, initialised) for every git submodule the tree declares."""
    modules_file = root / ".gitmodules"
    if not modules_file.is_file():
        return []
    out = []
    for path in re.findall(r"^\s*path\s*=\s*(\S+)", modules_file.read_text(errors="replace"), re.M):
        target = root / path
        initialised = target.is_dir() and any(target.rglob("*.py"))
        out.append((path, initialised))
    return out


def false_absence_hints(root: Path, siblings: Sequence[Path] = ()) -> list[str]:
    """Reasons a scan of this tree may report absences that are not absences.

    The one hint that existed -- an uninitialised git submodule -- was the
    most useful line the tool printed, because it named a specific way the
    finding could be wrong and said how to check. Measured 2026-09-10, the
    same class of error accounted for every wrong claim made about a single
    module that day: each came from a scan whose scope was narrower than the
    claim drawn from it.

    So the hint is generalised. These are conditions of the SCAN, attached
    once to the run rather than to any one void, because they explain the
    report and not the code.
    """
    root = Path(root)
    hints: list[str] = []

    for path, initialised in _submodules(root):
        if not initialised:
            hints.append(
                f"git submodule `{path}` is declared but not initialised. Run "
                "`git submodule update --init` and rescan: everything it would "
                "provide currently reads as missing.")

    if not siblings:
        hints.append(
            "no sibling checkout was supplied. A module another repository in "
            "this ecosystem provides is indistinguishable from a lost one "
            "here -- pass --sibling, or scan the parent directory with "
            "--ecosystem.")

    gitignore = root / ".gitignore"
    if gitignore.is_file():
        ignored = [line.strip() for line in
                   gitignore.read_text(errors="replace").splitlines()
                   if line.strip().endswith(".py")]
        if ignored:
            hints.append(
                f".gitignore excludes Python by name ({', '.join(ignored[:3])}). "
                "A file present on disk but ignored is still scanned; one "
                "absent from this checkout and ignored is not lost.")

    return hints


def resolve_providers(root: Path, siblings: Sequence[Path] = ()) -> dict[str, str]:
    """Module name -> who provides it, for everything this tree does not.

    Three sources, in the order a reader would want them named: a sibling
    checkout that defines the module; a dependency the project declares but
    that is not installed here; a git submodule declared in .gitmodules.
    An uninitialised submodule cannot say which modules it would provide, so
    it is attached to every otherwise-unresolved import as a note, never as
    a claim.
    """
    root = Path(root)
    providers: dict[str, str] = {}
    for sibling in siblings:
        sibling = Path(sibling)
        if not sibling.is_dir() or sibling.resolve() == root.resolve():
            continue
        for name in _available_modules([sibling]):
            providers.setdefault(name, f"sibling checkout `{sibling.name}` ({sibling})")
    for name in _declared_dependencies(root):
        providers.setdefault(name, "declared dependency (not installed in this environment)")
    for path, initialised in _submodules(root):
        if not initialised:
            providers.setdefault("__uninitialised_submodule__", path)
    return providers


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

        # A name the language already provides, used without importing it,
        # is a missing import and not a missing thing. Emitted before the
        # attribute survey because that survey would otherwise describe the
        # standard library back to the reader as an interface to rebuild.
        where = resolution(name)
        if where:
            yield NegativeEvidence(
                kind=EvidenceKind.MISSING_IMPORT,
                detail=(f"`{name}` is used but never imported; it is part of "
                        f"{where}. The fix is an import, not a reconstruction."),
                file=str(path), line=node.lineno,
            )
            continue

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


def path_root(path: Path) -> Path:
    """The checkout a file belongs to: the nearest ancestor holding .git,
    falling back to its own directory. Needed because the import detector
    is handed one file, and whether a dependency was DECLARED is a fact
    about the repository around it."""
    path = Path(path)
    for parent in [path] + list(path.parents):
        if (parent / ".git").exists():
            return parent
    return path.parent


def detect_missing_imports(path: Path, search_roots: Sequence[Path],
                           source: str | None = None,
                           providers: dict[str, str] | None = None) -> Iterator[NegativeEvidence]:
    """Imports of modules that exist nowhere under the search roots.

    Distinguished from a dangling name because the evidence is different: an
    import names the missing thing directly, and `from x import a, b, c` also
    enumerates part of its public surface.

    With `providers` (see resolve_providers), an import that something else
    known would satisfy is reported as WIRING rather than MISSING_MODULE: the
    module is not in this tree, and it is not lost either.
    """
    text = source if source is not None else path.read_text(errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return

    available = _available_modules(search_roots)

    declares: bool | None = None
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
        if resolution(module):     # stdlib, builtins, typing, or installed
            continue
        providers = providers or {}
        provider = providers.get(module) or providers.get(_normalise_dist(module))
        if provider:
            yield NegativeEvidence(
                kind=EvidenceKind.WIRING,
                detail=f"module `{module}` is not in this tree; provided by {provider}",
                file=str(path), line=node.lineno,
            )
            continue
        # Everything checkable has been checked and none of it accounts for
        # this. That is not the same as knowing it was lost: an undeclared
        # package on an index this scan cannot reach looks identical from
        # here. Say which checks were run, and let corroborating evidence --
        # a dangling attribute use, debris, an orphaned test -- decide
        # whether this is an absence or a dependency nobody wrote down.
        # Whether the project declares dependencies AT ALL changes what this
        # finding means. A repository with a populated pyproject that omits
        # this import has a manifest bug worth fixing today; one that
        # declares nothing cannot be said to have omitted anything.
        if declares is None:
            # Once per file, and only when a finding needs it: the manifest
            # read used to happen inside the loop for every unresolved import.
            declares = bool(_declared_dependencies(path_root(path)))
        manifest = ("the project declares dependencies and this is not among them"
                    if declares else
                    "the project declares no dependencies anywhere, so nothing "
                    "here can say whether it was meant to")
        detail = (f"module `{module}` is imported; it is not in the search roots, "
                  "not provided by a sibling, and not in the standard library; "
                  + manifest)
        if names:
            detail += f"; its expected surface includes {sorted(names)}"
        # The submodule note used to be appended here, to every single
        # unresolved import. It now belongs to false_absence_hints() and is
        # printed once for the run: the condition is a property of the scan,
        # and repeating it per finding taught the reader to skip it.
        submodule = providers.get("__uninitialised_submodule__")
        if submodule:
            detail += (f"; note: git submodule `{submodule}` is declared but not initialised, "
                       "run `git submodule update --init` and rescan before treating this as lost")
        yield NegativeEvidence(
            kind=EvidenceKind.UNRESOLVED_IMPORT, detail=detail,
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


# Identifier-shaped debris. Applied only to files that do not parse: on a
# working module the AST is authoritative and regex would be a downgrade.
_DEBRIS_CLASS = re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]*)")
_DEBRIS_DEF = re.compile(r"\bdef\s+([a-z_][A-Za-z0-9_]*)")


_DEFINING_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                   ast.Assign, ast.Import, ast.ImportFrom)


# WHAT A FLATTENED FILE IS
#
# Python source whose NEWLINES ARE GONE. The bytes survive, the line breaks
# do not, and with them go indentation and every statement boundary the
# language depends on.
#
#     VANGUARD/vanguard-behavioral-simulation-flattened.py
#     9,877 bytes.  0 newlines.  One line, 9,877 characters wide.
#
# It happens when code is copied out of a surface that renders rather than
# stores it -- a chat transcript, a rendered notebook, a PDF, a terminal
# that soft-wrapped. Nothing was deleted; the structure was.
#
# Two ways it presents, and the second is why _is_destroyed checks more
# than SyntaxError:
#
#   LOUD    the flattened text is not valid Python, so it raises on parse.
#   SILENT  the file's single line begins with `#`, so Python reads all
#           11,700 bytes of it as one comment. It imports cleanly, raises
#           nothing, and defines zero names. TOUCHSTONE keeps one of these
#           as a specimen precisely because a tool that only catches
#           SyntaxError walks straight past it.
#
# WHY IT IS RECOVERABLE AT ALL
#
# Whitespace carried the structure; TOKEN ORDER carried the interface, and
# token order is untouched. `class X:` is still followed by the `def`s that
# were indented beneath it, each with its parameter list and return
# annotation intact. debris_structure() reads that sequence straight off the
# wreckage. What is unrecoverable is the bodies, the nesting, and which
# headers were live code rather than examples inside a docstring -- and no
# better parser recovers them, because the information is not in the file.


def _is_destroyed(text: str) -> bool:
    """Does not parse, or parses to a module that defines nothing.

    The second case is TOUCHSTONE's canonical silent-pass specimen: a
    flattened file whose single line begins with `#`, so Python reads all
    11,700 bytes as one comment. It imports cleanly and defines zero names.
    An empty file is empty, not destroyed."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return True
    if not text.strip():
        return False
    return not any(isinstance(n, _DEFINING_NODES) for n in ast.walk(tree))


def detect_destroyed_residue(path: Path, source: str | None = None
                             ) -> Iterator[NegativeEvidence]:
    """Identifier debris surviving in a file that no longer parses.

    The other half of the black-hole method. You cannot see inside the object,
    but the debris field is measurable, and for a flattened paste the debris is
    every identifier-shaped token still sitting in the bytes.

    This is deliberately NOT run on files that parse. There the AST is
    authoritative and regex over source text would be strictly worse -- it
    cannot tell a class definition from the same word in a docstring. Here
    there is no AST to have, so imprecise evidence beats none.

    What the residue supports and does not:

      supports      what names existed, roughly how many, what vocabulary
      DOES NOT      structure, nesting, call graph, which names were public,
                    which were live code as opposed to examples in a docstring

    That last exclusion matters. A flattened chat paste routinely contains
    the assistant's illustrative snippets alongside the real module, and
    nothing in the bytes distinguishes them.
    """
    text = source if source is not None else path.read_text(errors="replace")
    if not _is_destroyed(text):
        return

    classes = sorted(set(_DEBRIS_CLASS.findall(text)))
    functions = sorted(set(_DEBRIS_DEF.findall(text)))
    if not classes and not functions:
        return

    yield NegativeEvidence(
        kind=EvidenceKind.DESTROYED_RESIDUE,
        detail=(
            f"unparseable file leaves identifier debris: {len(classes)} "
            f"class-shaped and {len(functions)} def-shaped tokens. "
            f"classes {classes[:12]}"
            + (" ..." if len(classes) > 12 else "")
            + ". Names only here; token order still holds the interface, "
              "see the debris_structure evidence. Which tokens were live "
              "code rather than docstring examples is destroyed."
        ),
        file=str(path),
        observed=f"{len(text)} bytes, {text.count(chr(10))} newlines",
    )


_DEBRIS_HEADER = re.compile(
    r"\bclass\s+([A-Z]\w*)\s*(\([^)]*\))?\s*:"
    r"|\bdef\s+([a-z_]\w*)\s*\(([^)]*)\)\s*(->\s*[^:]+?)?\s*:"
)
_PAIR_SUFFIXES = (("_source.py", "_adapter.py"), ("-flattened.py", ".py"))


def _companion(path: Path) -> Path | None:
    """The parsing counterpart of a destroyed file, by naming convention:
    `x_source.py` beside `x_adapter.py`, `x-flattened.py` beside `x.py`."""
    for old, new in _PAIR_SUFFIXES:
        if path.name.endswith(old):
            candidate = path.with_name(path.name[: -len(old)] + new)
            if candidate.is_file() and candidate != path:
                return candidate
    return None


def debris_structure(text: str) -> list[tuple[str, str, str, str]]:
    """(owner, name, params, returns) for every class and def header in token
    order. A def whose first parameter is `self` or `cls` is attributed to the
    most recent class header; anything else is module level. Newlines are
    gone but order is not, and that is enough to read the interface back."""
    out: list[tuple[str, str, str, str]] = []
    current = ""
    for m in _DEBRIS_HEADER.finditer(text):
        if m.group(1):
            current = m.group(1)
            out.append(("", current, (m.group(2) or "").strip("()"), ""))
            continue
        params = " ".join((m.group(4) or "").split())
        first = params.split(",", 1)[0].split(":", 1)[0].strip()
        owner = current if first in ("self", "cls") and current else ""
        out.append((owner, m.group(3), params, " ".join((m.group(5) or "").split())))
    return out


def detect_debris_structure(path: Path, source: str | None = None
                            ) -> Iterator[NegativeEvidence]:
    """The interface of a flattened file, read from the order of its debris.

    Only for files that do not parse: on a parsing file the AST is
    authoritative. What survives flattening is every token in its original
    order, so `class A:` followed by three `def`s taking `self` is class A
    with three methods, each with the parameter list and return annotation
    it was written with. Bodies are not recovered and never will be here;
    a def inside a docstring example is indistinguishable from a live one;
    and a method that followed its class in the text is attributed to it,
    which is right for ordinary source and wrong for a paste that
    interleaved two files.
    """
    text = source if source is not None else path.read_text(errors="replace")
    if not _is_destroyed(text):
        return
    structure = debris_structure(text)
    if not structure:
        return
    lines = []
    for owner, name, params, returns in structure:
        if not owner and not params and not returns and name[:1].isupper():
            lines.append(f"    class {name}")
            continue
        qual = f"{owner}.{name}" if owner else name
        lines.append(f"    {qual}({params}){' ' + returns if returns else ''}")
    classes = [n for o, n, p, r in structure if not o and n[:1].isupper() and not p and not r]
    methods = [x for x in structure if x[0]]
    functions = [x for x in structure if not x[0] and not x[1][:1].isupper()]
    detail = (
        f"ordered debris recovers the interface: {len(classes)} class(es), "
        f"{len(methods)} method(s), {len(functions)} module-level function(s), "
        "each with the parameter list and return annotation it was written with:\n"
        + "\n".join(lines)
    )
    companion = _companion(path)
    if companion is not None:
        try:
            tree = ast.parse(companion.read_text(errors="replace"))
            their = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
            shared = sorted(set(classes) & their)
            detail += (
                f"\n    companion `{companion.name}` parses and shares {len(shared)} of "
                f"{len(classes)} class name(s)"
                + (f" ({shared})" if shared else "")
                + (": a renamed rewrite, so this file is an ancestor and nothing reaches "
                   "for it, not a lost dependency" if not shared else
                   ": the same names survive there, so compare before treating this as lost")
            )
        except (SyntaxError, OSError):
            pass
    yield NegativeEvidence(
        kind=EvidenceKind.DEBRIS_STRUCTURE, detail=detail, file=str(path),
        observed=f"{len(structure)} header tokens in order",
    )


_DEBRIS_CTOR = re.compile(r"=\s*([A-Z]\w+)\(\)")
# An annotation follows a parameter name. `{"ok": True,` follows a quote and
# is a dict literal, which leaked `True` and `False` into OBSERVE's voids.
_DEBRIS_HINT = re.compile(r"\w\s*:\s*([A-Z]\w+)[,)]")
_DEBRIS_LITERALS = {"True", "False", "None"}
_DEBRIS_BIND = re.compile(r"self\.(\w+)\s*=\s*([A-Z]\w+)\(\)")
_DEBRIS_CALL = re.compile(r"self\.(\w+)\.(\w+)\(")

# Imports surviving in the debris. A name the file imports is resolved by that
# import and is not missing -- if the module itself is gone, that is a
# MISSING_MODULE void found by detect_missing_imports, reported once against
# the module rather than once per name it supplied.
_DEBRIS_IMPORT_HEAD = re.compile(r"\bfrom\s+[\w.]+\s+import\s*")
_DEBRIS_IMPORT_PLAIN = re.compile(r"\bimport\s+([\w.]+)(?:\s+as\s+(\w+))?")
_IMPORT_TOKEN = re.compile(r"[A-Za-z_]\w*")

# Tokens that end an import list once the line breaks are gone. In flattened
# text `from a import b from c import d` is one run of characters, so a
# non-greedy word match would otherwise swallow the next statement whole.
_IMPORT_STOP = frozenset({
    "from", "import", "class", "def", "return", "if", "for", "while", "try",
    "with", "raise", "assert", "logger", "async", "await", "del", "global",
})


def _debris_imported_names(text: str) -> set[str]:
    """Names this file brings in by import, recovered from unparseable text."""
    names: set[str] = set()

    # Scan forward from each `from X import`, taking names until the next
    # statement begins. A single greedy pattern cannot do this: with the line
    # breaks gone, `from a import b from c import d` is one uninterrupted run
    # of word characters and separators, so a greedy match consumes the rest
    # of the file and every import after the first is lost.
    for head in _DEBRIS_IMPORT_HEAD.finditer(text):
        for token in _IMPORT_TOKEN.finditer(text, head.end()):
            word = token.group(0)
            if word == "as":
                continue          # `x as y` -- both names are bound locally
            if word in _IMPORT_STOP:
                break             # next statement; this import list is over
            names.add(word)
            # Stop at the first gap that is not list punctuation, so a bare
            # `from a import b class C` ends after `b`.
            between = text[token.end():token.end() + 1]
            if between and between not in ",) \t\n(":
                break

    for module, alias in _DEBRIS_IMPORT_PLAIN.findall(text):
        names.add(alias or module.split(".")[0])

    return {n for n in names if n.isidentifier()}


def detect_dangling_in_debris(path: Path, source: str | None = None
                              ) -> Iterator[NegativeEvidence]:
    """Dangling references in a file that does not parse.

    `detect_dangling_names` needs an AST and returns nothing when there is
    none -- which silently excludes exactly the files most likely to be
    surrounded by voids. Found by hand on ARCHIVE's PULSEARMPipeline.py: a
    2.7 KB skeleton, indentation flattened to a uniform one space so the
    nesting depth is gone and no mechanical repair is possible, which
    instantiates seven types it never defines and calls methods on them. All
    of that is legible; none of it was reachable through the AST path.

    Regex, so weaker than the AST detector and correspondingly narrow: only
    `x = Name()` constructor calls, `: Name` annotations, and
    `self.field.method(` calls where the field's constructor is visible. A
    name mentioned in prose or a docstring is not evidence and is not
    matched.

    Runs only on unparseable files. Where an AST exists it is authoritative
    and this would be strictly worse.
    """
    text = source if source is not None else path.read_text(errors="replace")
    try:
        ast.parse(text)
        return
    except SyntaxError:
        pass

    # Defined here, or imported here. Counting only class definitions reported
    # every imported type as missing code: the first real specimen this ran on
    # yielded `Any`, whose `from typing import (...)` was sitting in the same
    # debris a few hundred bytes away.
    defined = set(re.findall(r"\bclass\s+(\w+)", text)) | _debris_imported_names(text)
    bindings = dict(_DEBRIS_BIND.findall(text))          # field -> Type
    methods: dict[str, set[str]] = {}
    for field, method in _DEBRIS_CALL.findall(text):
        methods.setdefault(field, set()).add(method)

    referenced = (set(_DEBRIS_CTOR.findall(text)) | set(_DEBRIS_HINT.findall(text))) - _DEBRIS_LITERALS
    for name in sorted(referenced - defined):
        fields = [f for f, cls in bindings.items() if cls == name]
        required = sorted({m for f in fields for m in methods.get(f, ())})
        if fields:
            role = f"constructed and bound to self.{fields[0]}"
        else:
            role = "used as a type annotation"
        detail = f"`{name}` is {role} but never defined in this file."
        if required:
            detail += f" Callers require attributes: read {required}"
        yield NegativeEvidence(
            kind=EvidenceKind.DANGLING_REFERENCE,
            detail=detail,
            file=str(path),
            observed="recovered from debris; this file does not parse",
        )


def detect_orphaned_tests(test_paths: Iterable[Path],  # ghost_buster: name-disagreement -- `test_paths` is `tests` at every call site
                          search_roots: Sequence[Path],
                          providers: dict[str, str] | None = None
                          ) -> Iterator[NegativeEvidence]:
    """Tests exercising something that is not there.

    Unusually strong evidence, because a test encodes both the expected
    interface and the expected behaviour -- it says not only what the missing
    thing was called but what it was supposed to do.
    """
    available = _available_modules(search_roots)
    for root in search_roots:
        if not root.is_dir():
            continue
        for candidate in _source_files(root):
            try:
                available.update(_bound_names(
                    ast.parse(candidate.read_text(errors="replace"))))
            except SyntaxError:
                continue

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
            except ImportError:
                # Not importable here: the evidence below is about that.
                importable = False
            except Exception as exc:  # noqa: BLE001
                # It exists and it breaks on import. That is a broken
                # module, not a missing one, and calling it "does not
                # exist" would send the reader looking for a ghost. Found
                # by ghost_buster's swallowed_exception on this very file:
                # the old handler was `pass` and said nothing.
                yield NegativeEvidence(
                    kind=EvidenceKind.WIRING,
                    detail=(f"module `{module}` exists but fails to import: "
                            f"{type(exc).__name__}: {exc}"),
                    file=str(path), line=node.lineno,
                )
                continue
            else:
                importable = True
            if importable:
                continue
            provider = (providers or {}).get(module) or (providers or {}).get(_normalise_dist(module))
            if provider:
                # Measured 2026-09-08: with every sibling checkout supplied,
                # the spine still reported `ccc`, `gems` and
                # `governance_gateway` as voids, because only the import
                # detector consulted the providers and the test detector
                # reported the same modules a second time.
                yield NegativeEvidence(
                    kind=EvidenceKind.WIRING,
                    detail=f"module `{module}` is not in this tree; provided by {provider}",
                    file=str(path), line=node.lineno,
                )
                continue
            wanted = [a.name for a in node.names] if isinstance(node, ast.ImportFrom) else []
            yield NegativeEvidence(
                kind=EvidenceKind.ORPHANED_TEST,
                detail=(f"test imports `{module}`, which does not exist; the "
                        f"test encodes the expected interface"
                        + (f" {sorted(wanted)}" if wanted else "")),
                file=str(path), line=node.lineno,
            )


def scan(root: Path, siblings: Sequence[Path] = ()) -> list[NegativeEvidence]:
    """Every mechanical negative-space signal under `root`.

    `siblings` are other checkouts that may provide what this tree imports;
    they classify, they do not silence. A module a sibling provides comes
    back as WIRING evidence rather than disappearing, so the reader sees the
    dependency and does not mistake it for a loss."""
    root = Path(root)
    providers = resolve_providers(root, siblings)
    sources = _source_files(root)
    tests = [p for p in sources
             if p.name.startswith("test_") or "test" in p.parent.name.lower()]

    evidence: list[NegativeEvidence] = []
    for path in sources:
        text = path.read_text(errors="replace")
        evidence.extend(detect_unparseable(path, text))
        evidence.extend(detect_destroyed_residue(path, text))
        evidence.extend(detect_debris_structure(path, text))
        evidence.extend(detect_dangling_names(path, text))
        evidence.extend(detect_dangling_in_debris(path, text))
        evidence.extend(detect_missing_imports(path, [root], text, providers))
    evidence.extend(detect_orphaned_tests(tests, [root], providers))  # ghost_buster: name-disagreement -- `tests` is `test_paths` in the signature
    from .rename import detect_rename_candidates
    evidence.extend(detect_rename_candidates(sources, evidence))
    return evidence
