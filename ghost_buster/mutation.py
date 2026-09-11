"""mutation.py -- prove a check is vacuous by breaking the thing it claims to check.

WHY THIS EXISTS
---------------
The characteristic defect of an iteratively built, AI-assisted codebase is
a check that passes without doing its job: a test that computes a result and
never asserts on it, asserts only `is not None`, hides its assertion behind
an `if` that is never true, or restates by hand a set the source already
defines. Every one of those is green. Coverage counts it. Nothing notices.

The only honest proof that a test is vacuous is a broken implementation the
test still passes. Deleting an assertion proves nothing (a deleted assertion
cannot fail). So this module does what a careful auditor does by hand:

    1. find candidate tests by shape (the four shapes above)
    2. resolve what project code each candidate actually calls
    3. copy the project to a scratch directory, break that code one way at a
       time, and run only that test
    4. report a finding ONLY when the test survived a mutation, with the
       mutation named, so the finding carries its own proof

A mutant the test kills is not a finding: the test did its job. A candidate
whose test does not pass unmutated cannot be judged and is reported as such
in the run summary, never as a finding.

WHAT IT NEVER DOES
------------------
It never modifies the working tree. Every mutation is applied to a copy under
a temporary directory; sibling directories of the project are symlinked
beside the copy so `../sibling` imports resolve as they do in place. It never
runs the whole suite: one test per mutant, with a timeout. It never claims
more than it ran: `MutationRun` carries the exact mutants tried, the
candidates it could not judge, and why.

Stdlib only, like the rest of the mechanical layer.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import corpus
from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "vacuous_check"

# Directory names never copied into the scratch tree. Same spirit as
# cli._EXCLUDED_DIRS; repeated here rather than imported so this module has
# no dependency on the CLI.
_COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".hg", ".svn", "__pycache__", "site-packages", ".venv", "venv",
    "node_modules", ".tox", ".nox", ".eggs", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".hypothesis", ".ipynb_checkpoints",
)

_UNITTEST_ANY = {name for name in dir(object)} | {
    "assertEqual", "assertNotEqual", "assertTrue", "assertFalse", "assertIs", "assertIsNot",
    "assertIsNone", "assertIsNotNone", "assertIn", "assertNotIn", "assertIsInstance",
    "assertNotIsInstance", "assertRaises", "assertRaisesRegex", "assertAlmostEqual",
    "assertNotAlmostEqual", "assertGreater", "assertGreaterEqual", "assertLess",
    "assertLessEqual", "assertRegex", "assertCountEqual", "assertListEqual",
    "assertDictEqual", "assertSetEqual", "assertTupleEqual", "assertWarns", "fail",
}


# --------------------------------------------------------------------------- data

@dataclass
class Candidate:
    """A test whose shape suggests it may pass without checking anything."""
    test_file: Path
    test_name: str          # pytest node id suffix: "test_x" or "TestC::test_x"
    line: int
    shape: str              # weak_assertion | unused_result | guarded_assertion | restated_set
    detail: str
    targets: List[Tuple[Path, str]] = field(default_factory=list)  # (file, qualified function name)
    literal_values: List[str] = field(default_factory=list)          # restated_set only
    guard_count: int = 0                                             # guarded_assertion only
    all_guarded: bool = False                                        # guarded_assertion: no assertion outside a guard


@dataclass
class Mutant:
    candidate: Candidate
    operator: str
    target_file: Optional[Path]
    target_name: Optional[str]
    description: str
    outcome: str = "not_run"   # survived | killed | baseline_failed | error | not_run
    output_tail: str = ""


@dataclass
class MutationRun:
    candidates: List[Candidate] = field(default_factory=list)
    mutants: List[Mutant] = field(default_factory=list)
    unjudged: List[Tuple[Candidate, str]] = field(default_factory=list)  # (candidate, reason)
    findings: List[Finding] = field(default_factory=list)

    @property
    def survived(self) -> List[Mutant]:
        return [m for m in self.mutants if m.outcome == "survived"]

    @property
    def killed(self) -> List[Mutant]:
        return [m for m in self.mutants if m.outcome == "killed"]

    def summary(self) -> str:
        return (
            f"{len(self.candidates)} candidate test(s), {len(self.mutants)} mutant(s) run: "
            f"{len(self.survived)} survived (findings), {len(self.killed)} killed, "
            f"{len(self.unjudged)} candidate(s) could not be judged"
        )


# ------------------------------------------------------------- candidate discovery

def _is_test_file(path: Path) -> bool:
    name = path.name
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def _assert_nodes(func: ast.AST) -> List[ast.AST]:
    """`assert` statements plus unittest `self.assert*` / `self.fail` calls."""
    found: List[ast.AST] = []
    for n in ast.walk(func):
        if isinstance(n, ast.Assert):
            found.append(n)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in _UNITTEST_ANY and n.func.attr.startswith(("assert", "fail")):
                found.append(n)
    return found


def _raises_context(func: ast.AST) -> bool:
    for n in ast.walk(func):
        if isinstance(n, ast.With):
            for item in n.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                        and call.func.attr in ("raises", "assertRaises", "assertRaisesRegex", "warns"):
                    return True
    return False


def _is_weak(node: ast.AST) -> bool:
    """A check that a value merely exists, has a type, or is positive."""
    if isinstance(node, ast.Assert):
        t = node.test
        if isinstance(t, ast.Name):
            return True                                  # assert x
        if isinstance(t, ast.Call):
            fn = t.func
            if isinstance(fn, ast.Name) and fn.id == "isinstance":
                return True
            return False                                 # assert f(x): the call may be the check
        if isinstance(t, ast.Compare) and len(t.ops) == 1:
            op, right = t.ops[0], t.comparators[0]
            if isinstance(op, (ast.IsNot,)) and isinstance(right, ast.Constant) and right.value is None:
                return True                              # assert x is not None
            if isinstance(op, (ast.Gt, ast.GtE)) and isinstance(right, ast.Constant) and right.value == 0:
                return True                              # assert x > 0 / len(x) > 0
        return False
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        name = node.func.attr
        if name in ("assertIsNotNone", "assertIsInstance"):
            return True
        if name == "assertTrue" and node.args and isinstance(node.args[0], ast.Name):
            return True
        if name in ("assertGreater", "assertGreaterEqual") and len(node.args) == 2 \
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == 0:
            return True
    return False


def _asserts_under(stmts: List[ast.stmt]) -> List[ast.AST]:
    return [a for stmt in stmts for a in ast.walk(stmt)
            if isinstance(a, ast.Assert) or (
                isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute)
                and a.func.attr.startswith("assert"))]


def _guarded_asserts(func: ast.FunctionDef) -> List[ast.If]:
    """`if` statements whose body asserts and whose else branch does not.

    An if/else that asserts on both sides is a branch, not a guard: one side
    or the other always runs. A bare `if` around an assertion is the shape
    that can silently never fire."""
    guards: List[ast.If] = []
    for n in ast.walk(func):
        if isinstance(n, ast.If) and _asserts_under(n.body) and not _asserts_under(n.orelse):
            guards.append(n)
    return guards


def _assigned_then_unread(func: ast.FunctionDef) -> List[Tuple[str, ast.Assign]]:
    """Names bound from a call and never read afterwards in the function."""
    assigned: Dict[str, ast.Assign] = {}
    for stmt in ast.walk(func):
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name) and isinstance(stmt.value, ast.Call):
            assigned[stmt.targets[0].id] = stmt
    reads: Dict[str, int] = {}
    for n in ast.walk(func):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            reads[n.id] = reads.get(n.id, 0) + 1
    return [(name, stmt) for name, stmt in assigned.items() if reads.get(name, 0) == 0]


def _literal_strings(node: ast.AST) -> List[str]:
    """String constants of a list/set/tuple literal, looking through
    set(...)/sorted(...)/list(...)/frozenset(...) wrappers."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in ("set", "sorted", "list", "frozenset", "tuple") and len(node.args) == 1:
        node = node.args[0]
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        values = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if len(values) >= 3 and len(values) == len(node.elts):
            return values
    return []


