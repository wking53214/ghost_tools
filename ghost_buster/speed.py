"""Pitstops: work the code does more often than it needs to.

TWO WAYS TO FIND THEM, AND WHY BOTH

The biggest one this toolkit ever had could not be found by reading the
code. Eighteen detectors each called `ast.parse` on every file, and no
single function was wrong -- each parsed once. Only a RUN showed 9.5 parses
per file and 52% of wall clock inside the parser. That is `profile()` below:
instrument a run, count repeated identical work, rank it by what it cost.

The small ones can be read off the tree and cost nothing to find. A
membership test against a list inside a loop is O(n*m) where a set would be
O(n). A call inside a loop whose arguments never mention the loop variable
computes the same thing every iteration. Those are the static detectors.

They are reported at different confidence, because they are different
kinds of evidence:

  measured redundancy     CONFIRMED. It happened, it was counted, and the
                          finding says what it cost as a share of the run.

  static pitstop          CONFIRMED that the shape is there; MINOR, because
                          a loop over four items with a list lookup is not a
                          problem and the tree cannot tell four from four
                          million. The finding says so.

WHAT IT WILL NOT DO

Hoist a loop-invariant call for you. `load()` inside a loop may be
invariant in its arguments and still be there on purpose -- it may have a
side effect, it may be reading something that changes. Moving it is a
judgement about the world the tree does not contain. Reported, never
rewritten.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from . import corpus
from .naming import is_test_path
from .schema import Category, Evidence, Finding, Layer, Severity, Status

LIST_IN_LOOP = "list_membership_in_loop"
INVARIANT_CALL = "loop_invariant_call"

# Constant-time builtins. `len(names)` inside a loop is invariant and costs
# nothing, and a report that says "hoist this" forty times about `len` is a
# report nobody reads twice. Measured against ghost_tools after the
# variance fix: 67 invariant calls, of which 55 were str/len/type. The
# ones worth a human's attention are the user-defined functions and the
# builtins that walk a collection -- sorted, min, max, sum, set, list.
_CHEAP = frozenset({"str", "len", "type", "int", "float", "bool", "repr", "id",
                    "hash", "abs", "isinstance", "issubclass", "getattr",
                    "hasattr", "callable", "round", "chr", "ord", "bytes"})

_COMPS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_LOOPS = (ast.For, ast.While) + _COMPS


def _names(node: ast.AST) -> Set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _variant_in(loop: ast.AST) -> Set[str]:
    """Every name that can change from one iteration to the next.

    Not just the loop target. The first version checked only the target,
    and against ghost_tools reported 295 invariant calls of which the
    first was `_identifiers(tree)` inside `for path in paths: tree =
    _parse(path)` -- `tree` is bound in the body, so it varies. Anything
    STORED anywhere inside the loop varies, and so does every
    comprehension target."""
    out: Set[str] = set()
    for n in ast.walk(loop):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (ast.For, ast.comprehension)):
            out |= _names(n.target)
    return out


def _iterated(loop: ast.AST) -> List[ast.AST]:
    """The statements or expressions evaluated once per iteration. A
    comprehension has no `.body`; its per-iteration work is the element and
    the filters, and the FIRST iterable is evaluated once, not per pass."""
    if isinstance(loop, (ast.For, ast.While)):
        return list(loop.body)
    parts: List[ast.AST] = [loop.key, loop.value] if isinstance(loop, ast.DictComp) else [loop.elt]
    for gen in loop.generators:
        parts.extend(gen.ifs)
    for gen in loop.generators[1:]:
        parts.append(gen.iter)
    return parts


@dataclass(frozen=True)
class Pitstop:
    path: Path
    line: int
    kind: str
    what: str


# A membership test against a constant this small is not a scan worth
# reporting: `x in ("self", "cls")` costs what a set lookup costs. The
# first serum reported three of these (a two-tuple and two three-tuples)
# and hoisting them would have changed nothing measurable.
_SMALL_LITERAL = 8


def _list_literals_bound(tree: ast.Module) -> Dict[str, int]:
    """Names bound to a list or tuple literal at module level, with the
    literal's length. The one case where the tree KNOWS the container is a
    list and not something a set would break, and knows how long it is."""
    out: Dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple)):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = len(node.value.elts)
    return out


def _may_change(loop_parts: List[ast.AST], call: ast.Call) -> bool:
    """Could something else in this loop change what `call`'s arguments
    refer to between iterations? The tree cannot see side effects, so it
    looks for the shapes that usually carry them, and abstains on any:

      - another call in the loop that receives one of the same names as a
        bare argument (`remedy(root, files)` before `rescan(files)`: the
        remedy edited what `files` names);
      - a method called on one of those names (`scratch.restore(original)`
        before `_run_test(scratch, ...)`);
      - an attribute or subscript of one of those names assigned to.

    Constant-time builtins (`str(path)`) and constructor-looking callees
    (`Finding(file=...)`) do not count: they read, they do not change.
    The first serum ranked four invariant calls that were nothing of the
    kind, all of them one of these three shapes."""
    args = {a.id for a in call.args if isinstance(a, ast.Name)}
    if not args:
        return False
    for part in loop_parts:
        for node in ast.walk(part):
            if node is call:
                continue
            if isinstance(node, ast.Call):
                callee = node.func
                if (isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name)
                        and callee.value.id in args):
                    return True
                if (isinstance(callee, ast.Name) and callee.id not in _CHEAP
                        and not callee.id[:1].isupper()):
                    passed = {a.id for a in node.args if isinstance(a, ast.Name)}
                    passed |= {k.value.id for k in node.keywords if isinstance(k.value, ast.Name)}
                    if passed & args:
                        return True
            elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, ast.Store):
                base = node.value
                while isinstance(base, (ast.Attribute, ast.Subscript)):
                    base = base.value
                if isinstance(base, ast.Name) and base.id in args:
                    return True
    return False


def _memoised(loop_parts: List[ast.AST]) -> Set[int]:
    """Calls that run once per loop, not once per pass: the value of
    `x = f(...)` inside `if x is None:` or `if not x:`. A memo is the
    hoist already done, lazily; reporting it asks for what is there."""
    out: Set[int] = set()
    for part in loop_parts:
        for node in ast.walk(part):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            guarded = None
            if (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)
                    and isinstance(test.left, ast.Name) and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value is None):
                guarded = test.left.id
            elif isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name):
                guarded = test.operand.id
            if guarded is None:
                continue
            for stmt in node.body:
                if (isinstance(stmt, ast.Assign)
                        and any(isinstance(tg, ast.Name) and tg.id == guarded for tg in stmt.targets)):
                    # every call in the memoised value, nested ones included:
                    # `declares = bool(_declared_dependencies(root))` runs once
                    out |= {id(c) for c in ast.walk(stmt.value) if isinstance(c, ast.Call)}
    return out


def _filled_each_pass(loop_parts: List[ast.AST]) -> Set[int]:
    """Calls whose result is a fresh accumulator: `x = f(...)` inside the
    loop, with `x` then filled in the same loop -- an item stored under it
    (`x[k] = v`, `x[k].add(v)`, `x[k] += 1`), a method called on it, or an
    augmented assignment into it. Hoisting the call would make every pass
    share one container, which is a bug, not a speedup. The third serum
    reported two `defaultdict(set)` constructions this way; a
    `defaultdict` whose argument never changes is still built for its
    contents, and the contents change every pass."""
    out: Set[int] = set()
    for part in loop_parts:
        for node in ast.walk(part):
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                continue
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names and _filled(loop_parts, names):
                out.add(id(node.value))
    return out


def _filled(loop_parts: List[ast.AST], names: Set[str]) -> bool:
    for part in loop_parts:
        for node in ast.walk(part):
            if isinstance(node, ast.AugAssign):
                target = node.target
            elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, ast.Store):
                target = node
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                target = node.func.value
            else:
                continue
            while isinstance(target, (ast.Attribute, ast.Subscript)):
                target = target.value
            if isinstance(target, ast.Name) and target.id in names:
                return True
    return False


def _add(out: List[Pitstop], seen: Set[Pitstop], stop: Pitstop) -> None:
    if stop not in seen:
        seen.add(stop)
        out.append(stop)


def find_pitstops(files: Sequence[Path]) -> List[Pitstop]:
    """Every pitstop, each once.

    A call inside an inner loop sits inside the outer loop's body too, so a
    walk from each loop finds it twice; the first run against ghost_tools
    reported mechanical.py:551 three times. A set keys on (path, line, kind,
    what) so a nested loop reports what it contains once."""
    seen: Set[Pitstop] = set()
    out: List[Pitstop] = []
    for path in (Path(f) for f in files):
        if is_test_path(path):
            continue
        tree = corpus.parse(path)
        if tree is None:
            continue
        lists = _list_literals_bound(tree)
        for loop in ast.walk(tree):
            if not isinstance(loop, _LOOPS):
                continue
            variant = _variant_in(loop)
            parts = _iterated(loop)
            memo = _memoised(parts)
            filled = _filled_each_pass(parts)
            for part in parts:
                for node in ast.walk(part):
                    # x in SOME_LIST, where SOME_LIST is a module-level list literal
                    # long enough for the scan to matter
                    if (isinstance(node, ast.Compare) and len(node.ops) == 1
                            and isinstance(node.ops[0], (ast.In, ast.NotIn))
                            and isinstance(node.comparators[0], ast.Name)
                            and lists.get(node.comparators[0].id, 0) > _SMALL_LITERAL):
                        _add(out, seen, Pitstop(path, node.lineno, LIST_IN_LOOP,
                                                f"`in {node.comparators[0].id}`, a module-level list"))
                    # a call whose arguments cannot change between iterations
                    if (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name)
                            and node.func.id not in _CHEAP
                            and node.args and not node.keywords
                            and all(isinstance(a, (ast.Name, ast.Constant)) for a in node.args)
                            and not (_names(node) & variant)
                            and id(node) not in memo
                            and id(node) not in filled
                            and not _may_change(parts, node)):
                        _add(out, seen, Pitstop(path, node.lineno, INVARIANT_CALL,
                                                f"`{node.func.id}(...)` with arguments the loop never changes"))
    return out


def detect_pitstops(files: Sequence[Path]) -> List[Finding]:
    findings: List[Finding] = []
    for p in find_pitstops(files):
        findings.append(Finding(
            detector=p.kind,
            category=Category.COMPLEXITY,
            layer=Layer.MECHANICAL,
            severity=Severity.MINOR,
            status=Status.CONFIRMED,
            summary=f"{p.path.name}:{p.line} {p.what} inside a loop",
            detail=(
                f"{p.path}:{p.line}\n"
                + ("Each iteration scans the whole list. A set makes the lookup "
                   "constant-time. MINOR because the tree cannot tell a list of "
                   "four from a list of four million, and only the second is a "
                   "problem.\n" if p.kind == LIST_IN_LOOP else
                   "The arguments never mention the loop variable, so the call "
                   "computes the same thing every iteration -- unless it has a "
                   "side effect or reads something that changes, which the tree "
                   "cannot see. Reported, never hoisted for you.\n")
                + "Measured redundancy across a whole run is a different finding: "
                  "see `ghost-buster --profile`."
            ),
            evidence=Evidence(file=str(p.path), line_start=p.line),
            attributes={"kind": p.kind},
        ))
    return findings


# ------------------------------------------------------------ measured

@dataclass(frozen=True)
class Redundancy:
    """One kind of work, done more than once with the same input."""

    what: str
    distinct: int
    calls: int
    seconds: float

    @property
    def repeated(self) -> int:
        return self.calls - self.distinct

    @property
    def share(self) -> float:
        return 0.0 if self.calls == 0 else self.repeated / self.calls


class Profile:
    """Instrument a run and count repeated identical work.

    Wraps the three things this toolkit does that are expensive and
    repeatable -- parse a file, read a file, run a subprocess -- and records
    each call keyed by its input. Repeated identical inputs are the pitstops
    a static read cannot see.
    """

    def __init__(self) -> None:
        self.calls: Dict[str, Counter] = {"ast.parse": Counter(), "read": Counter(),
                                          "subprocess": Counter()}
        self.seconds: Dict[str, float] = {k: 0.0 for k in self.calls}
        self._saved: list = []

    def __enter__(self) -> "Profile":
        import subprocess
        import time
        prof = self

        real_parse = ast.parse
        def parse(src, *a, **k):
            key = src if isinstance(src, (str, bytes)) else repr(src)
            t = time.perf_counter()
            try:
                return real_parse(src, *a, **k)
            finally:
                prof.seconds["ast.parse"] += time.perf_counter() - t
                prof.calls["ast.parse"][hash(key)] += 1
        ast.parse = parse

        real_read_bytes = Path.read_bytes
        def read_bytes(self_):
            t = time.perf_counter()
            try:
                return real_read_bytes(self_)
            finally:
                prof.seconds["read"] += time.perf_counter() - t
                prof.calls["read"][str(self_)] += 1
        Path.read_bytes = read_bytes

        real_read_text = Path.read_text
        def read_text(self_, *a, **k):
            t = time.perf_counter()
            try:
                return real_read_text(self_, *a, **k)
            finally:
                prof.seconds["read"] += time.perf_counter() - t
                prof.calls["read"][str(self_)] += 1
        Path.read_text = read_text

        real_run = subprocess.run
        def run(args, *a, **k):
            t = time.perf_counter()
            try:
                return real_run(args, *a, **k)
            finally:
                prof.seconds["subprocess"] += time.perf_counter() - t
                prof.calls["subprocess"][repr(args)] += 1
        subprocess.run = run

        self._saved = [(ast, "parse", real_parse), (Path, "read_bytes", real_read_bytes),
                       (Path, "read_text", real_read_text), (subprocess, "run", real_run)]
        return self

    def __exit__(self, *exc) -> None:
        for obj, name, original in self._saved:
            setattr(obj, name, original)

    def redundancies(self) -> List[Redundancy]:
        out = []
        for what, counter in self.calls.items():
            calls = sum(counter.values())
            if calls:
                out.append(Redundancy(what, len(counter), calls, self.seconds[what]))
        return sorted(out, key=lambda r: -r.repeated)

    def render(self, total_seconds: Optional[float] = None) -> str:
        lines = ["measured redundancy (same input, done again):"]
        for r in self.redundancies():
            cost = f"{r.seconds:.2f}s"
            if total_seconds:
                cost += f" ({100 * r.seconds / total_seconds:.0f}% of the run)"
            lines.append(f"  {r.what:12s} {r.calls:6d} calls, {r.distinct:6d} distinct, "
                         f"{r.repeated:6d} repeated  {cost}")
        if all(r.repeated == 0 for r in self.redundancies()):
            lines.append("  nothing was done twice.")
        return "\n".join(lines)
