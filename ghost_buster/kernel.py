"""A shared kernel, and the classes that shadow it.

When a library extracts its shared contracts into one package (a kernel:
the classes several repositories agree on), the repositories that still
carry their own copy are the migration's remaining work, and nothing in a
single-repository scan can see them: `drifted_copy` compares files inside
one tree, and a kernel lives in another.

    ghost-buster PATH --kernel ../cns

Every top-level class in the kernel is hashed by structure, docstrings
stripped, the same `ast.dump` hash `drifted_copy` uses so that formatting
and comments do not register and a changed condition does. A class in the
patient with the same name is then one of three things:

| shape                          | finding             | severity |
|--------------------------------|---------------------|----------|
| identical                      | `kernel_shadow`     | MAJOR: import it instead |
| same name, most members shared | `drifted_contract`  | MAJOR: a copy that diverged |
| same name, little else         | nothing, but counted | a coincidence of names |

The third row is the calibration. A `Node` in a tree-drawing module is
not a drifted copy of a graph kernel's `Node`; without the member-overlap
gate every common class name in the library would be reported as
drifted. Measured with CNS as the kernel across 38 repositories before
this shipped (see CHANGELOG 1.1.0).

The kernel's own files are never patients: a checkout of the kernel
sitting inside the scanned tree (a vendored copy, a submodule) is skipped,
because a kernel that shadows itself is the tool reporting its own
argument.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

from . import corpus
from .naming import is_test_path
from .schema import Category, Evidence, Finding, Layer, Severity, Status

KERNEL_SHADOW = "kernel_shadow"
DRIFTED_CONTRACT = "drifted_contract"

# A same-name class is a drifted copy only if it still shares most of the
# kernel class's members (methods, enum members, fields). Below this it is
# a coincidence of names.
SHARED_MEMBERS = 0.5


def _strip_docstrings(node: ast.AST) -> ast.AST:
    """A copy of the node with every docstring removed: a documentation
    edit is not a drift."""
    node = copy.deepcopy(node)
    for n in ast.walk(node):
        body = getattr(n, "body", None)
        if (isinstance(body, list) and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):
            del body[0]
            if not body:
                body.append(ast.Pass())
    return node


def _shape(node: ast.ClassDef) -> str:
    return hashlib.sha256(
        ast.dump(_strip_docstrings(node), annotate_fields=True, include_attributes=False).encode()
    ).hexdigest()


def _methods(node: ast.ClassDef) -> Set[str]:
    return {n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _members(node: ast.ClassDef) -> Set[str]:
    """The names a class declares at its top level: methods, and the
    class-level assignments that make an Enum's members, a dataclass's
    fields, a Protocol's attributes. The overlap gate compares methods
    when the kernel class has any (a copy that sets its fields in
    `__init__` instead of declaring them is still the same contract) and
    falls back to these for a class with none, so an Enum with a member
    added is still a drifted contract."""
    out: Set[str] = set()
    for n in node.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
    return out


@dataclass(frozen=True)
class KernelClass:
    name: str
    path: Path
    shape: str
    methods: frozenset      # the overlap gate, when the kernel class has any
    members: frozenset      # the gate for an Enum, a dataclass, a Protocol: no methods, only names


def _classes(path: Path) -> List[ast.ClassDef]:
    tree = corpus.parse(path)
    if tree is None:
        return []
    return [n for n in tree.body if isinstance(n, ast.ClassDef)]


def load_kernel(root: Path) -> Dict[str, KernelClass]:
    """Every top-level class the kernel defines, by name. A name defined
    twice in the kernel is the kernel's own problem and is skipped here,
    since there is no one shape to compare against."""
    seen: Dict[str, List[KernelClass]] = {}
    for path in sorted(Path(root).rglob("*.py")):
        if is_test_path(path) or any(part in _SKIP for part in path.parts):
            continue
        for node in _classes(path):
            seen.setdefault(node.name, []).append(
                KernelClass(node.name, path, _shape(node), frozenset(_methods(node)), frozenset(_members(node))))
    return {name: found[0] for name, found in seen.items() if len(found) == 1}


_SKIP = {".git", "venv", ".venv", "node_modules", "site-packages", "__pycache__", "build", "dist"}


@dataclass
class KernelReport:
    ran: bool
    kernels: Tuple[Path, ...]
    kernel_classes: int = 0
    shadows: int = 0
    drifted: int = 0
    collisions: int = 0                      # same name, unrelated by shape: not reported
    skipped_inside_kernel: int = 0           # patient files that are the kernel itself
    reason: str = ""


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    p = path.resolve()
    return any(p == r or r in p.parents for r in roots)


def check_kernel(files: Sequence[Path], kernels: Sequence[Path]) -> Tuple[List[Finding], KernelReport]:
    roots = [Path(k).resolve() for k in kernels]
    report = KernelReport(ran=False, kernels=tuple(roots))
    missing = [r for r in roots if not r.is_dir()]
    if missing:
        report.reason = "kernel path is not a directory: " + ", ".join(str(m) for m in missing)
        return [], report
    kernel: Dict[str, KernelClass] = {}
    for r in roots:
        kernel.update(load_kernel(r))
    report.kernel_classes = len(kernel)
    report.ran = True
    findings: List[Finding] = []
    for path in (Path(f) for f in files):
        if is_test_path(path):
            continue
        if _inside(path, roots):
            report.skipped_inside_kernel += 1
            continue
        for node in _classes(path):
            k = kernel.get(node.name)
            if k is None:
                continue
            shape = _shape(node)
            members = _members(node) if not k.methods else _methods(node)
            against = k.methods or k.members
            if shape == k.shape:
                report.shadows += 1
                findings.append(_finding(KERNEL_SHADOW, Category.DUPLICATION, path, node, k,
                    f"class `{node.name}` is the kernel's `{node.name}` ({k.path.name}), structurally identical: import it instead",
                    "Every definition in this class matches the kernel's, docstrings aside. Two copies of one "
                    "contract means the next fix lands in one of them. Replace the class with an import from "
                    "the kernel; if this copy is deliberate (a frozen fork), record that decision."))
                continue
            shared = len(members & against)
            if against and shared / len(against) >= SHARED_MEMBERS:
                report.drifted += 1
                differ = sorted(members ^ against)
                findings.append(_finding(DRIFTED_CONTRACT, Category.PARALLEL_IMPLEMENTATION, path, node, k,
                    f"class `{node.name}` diverged from the kernel's `{node.name}` ({k.path.name}): "
                    f"{shared} of {len(against)} kernel {'methods' if k.methods else 'members'} shared"
                    + (f", differing: {', '.join(differ[:6])}" if differ else ", same members, different bodies"),
                    "Same name, most of the same methods, a different structure: a copy of the contract "
                    "that diverged, or the kernel that moved on without it. Which side is right is a "
                    "judgement; that they disagree is not."))
            else:
                report.collisions += 1
    return findings, report


def _finding(detector, category, path, node, k: KernelClass, summary, detail) -> Finding:
    return Finding(
        detector=detector,
        category=category,
        layer=Layer.MECHANICAL,
        severity=Severity.MAJOR,
        status=Status.CONFIRMED,
        summary=f"{path.name}: {summary}",
        detail=f"{path}:{node.lineno}\nkernel: {k.path}\n{detail}",
        evidence=Evidence(file=str(path), line_start=node.lineno, related_files=[str(k.path)]),
        attributes={"class": node.name, "kernel_shape": k.shape},
    )


def render_report(report: KernelReport) -> str:
    if not report.ran:
        return f"ghost_buster: kernel check did not run: {report.reason}"
    names = ", ".join(k.name for k in report.kernels)
    line = (f"ghost_buster: kernel check against {names} ({report.kernel_classes} class(es)): "
            f"{report.shadows} shadow(s), {report.drifted} drifted contract(s), "
            f"{report.collisions} same-name class(es) unrelated by shape (not reported)")
    if report.skipped_inside_kernel:
        line += f"; {report.skipped_inside_kernel} file(s) inside the kernel skipped"
    return line
