"""Tests that cannot fail, and tests that only check a mock.

THE FAILURE THIS NAMES

A green suite is evidence only if the tests could have been red. Two shapes
of test look like evidence and are not:

    def test_pipeline_runs():            def test_boots():
        run_pipeline(sample())                pass

The first can fail only by raising; it asserts nothing about what the
pipeline did. The second cannot fail at all. Both count toward "N tests
pass", both make the README's number bigger, and both survive review because
a function named `test_` is read as a test. Recorded in this project's own
history (sentinel_os, finding F9): tests whose assertions sat behind guards
that were never true, so every test returned without ever asserting, and the
suite stayed green while the code was broken.

The third shape is a test whose only assertions are about a mock:

    def test_sends_the_order():
        gateway = Mock()
        place_order(gateway, order)
        gateway.submit.assert_called_once()

That proves the code called the mock, which is a fact about the test's own
wiring. It proves nothing about what a real gateway would have done with the
order. A feature validated only against mocks has not been validated.

WHAT COUNTS AS AN ASSERTION (and why the list is generous)

A detector that reports a test for not using the `assert` statement would be
wrong far more often than right: pytest suites assert through
`pytest.raises`, unittest suites through `self.assertEqual`, and many suites
through helpers of their own. So a test is assertless only when its body
holds none of these, anywhere inside it:

    * an `assert` or `raise` statement, except an assert that cannot fail
      (`assert True`, `assert 1`, `assert x == x`), which counts as nothing;
    * a call whose name (leading underscores stripped) starts with `assert`,
      `check`, `verify`, `expect`, `ensure`, `require` or `confirm`, or is
      `raises`, `warns`, `fail`, `deprecated_call` or `approx` (`pytest.raises`
      inside a `with` is a call like any other);
    * a call to a function whose own body contains an `assert` or `raise` and
      that is defined in the same file, or imported from a module in the same
      folder (`from tree_guard import unchanged`; `conftest.py` is always read):
      a local helper that does the asserting.

That generosity is the point. What is left after it is a test that genuinely
asserts nothing, and the finding says what it saw, not what it inferred.

A test marked `xfail` or `skip` is left alone: it is already declared not to be
evidence. A test file is recognised by `is_test_path` plus the `_test.py`
suffix, the same rule the other detectors use, so the three agree.

SEVERITY

    stub        the body is only `pass`, `...` or a docstring      MAJOR
    assertless  the body does work and asserts nothing              MINOR
    mock-only   every assertion is a Mock assertion                 MINOR

MAJOR for the stub because it is unambiguous: the test can never fail, and it
is counted. MINOR for the other two because the tree cannot tell a smoke test
that is meant to catch a crash from one that was meant to check a result, and
cannot tell a mock-only unit test that sits beside an integration test from
one that stands alone. Both are reported as what they are; a person decides.

Measured 2026-10-14 on the seven circuit repositories (2,733 test functions):
14 assertless, 0 stubs, 0 mock-only. The 14 are smoke tests of the "still
builds" kind, every one of them a real test that can only fail by raising.
Five more were reported before helpers imported from a sibling module were
read; all five asserted through `tree_guard.unchanged`, a context manager
beside the tests. The record is in `calibration.json`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple, Union

from . import corpus
from .naming import is_test_path
from .schema import Category, Evidence, Finding, Layer, Severity, Status

ASSERTLESS = "assertless_test"
MOCK_ONLY = "mock_only_test"

_Func = Union[ast.FunctionDef, ast.AsyncFunctionDef]

_ASSERTING_PREFIXES = ("assert", "check", "verify", "expect", "ensure", "require", "confirm")
_ASSERTING_NAMES = frozenset({"raises", "warns", "fail", "deprecated_call", "approx", "does_not_raise"})
_MOCK_ASSERTIONS = frozenset({
    "assert_called", "assert_called_once", "assert_called_with", "assert_called_once_with",
    "assert_any_call", "assert_has_calls", "assert_not_called",
    "assert_awaited", "assert_awaited_once", "assert_awaited_with", "assert_awaited_once_with",
    "assert_any_await", "assert_has_awaits", "assert_not_awaited",
})
_EXCUSED_MARKS = ("xfail", "skip", "skipif")


def _is_test_file(path: Path) -> bool:
    return is_test_path(path) or path.name.endswith("_test.py")


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _asserts_itself(name: str) -> bool:
    bare = name.lstrip("_")
    return bare.startswith(_ASSERTING_PREFIXES) or bare in _ASSERTING_NAMES


def _asserting_definitions(tree: ast.Module) -> Set[str]:
    """Names of functions defined in `tree` whose own body asserts or raises."""
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("test"):
            if any(isinstance(n, (ast.Assert, ast.Raise)) for n in ast.walk(node)):
                out.add(node.name)
    return out


def _local_asserting_helpers(tree: ast.Module, path: Path) -> Set[str]:
    """Asserting helpers the test file can call by name: defined here, or imported from a module
    in the same folder (a `tree_guard.py` or `support.py` beside the tests), plus `conftest.py`."""
    out = _asserting_definitions(tree)
    folder = path.parent
    sources: dict[Path, List[Tuple[str, str]]] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            candidate = folder / (node.module.replace(".", "/") + ".py")
            if candidate.is_file():
                sources.setdefault(candidate, []).extend((a.name, a.asname or a.name) for a in node.names)
    conftest = folder / "conftest.py"
    if conftest.is_file():
        sources.setdefault(conftest, [])
    for source, names in sources.items():
        other = corpus.parse(source)
        if other is None:
            continue
        defined = _asserting_definitions(other)
        if source == conftest:
            out |= defined
        out |= {alias for name, alias in names if name in defined}
    return out


def _excused(func: ast.AST) -> bool:
    for deco in getattr(func, "decorator_list", []):
        target = deco.func if isinstance(deco, ast.Call) else deco
        text = ast.unparse(target) if hasattr(ast, "unparse") else ""
        if any(text.endswith("." + mark) or text == mark for mark in _EXCUSED_MARKS):
            return True
    return False


def _body_without_docstring(func: _Func) -> List[ast.stmt]:
    body = list(func.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return body


def _is_stub(body: Sequence[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
            continue
        return False
    return True


def _tautology(node: ast.Assert) -> bool:
    """`assert True`, `assert 1`, `assert x == x`: an assert statement that cannot fail.

    The cheapest way to satisfy "the test must assert something" without asserting anything, and
    the one an agent under pressure to pass reaches for first. Red-teamed 2026-10-14."""
    test = node.test
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.Eq, ast.Is, ast.LtE, ast.GtE))):
        return ast.dump(test.left) == ast.dump(test.comparators[0])
    return False


def _shape(func: _Func, helpers: Set[str]) -> Optional[str]:
    """None, "stub", "assertless" or "mock_only" for one test function."""
    body = _body_without_docstring(func)
    if _is_stub(body):
        return "stub"
    plain: List[ast.AST] = []
    mock: List[ast.Call] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            if not _tautology(node):
                plain.append(node)
        elif isinstance(node, ast.Raise):
            plain.append(node)
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in _MOCK_ASSERTIONS and isinstance(node.func, ast.Attribute):
                mock.append(node)
            elif _asserts_itself(name) or name in helpers:
                plain.append(node)
    if plain:
        return None
    return "mock_only" if mock else "assertless"


def _test_functions(tree: ast.Module):
    """(qualified name, function) for every test: module-level `test_*`, and `test*` methods of a class.

    The qualified name (`TestA.test_runs`) is the finding's identity, so two classes with a method of
    the same name are two findings, not one that hides the other."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                    yield f"{node.name}.{item.name}", item


