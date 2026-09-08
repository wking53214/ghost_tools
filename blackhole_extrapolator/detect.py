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
        # a directory of .py files is importable as a namespace package too
        for path in root.rglob("*/"):
            if path.is_dir() and not _SKIP_DIRS & set(path.parts) and \
                    any(path.glob("*.py")):
                available.add(path.name)
    return available


def _normalise_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name.strip().lower())


def _declared_dependencies(root: Path) -> set[str]:
    """Top-level names a project says it depends on, from requirements files
    and pyproject, normalised the way pip does. Best effort: the import name
    and the distribution name usually match, and when they do not the module
    is reported as unresolved rather than guessed."""
    names: set[str] = set()
    for req in list(root.glob("requirements*.txt")) + list(root.glob("requirements/*.txt")):
        for line in req.read_text(errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(("-", "git+", "http")):
                continue
            token = re.split(r"[<>=!~;\[\s]", line, 1)[0]
            if token:
                names.add(_normalise_dist(token))
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
                names.add(_normalise_dist(token))
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
        providers = providers or {}
        provider = providers.get(module) or providers.get(_normalise_dist(module))
        if provider:
            yield NegativeEvidence(
                kind=EvidenceKind.WIRING,
                detail=f"module `{module}` is not in this tree; provided by {provider}",
                file=str(path), line=node.lineno,
            )
            continue
        detail = f"module `{module}` is imported and exists nowhere in the search roots"
        if names:
            detail += f"; its expected surface includes {sorted(names)}"
        submodule = providers.get("__uninitialised_submodule__")
        if submodule:
            detail += (f"; note: git submodule `{submodule}` is declared but not initialised, "
                       "run `git submodule update --init` and rescan before treating this as lost")
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


# Identifier-shaped debris. Applied only to files that do not parse: on a
# working module the AST is authoritative and regex would be a downgrade.
_DEBRIS_CLASS = re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]*)")
_DEBRIS_DEF = re.compile(r"\bdef\s+([a-z_][A-Za-z0-9_]*)")


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
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None

    if tree is not None:
        # Parsing is not proof of survival. TOUCHSTONE's canonical silent-pass
        # specimen is a flattened file whose single line happens to begin with
        # `#`, so Python reads the whole 11,700 bytes as one comment: it
        # imports cleanly, raises nothing, and defines zero names. An earlier
        # version of this detector returned here and missed it -- fooled by
        # exactly the property that specimen exists to catch, on the first
        # real run against the corpus.
        #
        # A module that parses to nothing is destroyed regardless of what the
        # parser says about it.
        defines = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef, ast.Assign, ast.Import,
                                     ast.ImportFrom))
                      for n in ast.walk(tree))
        if defines or not text.strip():
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
            + ". Names only -- structure, nesting and which tokens were live "
              "code rather than docstring examples are all destroyed."
        ),
        file=str(path),
        observed=f"{len(text)} bytes, {text.count(chr(10))} newlines",
    )


_DEBRIS_CTOR = re.compile(r"=\s*([A-Z]\w+)\(\)")
_DEBRIS_HINT = re.compile(r":\s*([A-Z]\w+)[,)]")
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

    referenced = set(_DEBRIS_CTOR.findall(text)) | set(_DEBRIS_HINT.findall(text))
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


def detect_orphaned_tests(test_paths: Iterable[Path],
                          search_roots: Sequence[Path]) -> Iterator[NegativeEvidence]:
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
        evidence.extend(detect_dangling_names(path, text))
        evidence.extend(detect_dangling_in_debris(path, text))
        evidence.extend(detect_missing_imports(path, [root], text, providers))
    evidence.extend(detect_orphaned_tests(tests, [root]))
    return evidence