def _restated_literals(func: ast.FunctionDef) -> List[str]:
    """A hand-written list of three or more strings that an assertion
    compares (==, <=, >=, in, issubset) against something derived: the
    restatement of a set the source already defines."""
    for a in _assert_nodes(func):
        sides: List[ast.AST] = []
        if isinstance(a, ast.Assert):
            t = a.test
            if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], (ast.Eq, ast.LtE, ast.GtE, ast.In, ast.NotIn)):
                sides = [t.left, t.comparators[0]]
            elif isinstance(t, ast.Call) and isinstance(t.func, ast.Attribute) and t.func.attr in ("issubset", "issuperset"):
                sides = [t.func.value] + list(t.args)
        elif isinstance(a, ast.Call) and a.func.attr in ("assertEqual", "assertSetEqual", "assertListEqual", "assertCountEqual", "assertIn", "assertTrue"):
            sides = list(a.args[:2])
        for side in sides:
            values = _literal_strings(side)
            if values:
                return values
    return []


def _import_map(module: ast.Module) -> Dict[str, Tuple[str, Optional[str]]]:
    """local name -> (module path, attribute or None) for every import."""
    out: Dict[str, Tuple[str, Optional[str]]] = {}
    for n in ast.walk(module):
        if isinstance(n, ast.Import):
            for alias in n.names:
                out[alias.asname or alias.name.split(".")[0]] = (alias.name, None)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            for alias in n.names:
                out[alias.asname or alias.name] = (n.module, alias.name)
    return out