#: shape -> (detector, severity, what the summary says after the test's name, the detail).
_SHAPES = {
    "stub": (ASSERTLESS, Severity.MAJOR, "does nothing: its body is only pass or ...",
             "The test cannot fail. It is still counted, so every count of passing tests in this "
             "repository is one too high for each test like it, and whatever it is named for is unchecked."),
    "assertless": (ASSERTLESS, Severity.MINOR, "asserts nothing",
                   "No assert or raise statement, no call that looks like an assertion (assert*, check*, "
                   "verify*, expect*, ensure*, require*, confirm*, raises, warns, fail) and no call to a local "
                   "helper that asserts, anywhere in the body. The test can fail only by raising, so it checks "
                   "that the code ran, not what it did. MINOR because a smoke test that catches a crash is a "
                   "real test; one that was meant to check a result is not, and the tree cannot tell them apart."),
    "mock_only": (MOCK_ONLY, Severity.MINOR, "is validated only against a mock",
                  "Every assertion in the test is a Mock assertion (assert_called..., assert_awaited...). "
                  "It proves the code called the mock, which is a fact about the test's wiring, and nothing "
                  "about what the real collaborator would have done. If this is the only test of the feature, "
                  "the feature has not been validated."),
}


def _finding(path: Path, func: _Func, shape: str, qualified: str) -> Finding:
    detector, severity, says, detail = _SHAPES[shape]
    return Finding(
        detector=detector,
        category=Category.VACUOUS_CHECK,
        layer=Layer.MECHANICAL,
        severity=severity,
        status=Status.CONFIRMED,
        summary=f"{path.name}:{func.lineno} test '{func.name}' {says}",
        detail=detail,
        # The test is the defect, not the line it starts on; an edit above it must not make a new finding.
        identity_key=f"{shape}: {qualified}",
        evidence=Evidence(file=str(path), line_start=func.lineno,
                          line_end=getattr(func, "end_lineno", None)),
        attributes={"shape": shape, "name": func.name},
    )


def find_shapes(files: Sequence[Path]) -> List[Finding]:
    findings: List[Finding] = []
    for path in (Path(f) for f in files):
        if path.suffix != ".py" or not _is_test_file(path):
            continue
        tree = corpus.parse(path)
        if tree is None:
            continue
        helpers = _local_asserting_helpers(tree, path)
        for qualified, func in _test_functions(tree):
            if _excused(func):
                continue
            shape = _shape(func, helpers)
            if shape is not None:
                findings.append(_finding(path, func, shape, qualified))
    return findings


def detect_assertless_tests(files: Sequence[Path]) -> List[Finding]:
    return [f for f in find_shapes(files) if f.detector == ASSERTLESS]


def detect_mock_only_tests(files: Sequence[Path]) -> List[Finding]:
    return [f for f in find_shapes(files) if f.detector == MOCK_ONLY]
