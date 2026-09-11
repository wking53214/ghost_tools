"""A door somebody opens onto nothing.

THE DISTINCTION THIS TURNS ON

`dead_code` next door answers the opposite question: it finds a definition
nobody references. This one finds the definition everybody references whose
body does nothing, and it has to separate that from the thing it most
resembles and is not:

  A SEAM is inert on purpose. An abstract method, a Protocol, a plugin
  interface: it has no body because the body arrives from somewhere else,
  and being empty is the whole design. Reporting it is noise, and reporting
  every one of them is how a report teaches its reader to skim.

  A DEAD END is inert because nothing ever arrived. Live code calls it, the
  call returns, and nothing happened.

Both are empty. The difference is not in the body, it is in whether anything
in the world is arranged to fill it -- which is decidable, and is the same
rule the cassette check uses in naming.py: a seam DECLARES itself.

    declared by inheritance    ABC, ABCMeta or Protocol base
    declared by decorator      @abstractmethod, @abstractproperty
    declared by use            a subclass, anywhere in the scan, that
                               actually overrides it with a real body

Anything with none of those, called by non-test code, is reported.

WHAT IT CANNOT SAY

"And never will be." Nothing static proves never. What the evidence
supports is narrower and is what the finding says: nothing in the scanned
set provides a body, and nothing declares an intent to. A subclass in a
repository this scan was not pointed at would falsify it, which is exactly
what blackhole_extrapolator's --sibling exists to handle. Scan the siblings
if the answer matters.

A SECOND THING IT CANNOT SAY

Which object a call landed on. This is an AST-only tool with no type
resolution -- the same disclosed limit `dead_code` carries -- so "something
calls `execute`" means the NAME is called somewhere, not that the receiver
was necessarily this class. That direction is safe: it can only make the
detector speak up about a hollow body, never stay quiet about one, and the
finding says what it saw rather than what it inferred.

WHY SILENCE IS WORSE THAN A CRASH

A `raise NotImplementedError` reached at runtime is loud: it stops, it names
itself, and somebody fixes it that afternoon. A `pass` reached at runtime is
silent: the caller believes the work happened, and the report says the check
passed. That is the difference between "the check passed" and "the thing
works", so the silent shapes are MAJOR and the loud one is MINOR.

MEASURED BEFORE IT WAS BUILT

Across 24 live repositories and 1,562 files on 2026-09-10: 162 callables
whose body does nothing, 31 with no override in their own repository, 11 of
those called by live code. Of the 11, ten were deliberate -- Null Object
sinks, no-op tracing spans, test doubles, and a stateless `__init__` -- and
one was real: `UniversalAdapter.execute` raising NotImplementedError with
nothing subclassing it and live code calling `.execute()`. The exclusions
below are that measurement; each one was a false positive first.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Set

from . import corpus
from .naming import is_test_path
from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "dead_end_call"

PASS = "pass"
ELLIPSIS = "..."
DOCSTRING_ONLY = "docstring only"
RETURNS_NOTHING = "return None"
RAISES = "raise NotImplementedError"

# The loud one. It stops and names itself; the others let the caller believe
# the work happened.
LOUD = frozenset({RAISES})

_ABSTRACT_BASES = frozenset({"ABC", "ABCMeta", "Protocol"})
_ABSTRACT_DECORATORS = frozenset({"abstractmethod", "abstractproperty"})

# The Null Object pattern and the test double: an empty body that IS the
# implementation.
_NO_OP_WORDS = ("null", "noop", "no_op", "fake", "stub", "dummy", "mock")


def is_no_op_name(name: str) -> bool:
    """Whether a name announces itself as a deliberate do-nothing.

    The prefix has to end where a name part ends, so `nullify_cache` is not a
    Null object and `stubborn_retry` is not a stub. Written out rather than
    matched by regex because the regex that did this first was
    `(?:null|noop|...)(?=[A-Z_0-9]|$)` with re.IGNORECASE, and IGNORECASE
    makes `[A-Z]` match lowercase too -- so the boundary it was there to
    enforce did not exist and every one of these words matched as a bare
    prefix.
    """
    bare = name.lstrip("_")
    lowered = bare.lower()
    for word in _NO_OP_WORDS:
        if lowered.startswith(word):
            rest = bare[len(word):]
            if not rest or rest[0].isupper() or rest[0] == "_" or rest[0].isdigit():
                return True
    return False

# An empty `__init__` is a class with no state to set up, which is ordinary
# and was a measured false positive (ATS's AuditReportValidator). The other
# two are protocols where doing nothing is the correct implementation.
_EMPTY_IS_NORMAL = frozenset({"__init__", "__enter__", "__exit__", "__del__"})


def body_does_nothing(node: ast.AST) -> str | None:
    """The shape of an empty body, or None if the body does something.

    A docstring does not count as doing something, which is the point: a
    callable documented at length and implemented not at all is the most
    convincing dead end there is.
    """
    body = list(getattr(node, "body", []))
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
        if not body:
            return DOCSTRING_ONLY
    if not body or len(body) > 1:
        return None
    only = body[0]
    if isinstance(only, ast.Pass):
        return PASS
    if (isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant)
            and only.value.value is Ellipsis):
        return ELLIPSIS
    if isinstance(only, ast.Return) and (
            only.value is None
            or (isinstance(only.value, ast.Constant) and only.value.value is None)):
        return RETURNS_NOTHING
    if isinstance(only, ast.Raise):
        raised = only.exc
        name = (getattr(raised, "id", None)
                or getattr(getattr(raised, "func", None), "id", None))
        if name == "NotImplementedError":
            return RAISES
    return None


def _decorators(node: ast.AST) -> Set[str]:
    return {getattr(d, "id", getattr(d, "attr", ""))
            for d in getattr(node, "decorator_list", [])}


def _base_names(node: ast.ClassDef) -> List[str]:
    return [getattr(b, "id", getattr(b, "attr", "")) for b in node.bases]


@dataclass(frozen=True)
class Hollow:
    """One callable whose body does nothing, and where it lives."""

    path: Path
    owner: str | None
    name: str
    shape: str
    line: int

    @property
    def qualified(self) -> str:
        return f"{self.owner}.{self.name}" if self.owner else self.name

    @property
    def is_loud(self) -> bool:
        return self.shape in LOUD


class _Index:
    """Everything the seam test needs, read once from the scanned set."""

    def __init__(self, files: Sequence[Path]) -> None:
        self.bases: Dict[str, List[str]] = {}
        self.real_methods: Dict[str, Set[str]] = defaultdict(set)
        self.abstract_classes: Set[str] = set()
        self.abstract_methods: Set[str] = set()
        self.real_functions: Set[str] = set()
        self.called: Set[str] = set()
        self.hollows: List[Hollow] = []

        for path in (Path(f) for f in files):
            tree = self._parse(path)
            if tree is None:
                continue
            test = is_test_path(path)
            if not test:
                self._note_calls(tree)
            self._note_classes(path, tree, test)
            self._note_functions(path, tree, test)

    @staticmethod
    def _parse(path: Path) -> ast.Module | None:
        return corpus.parse(path)

    def _note_calls(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name:
                    self.called.add(name)

    def _note_classes(self, path: Path, tree: ast.Module, test: bool) -> None:
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            bases = _base_names(cls)
            self.bases[cls.name] = bases
            if _ABSTRACT_BASES & set(bases):
                self.abstract_classes.add(cls.name)
            for node in cls.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _decorators(node) & _ABSTRACT_DECORATORS:
                    self.abstract_methods.add(f"{cls.name}.{node.name}")
                shape = body_does_nothing(node)
                if shape is None:
                    # A real body anywhere under this class name is what makes
                    # an empty one above it a seam rather than a dead end.
                    self.real_methods[cls.name].add(node.name)
                elif not test:
                    self.hollows.append(Hollow(path, cls.name, node.name,
                                               shape, node.lineno))

    def _note_functions(self, path: Path, tree: ast.Module, test: bool) -> None:
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            shape = body_does_nothing(node)
            if shape is None:
                self.real_functions.add(node.name)
            elif not test:
                self.hollows.append(Hollow(path, None, node.name, shape, node.lineno))

    def ancestry(self, cls: str, seen: Set[str] | None = None) -> Set[str]:
        seen = seen if seen is not None else set()
        for base in self.bases.get(cls, []):
            if base and base not in seen:
                seen.add(base)
                self.ancestry(base, seen)
        return seen

    def subclasses(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = defaultdict(list)
        for cls in self.bases:
            for ancestor in self.ancestry(cls):
                out[ancestor].append(cls)
        return out


def _declared_seam(index: _Index, subclasses: Dict[str, List[str]],
                   hollow: Hollow) -> str | None:
    """Why this empty body is empty ON PURPOSE, or None if nothing says so."""
    if hollow.owner is None:
        if hollow.name in index.real_functions:
            return "another definition of the same function has a real body"
        return None
    if hollow.owner in index.abstract_classes:
        return f"{hollow.owner} declares an abstract or Protocol base"
    if hollow.qualified in index.abstract_methods:
        return "declared @abstractmethod"
    for sub in subclasses.get(hollow.owner, []):
        if hollow.name in index.real_methods.get(sub, ()):
            return f"{sub} overrides it with a real body"
    return None


def _deliberate_no_op(hollow: Hollow) -> bool:
    if hollow.name in _EMPTY_IS_NORMAL:
        return True
    return is_no_op_name(hollow.owner or hollow.name) or is_no_op_name(hollow.name)


def find_dead_ends(files: Sequence[Path]) -> List[Hollow]:
    """Every empty body that live code calls and nothing is arranged to fill."""
    index = _Index(files)
    subclasses = index.subclasses()
    return [h for h in index.hollows
            if h.name in index.called
            and not _deliberate_no_op(h)
            and _declared_seam(index, subclasses, h) is None]


def detect_dead_end_calls(files: Sequence[Path]) -> List[Finding]:
    findings: List[Finding] = []
    for hollow in sorted(find_dead_ends(files), key=lambda h: (str(h.path), h.line)):
        loud = hollow.is_loud
        findings.append(Finding(
            detector=DETECTOR,
            category=Category.DEAD_CODE,
            layer=Layer.MECHANICAL,
            severity=Severity.MINOR if loud else Severity.MAJOR,
            status=Status.CONFIRMED,
            summary=(f"`{hollow.qualified}` is called and its body is "
                     f"`{hollow.shape}`"),
            detail=(
                f"{hollow.path.name}:{hollow.line} defines `{hollow.qualified}` "
                f"with a body of `{hollow.shape}`, something in the scanned set "
                "calls it, and nothing in the scanned set is arranged to fill "
                "it: no abstract or Protocol base, no @abstractmethod, and no "
                "subclass overriding it with a real body.\n"
                + ("A raised NotImplementedError is the loud shape. It stops "
                   "and names itself, so it is MINOR: a caller finds out.\n"
                   if loud else
                   "This is the silent shape, which is why it is MAJOR. The "
                   "call returns, the caller believes the work happened, and "
                   "nothing says otherwise.\n")
                + "This says nothing about `never`. It says nothing HERE "
                  "provides a body. An implementation in a repository this "
                  "scan was not pointed at would settle it; scan the siblings "
                  "if the answer matters."
            ),
            evidence=Evidence(file=str(hollow.path), line_start=hollow.line),
            attributes={"shape": hollow.shape, "qualified": hollow.qualified},
        ))
    return findings