def _module_file(root: Path, dotted: str) -> Optional[Path]:  # ghost_buster: name-disagreement -- `dotted` is `mod` at every call site
    rel = Path(*dotted.split("."))
    for candidate in (root / rel.with_suffix(".py"), root / rel / "__init__.py"):
        if candidate.exists():
            return candidate
    # src/ layouts and pythonpath entries: look one level down.
    for sub in ("src",):
        for candidate in (root / sub / rel.with_suffix(".py"), root / sub / rel / "__init__.py"):
            if candidate.exists():
                return candidate
    return None


def _function_in(file: Path, qualname: str) -> bool:
    tree = _safe_parse(file)
    if tree is None:
        return False
    return _find_function(tree, qualname) is not None


def _find_function(tree: ast.Module, qualname: str) -> Optional[ast.AST]:
    parts = qualname.split(".")
    scope: ast.AST = tree
    for i, part in enumerate(parts):
        nxt = None
        for n in ast.iter_child_nodes(scope):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == part:
                nxt = n
                break
        if nxt is None:
            return None
        scope = nxt
    return scope if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def _class_methods(tree: ast.Module, class_name: str) -> List[str]:
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, ast.ClassDef) and n.name == class_name:
            return [m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not m.name.startswith("_")]
    return []


def _resolve_targets(root: Path, test_file: Path, module: ast.Module, func: ast.FunctionDef) -> List[Tuple[Path, str]]:
    """Project functions the test calls, best effort, via the test file's imports."""
    imports = _import_map(module)
    targets: List[Tuple[Path, str]] = []
    seen = set()

    def add(file: Path, qual: str):
        key = (file, qual)
        if key not in seen and file.resolve() != test_file.resolve() and _function_in(file, qual):
            seen.add(key)
            targets.append(key)

    # names bound to constructed instances: x = Cls(...); later x.method(...)
    instance_of: Dict[str, str] = {}
    for n in ast.walk(func):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) \
                and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            instance_of[n.targets[0].id] = n.value.func.id

    for n in ast.walk(func):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Name) and f.id in imports:
            mod, attr = imports[f.id]
            file = _module_file(root, mod)  # ghost_buster: name-disagreement -- `mod` is `dotted` in the signature
            if file and attr:
                add(file, attr)
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            base = f.value.id
            if base in imports:
                mod, attr = imports[base]
                if attr is None:                       # import mod; mod.func()
                    file = _module_file(root, mod)  # ghost_buster: name-disagreement -- `mod` is `dotted` in the signature
                    if file:
                        add(file, f.attr)
                else:                                  # from mod import Cls; Cls.method()
                    file = _module_file(root, mod)  # ghost_buster: name-disagreement -- `mod` is `dotted` in the signature
                    if file:
                        add(file, f"{attr}.{f.attr}")
            elif base in instance_of and instance_of[base] in imports:
                mod, attr = imports[instance_of[base]]
                file = _module_file(root, mod)  # ghost_buster: name-disagreement -- `mod` is `dotted` in the signature
                if file and attr:
                    add(file, f"{attr}.{f.attr}")
            else:
                # A fixture-injected or otherwise unresolved receiver. If exactly
                # one class imported by this test file defines the method, that
                # is the target; ambiguity means no target, never a guess.
                owners = []
                for local, (mod, attr) in imports.items():
                    if attr is None:
                        continue
                    file = _module_file(root, mod)  # ghost_buster: name-disagreement -- `mod` is `dotted` in the signature
                    if file is None:
                        continue
                    tree = _safe_parse(file)
                    if tree is not None and f.attr in _class_methods(tree, attr):
                        owners.append((file, f"{attr}.{f.attr}"))
                if len(owners) == 1:
                    add(*owners[0])
    return targets


