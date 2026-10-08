"""A method that calls `self.something()` when nothing called that exists.

THE FAILURE THIS CATCHES

A class whose method calls `self._check_node_compliance(...)`, where no
`_check_node_compliance` is defined on the class, on any base class, or
assigned to `self` anywhere. The call raises AttributeError the first time
it runs. Until then the class imports, instantiates and reads as finished:
an overclaim. TOUCHSTONE keeps the specimen
(`specimens/progressions/uztc/uztc-construct-v1.2-validated.py`, described
as "a 7-layer registry", whose only method makes exactly this call; MANIFEST
section 3.2).

WHY IT ONLY SPEAKS WHEN IT CAN SEE THE WHOLE CLASS

Python lets a name arrive on an instance in many ways: inheritance from a
class defined elsewhere, a metaclass, `__getattr__`, `setattr`, a decorator,
a mixin from a library. A detector that guessed through those would be
wrong often enough to be ignored. So this one abstains on any class it
cannot see completely, and the conditions are strict:

  - every base is either absent, `object`, or a class defined in the same
    file (followed recursively, with the same rule);
  - no `metaclass=` keyword and no class decorator;
  - no `__getattr__` / `__getattribute__` on the class or its bases;
  - no `setattr(` or `__dict__` anywhere in the class body.

What remains is a class whose complete vocabulary is on the page. A call on
`self` to a name outside that vocabulary is CONFIRMED: there is nowhere
else for it to come from.

Members counted: methods, class-level assignments, and every `self.X = ...`
/ `self.X: T = ...` inside the class's methods (a callable stored on the
instance is a real method as far as a call is concerned).
"""

from __future__ import annotations

import ast
from pathlib import Path

from . import corpus
from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "undefined_self_method"

_DYNAMIC_HOOKS = {"__getattr__", "__getattribute__"}


def _own_members(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for n in ast.walk(target):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    for node in ast.walk(cls):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            for t in ast.walk(target):
                if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                        and t.value.id == "self"):
                    names.add(t.attr)
    return names


def _is_dynamic(cls: ast.ClassDef) -> bool:
    if cls.decorator_list or any(k.arg == "metaclass" for k in cls.keywords):
        return True
    for node in ast.walk(cls):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in {"setattr", "getattr", "delattr"}:
            return True
        if isinstance(node, ast.Attribute) and node.attr == "__dict__":
            return True
    return False


def _vocabulary(cls: ast.ClassDef, classes: dict[str, ast.ClassDef],
                seen: set[str] | None = None) -> set[str] | None:
    """Every member name visible on instances of `cls`, or None if unknowable."""
    seen = set() if seen is None else seen
    if cls.name in seen:
        return None
    seen.add(cls.name)
    if _is_dynamic(cls):
        return None
    names = _own_members(cls)
    if names & _DYNAMIC_HOOKS:
        return None
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "object":
            continue
        if isinstance(base, ast.Name) and base.id in classes:
            inherited = _vocabulary(classes[base.id], classes, seen)
            if inherited is None:
                return None
            names |= inherited
            continue
        return None
    return names


def _self_calls(cls: ast.ClassDef):
    """(name, line) for every `self.name(...)` in this class's own methods."""
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.args.args or node.args.args[0].arg != "self":
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and isinstance(sub.func.value, ast.Name) and sub.func.value.id == "self"):
                yield sub.func.attr, sub.lineno, node.name


def detect_undefined_self_methods(files: list[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in sorted(f for f in files if f.suffix == ".py"):
        tree = corpus.parse(path)
        if tree is None:
            continue
        classes: dict[str, ast.ClassDef] = {}
        duplicated: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if node.name in classes:
                    duplicated.add(node.name)
                classes[node.name] = node
        for name, cls in sorted(classes.items()):
            if name in duplicated:
                continue  # two classes, one name: which one is the base is a guess
            vocab = _vocabulary(cls, classes)
            if vocab is None:
                continue
            reported: set[str] = set()
            for attr, line, method in _self_calls(cls):
                if attr in vocab or attr in reported or attr.startswith("__"):
                    continue
                reported.add(attr)
                out.append(Finding(
                    detector=DETECTOR,
                    category=Category.DEAD_CODE,
                    layer=Layer.MECHANICAL,
                    severity=Severity.MAJOR,
                    status=Status.CONFIRMED,
                    summary=(f"{name}.{method} calls self.{attr}(), and {name} has no "
                             f"'{attr}' anywhere: not defined, not inherited, never "
                             f"assigned. It raises AttributeError the first time it runs"),
                    evidence=Evidence(file=str(path), line_start=line, line_end=line),
                    detail=(
                        f"Every base of {name} is visible in this file and none of them "
                        f"defines '{attr}', the class has no __getattr__, no metaclass, "
                        "no decorator and no setattr, so there is nowhere else for the "
                        "name to come from. The method reads as finished and cannot run "
                        "past this call. Either the helper was never written, or it was "
                        "renamed and this call was missed."
                    ),
                    identity_key=f"{name}.{attr}",
                    attributes={"class": name, "method": method, "missing": attr},
                ))
    return out