def _safe_parse(path: Path) -> Optional[ast.Module]:
    """An UNCACHED tree. This module mutates what it parses -- `drop_body`
    replaces a function body with `pass` in place -- so it must never
    receive the tree every other detector shares."""
    return corpus.fresh(path)


def find_candidates(root: Path, files: Iterable[Path]) -> List[Candidate]:
    root = Path(root)
    out: List[Candidate] = []
    for path in files:
        path = Path(path)
        if not _is_test_file(path):
            continue
        module = _safe_parse(path)
        if module is None:
            continue
        for node in ast.walk(module):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test"):
                continue
            parent_class = next((c.name for c in ast.walk(module) if isinstance(c, ast.ClassDef) and node in c.body), None)
            node_name = f"{parent_class}::{node.name}" if parent_class else node.name
            asserts = _assert_nodes(node)
            targets = _resolve_targets(root, path, module, node)

            def make(shape: str, detail: str, values=None) -> Candidate:
                return Candidate(path, node_name, node.lineno, shape, detail, list(targets), list(values or []))

            guards = _guarded_asserts(node)
            if guards:
                c = make("guarded_assertion", f"assertion sits behind `if` at line {guards[0].lineno}")
                c.guard_count = len(guards)
                guarded_ids = {id(a) for g in guards for stmt in g.body for a in ast.walk(stmt)}
                c.all_guarded = all(id(a) in guarded_ids for a in asserts)
                out.append(c)
            values = _restated_literals(node)
            if values:
                out.append(make("restated_set", f"asserts equality with a hand-written list of {len(values)} strings", values))
            unread = _assigned_then_unread(node)
            if unread and targets:
                names = ", ".join(n for n, _ in unread)
                out.append(make("unused_result", f"assigns {names} from a call and never reads it"))
            if asserts and all(_is_weak(a) for a in asserts) and not _raises_context(node) and targets:
                out.append(make("weak_assertion", f"every assertion is existence, type or positivity ({len(asserts)} assertion(s))"))
    return out


# ------------------------------------------------------------------- mutation ops

class _ReturnNone(ast.NodeTransformer):
    def visit_Return(self, node):
        return ast.copy_location(ast.Return(value=ast.Constant(value=None)), node)


_FLIP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
         ast.Gt: ast.LtE, ast.LtE: ast.Gt, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
         ast.In: ast.NotIn, ast.NotIn: ast.In}


class _FlipCompare(ast.NodeTransformer):
    def __init__(self):
        self.changed = 0

    def visit_Compare(self, node):
        self.generic_visit(node)
        node.ops = [_FLIP[type(op)]() if type(op) in _FLIP else op for op in node.ops]
        self.changed += 1
        return node


class _BumpConstants(ast.NodeTransformer):
    def __init__(self):
        self.changed = 0

    def visit_Constant(self, node):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            return node
        self.changed += 1
        return ast.copy_location(ast.Constant(value=node.value + 100), node)


def _mutate_function(tree: ast.Module, qualname: str, operator: str) -> Tuple[bool, str]:
    func = _find_function(tree, qualname)
    if func is None:
        return False, "function not found"
    if operator == "return_none":
        has_return = any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(func))
        if not has_return:
            return False, "no value-returning statement"
        _ReturnNone().visit(func)
        return True, f"every `return <value>` in {qualname} replaced with `return None`"
    if operator == "flip_compare":
        t = _FlipCompare()
        t.visit(func)
        return (t.changed > 0), f"{t.changed} comparison(s) in {qualname} inverted"
    if operator == "bump_constants":
        t = _BumpConstants()
        t.visit(func)
        return (t.changed > 0), f"{t.changed} numeric constant(s) in {qualname} moved by +100"
    if operator == "drop_body":
        func.body = [ast.Pass()]
        return True, f"body of {qualname} replaced with `pass`"
    return False, f"unknown operator {operator}"


GUARD_MARKER = "ghost_buster: guarded assertions never ran"


def _instrument_guard(tree: ast.Module, test_qual: str, guard_index: int) -> Tuple[bool, str]:
    """Record whether the guarded branch ever runs, and fail the test at the
    end if it never did.

    The finding is NOT "removing the guard makes the test fail": a guard that
    depends on data can be legitimately false on some inputs. The finding is
    a guard that is never true in the test that carries it, so the assertions
    behind it never run and the test passes while checking nothing.
    """
    func = _find_function(tree, test_qual.replace("::", "."))
    if func is None:
        return False, "test not found"
    guards = _guarded_asserts(func)
    if guard_index >= len(guards):
        return False, "no such guard"
    guard = guards[guard_index]
    flag = f"_ghost_guard_taken_{guard_index}"
    guard.body.insert(0, ast.Assign(
        targets=[ast.Name(id=flag, ctx=ast.Store())], value=ast.Constant(value=True),
    ))
    func.body.insert(0, ast.Assign(targets=[ast.Name(id=flag, ctx=ast.Store())], value=ast.Constant(value=False)))
    func.body.append(ast.Assert(
        test=ast.Name(id=flag, ctx=ast.Load()),
        msg=ast.Constant(value=f"{GUARD_MARKER} (guard at line {guard.lineno})"),
    ))
    ast.fix_missing_locations(func)
    return True, f"`if` guard at line {guard.lineno} instrumented; the test now fails if its assertions never run"


def _extend_enum(tree: ast.Module, values: Sequence[str]) -> Tuple[bool, str]:
    """Append a member to an Enum (or a module-level list/set/tuple) whose
    string members contain every restated value."""
    wanted = set(values)
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, ast.ClassDef):
            members = {stmt.value.value for stmt in n.body if isinstance(stmt, ast.Assign)
                       and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)}
            if wanted <= members:
                n.body.append(ast.Assign(
                    targets=[ast.Name(id="GHOST_MUTANT", ctx=ast.Store())],
                    value=ast.Constant(value="ghost-mutant"), lineno=n.lineno, col_offset=0,
                ))
                ast.fix_missing_locations(tree)
                return True, f"member GHOST_MUTANT added to {n.name}"
        if isinstance(n, ast.Assign) and isinstance(n.value, (ast.List, ast.Set, ast.Tuple)):
            members = {e.value for e in n.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if wanted <= members and isinstance(n.targets[0], ast.Name):
                n.value.elts.append(ast.Constant(value="ghost-mutant"))
                ast.fix_missing_locations(tree)
                return True, f"'ghost-mutant' appended to {n.targets[0].id}"
    return False, "no enum or literal collection defines exactly these values"


def _find_defining_file(root: Path, files: Iterable[Path], values: Sequence[str]) -> Optional[Path]:
    wanted = set(values)
    for path in files:
        path = Path(path)
        if _is_test_file(path) or path.suffix != ".py":
            continue
        tree = _safe_parse(path)
        if tree is None:
            continue
        for n in ast.iter_child_nodes(tree):
            if isinstance(n, ast.ClassDef):
                members = {s.value.value for s in n.body if isinstance(s, ast.Assign)
                           and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str)}
                if wanted <= members:
                    return path
            if isinstance(n, ast.Assign) and isinstance(n.value, (ast.List, ast.Set, ast.Tuple)):
                members = {e.value for e in n.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                if wanted <= members:
                    return path
    return None


# -------------------------------------------------------------------- execution

class _Scratch:
    """A copy of the project in a temp dir, siblings symlinked beside it."""

    def __init__(self, root: Path, link_siblings: bool = True):
        self.root = Path(root).resolve()
        self.tmp = Path(tempfile.mkdtemp(prefix="ghost_mutate_"))
        self.copy = self.tmp / self.root.name
        shutil.copytree(self.root, self.copy, ignore=_COPY_IGNORE, symlinks=True)
        if link_siblings:
            for sibling in self.root.parent.iterdir():
                if sibling.is_dir() and sibling != self.root and not (self.tmp / sibling.name).exists():
                    try:
                        os.symlink(sibling, self.tmp / sibling.name)
                    except OSError:
                        pass

    def path_for(self, original: Path) -> Path:
        return self.copy / Path(original).resolve().relative_to(self.root)

    def restore(self, original: Path) -> None:
        shutil.copy2(original, self.path_for(original))

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def _run_test(scratch: _Scratch, candidate: Candidate, timeout: float) -> Tuple[str, str]:
    """Run one test in the scratch copy. Returns (outcome, output tail)."""
    rel = Path(candidate.test_file).resolve().relative_to(scratch.root)
    node_id = f"{rel.as_posix()}::{candidate.test_name}"
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", node_id]
    env = dict(os.environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    try:
        proc = subprocess.run(cmd, cwd=scratch.copy, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return "error", "timed out"
    text = (proc.stdout or "").strip()
    tail = "\n".join(text.splitlines()[-3:])
    if GUARD_MARKER in text:
        tail = GUARD_MARKER + "\n" + tail
    if proc.returncode == 0:
        return "passed", tail
    if proc.returncode == 1:
        return "failed", tail
    return "error", tail or (proc.stderr or "").strip()[-300:]


def _write_tree(path: Path, tree: ast.Module) -> None:
    path.write_text(ast.unparse(tree) + "\n", encoding="utf-8")


def run_mutations(
    root: Path,
    files: Iterable[Path],
    *,
    max_mutants_per_candidate: int = 6,
    timeout: float = 120.0,
    operators: Sequence[str] = ("drop_body", "return_none", "flip_compare", "bump_constants"),
    link_siblings: bool = True,
    only: Optional[str] = None,
) -> MutationRun:
    """Find candidates, mutate what they call, keep what survived.

    `only` restricts candidates to test files whose path contains the string.
    """
    root = Path(root).resolve()
    file_list = [Path(f) for f in files]
    run = MutationRun(candidates=find_candidates(root, file_list))
    if only:
        run.candidates = [c for c in run.candidates if only in str(c.test_file)]
    if not run.candidates:
        return run

    scratch = _Scratch(root, link_siblings=link_siblings)
    try:
        baseline_cache: Dict[Tuple[Path, str], Tuple[str, str]] = {}
        for cand in run.candidates:
            key = (cand.test_file, cand.test_name)
            if key not in baseline_cache:
                baseline_cache[key] = _run_test(scratch, cand, timeout)
            outcome, tail = baseline_cache[key]
            if outcome != "passed":
                run.unjudged.append((cand, f"test does not pass unmutated ({outcome}): {tail[-120:]}"))
                continue

            mutants = _plan_mutants(cand, root, file_list, operators, max_mutants_per_candidate)  # ghost_buster: name-disagreement -- `max_mutants_per_candidate` is `cap` in the signature
            if not mutants:
                reason = (
                    "no enum or literal collection in the project defines these values; nothing to extend"
                    if cand.shape == "restated_set"
                    else "no mutable target could be resolved from the test's imports"
                )
                run.unjudged.append((cand, reason))
                continue

            for mutant in mutants:
                original = mutant.target_file if mutant.target_file else cand.test_file
                tree = _safe_parse(original)
                if tree is None:
                    mutant.outcome = "error"
                    mutant.output_tail = "could not parse target"
                    run.mutants.append(mutant)
                    continue
                applied, description = _apply(mutant, tree)
                if not applied:
                    continue          # operator did not apply to this target; not a mutant
                mutant.description = description
                _write_tree(scratch.path_for(original), tree)
                try:
                    outcome, tail = _run_test(scratch, cand, timeout)
                finally:
                    scratch.restore(original)
                mutant.output_tail = tail
                if cand.shape == "guarded_assertion":
                    # The instrumented test fails with the marker only when the
                    # guarded assertions never ran. Any other failure is noise.
                    # For a parametrized test the marker fires per case; the
                    # guard counts as never taken only if NO case took it,
                    # which pytest's summary shows as no "passed" at all.
                    some_case_passed = " passed" in (mutant.output_tail or "").splitlines()[-1:][0] if mutant.output_tail else False
                    if outcome == "failed" and GUARD_MARKER in (mutant.output_tail or "") and not some_case_passed:
                        mutant.outcome = "survived"
                    elif outcome in ("passed", "failed"):
                        mutant.outcome = "killed"
                    else:
                        mutant.outcome = "error"
                else:
                    mutant.outcome = "survived" if outcome == "passed" else ("killed" if outcome == "failed" else "error")
                run.mutants.append(mutant)
                if mutant.outcome == "survived":
                    run.findings.append(_finding_for(root, mutant))
                    break             # one proof is enough; do not pile on
    finally:
        scratch.close()
    return run


def _plan_mutants(cand: Candidate, root: Path, files: List[Path], operators: Sequence[str], cap: int) -> List[Mutant]:  # ghost_buster: name-disagreement -- `cap` is `max_mutants_per_candidate` at every call site
    plans: List[Mutant] = []
    if cand.shape == "guarded_assertion":
        for index in range(cand.guard_count):
            plans.append(Mutant(cand, f"guard_never_taken:{index}", None, None, ""))
        return plans
    if cand.shape == "restated_set":
        defining = _find_defining_file(root, files, cand.literal_values)
        if defining is not None:
            plans.append(Mutant(cand, "extend_set", defining, None, ""))
        return plans
    for target_file, qual in cand.targets:
        for op in operators:
            plans.append(Mutant(cand, op, target_file, qual, ""))
            if len(plans) >= cap:
                return plans
    return plans


def _apply(mutant: Mutant, tree: ast.Module) -> Tuple[bool, str]:
    if mutant.operator.startswith("guard_never_taken:"):
        return _instrument_guard(tree, mutant.candidate.test_name, int(mutant.operator.split(":")[1]))
    if mutant.operator == "extend_set":
        return _extend_enum(tree, mutant.candidate.literal_values)
    return _mutate_function(tree, mutant.target_name or "", mutant.operator)


def _finding_for(root: Path, mutant: Mutant) -> Finding:
    cand = mutant.candidate
    if cand.shape == "guarded_assertion":
        # Every assertion behind a guard that never fires: the test checks
        # nothing (CRITICAL). Some assertions outside it: the test checks
        # less than it reads as checking (MAJOR).
        severity = Severity.CRITICAL if cand.all_guarded else Severity.MAJOR
        summary = (f"'{cand.test_name}' never runs its guarded assertions"
                   + ("" if cand.all_guarded else " (its unguarded assertions still run)"))
        what_it_means = ("The branch holding these assertions was never taken during the test. "
                         + ("The test passes while checking nothing." if cand.all_guarded
                            else "What it reads as checking in that branch, it does not check."))
    else:
        severity = Severity.MAJOR
        summary = f"'{cand.test_name}' still passes with {mutant.operator} applied to {mutant.target_name or 'the source'}"
        what_it_means = ("The implementation the test names was broken and the test did not notice. "
                         "Whatever the test's name claims, this is the behaviour it does not check.")
    related = [str(mutant.target_file)] if mutant.target_file else []
    return Finding(
        detector=DETECTOR,
        category=Category.VACUOUS_CHECK,
        layer=Layer.MECHANICAL,
        severity=severity,
        status=Status.CONFIRMED,
        summary=summary,
        detail=(
            f"shape: {cand.shape} ({cand.detail}). mutation: {mutant.description}. "
            f"{what_it_means} Proof is the mutation; re-apply it and run the test to reproduce."
        ),
        evidence=Evidence(
            file=str(cand.test_file), line_start=cand.line,
            snippet=mutant.output_tail or None, related_files=related,
        ),
    )


def render_run(run: MutationRun, verbose: bool = False) -> str:  # ghost_buster: name-disagreement -- `run` is `mutation_run` at every call site
    lines = [f"\nghost_buster --mutate: {run.summary()}\n"]
    for m in run.survived:
        c = m.candidate
        sev = "CRITICAL" if (c.shape == "guarded_assertion" and c.all_guarded) else "MAJOR"
        lines.append(f"  [{sev:13s}] {DETECTOR:25s} {c.test_file}:{c.line}")
        lines.append(f"      {c.test_name}  ({c.shape})")
        lines.append(f"      mutation: {m.description}")
        lines.append("")
    if verbose:
        for m in run.killed:
            lines.append(f"  killed   {m.candidate.test_name:40s} {m.operator} on {m.target_name}")
        for c, why in run.unjudged:
            lines.append(f"  unjudged {c.test_name:40s} {why}")
        lines.append("")
    if not run.survived:
        lines.append("  (no test survived a mutation)\n")
    return "\n".join(lines)
