"""The proof that Tests/test_unauthenticated_route.py is not vacuous.

This detector's design is a set of thresholds that keep it quiet. Loosen
any one of them and it becomes the naive "routes with no auth" check that
fires on every login endpoint and health probe -- so most of these mutants
make it LOUD, and each must be caught.

TWO MUTANTS FROM THE FIRST RUN ARE DELIBERATELY ABSENT. Both targeted a
`_MIN_ROUTES = 3` constant, and both survived because neither could change
an outcome: with two routes the most protected a module can be while still
having an unprotected sibling is one of two, and 0.5 already fails the
majority gate. The constant was removed rather than propped up with a test
that would only have been asserting its own arithmetic.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

ROUTE_TESTS = "Tests/test_unauthenticated_route.py"
_M = "ghost_buster/mechanical.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- it becomes the naive check ---
    ("the protected-majority gate is removed (every login route is reported)", _M,
     "        if len(protected) / len(routes) < _PROTECTED_MAJORITY:\n            continue"
     "    # the module is not claiming to be a protected one\n",
     "        if False:\n            continue\n"),
    ("the majority threshold drops to nothing", _M,
     "_PROTECTED_MAJORITY = 0.6\n", "_PROTECTED_MAJORITY = 0.0\n"),
    ("the majority gate is inverted (only protected modules are reported)", _M,
     "        if len(protected) / len(routes) < _PROTECTED_MAJORITY:\n",
     "        if len(protected) / len(routes) > _PROTECTED_MAJORITY:\n"),
    ("test files are scanned", _M,
     "        if _looks_like_a_test(path):\n            continue\n"
     "        tree = _parse(path)\n"
     "        if tree is None:\n            continue\n"
     "        routes = [\n",
     "        tree = _parse(path)\n"
     "        if tree is None:\n            continue\n"
     "        routes = [\n"),
    ("every function counts as a route, not just decorated ones", _M,
     "            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_route(n)\n",
     "            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))\n"),

    # --- it stops seeing auth, which makes every module look public ---
    ("decorator-style auth stops counting (every Flask router reads as public)", _M,
     "    found = [n for n in _decorator_names(node) if n in _AUTH_MARKERS]\n",
     "    found = []\n"),
    ("parameter-style auth stops counting (every FastAPI router reads as public)", _M,
     "        for default in list(args.defaults) + [d for d in args.kw_defaults if d]:\n",
     "        for default in []:\n"),
    ("a Depends(...) wrapper hides the marker inside it", _M,
     "            if isinstance(default, ast.Call):\n"
     "                for a in default.args:\n",
     "            if False:\n                for a in default.args:\n"),

    # --- it stops reporting at all ---
    ("the detector is unregistered, so run_all never calls it", _M,
     '@register("unauthenticated_route")\ndef detect_unauthenticated_route',
     "def detect_unauthenticated_route"),
    ("protected routes are reported instead of unprotected ones", _M,
     "            if _auth_names(node):\n                continue\n"
     "            out.append(Finding(\n"
     '                detector="unauthenticated_route",\n',
     "            if not _auth_names(node):\n                continue\n"
     "            out.append(Finding(\n"
     '                detector="unauthenticated_route",\n'),
    ("only GET is recognised as a route", _M,
     '    "route", "get", "post", "put", "patch", "delete", "head", "options",\n'
     '    "websocket", "api_route",\n',
     '    "get",\n'),

    # --- it says the wrong thing ---
    ("a forgotten handler is downgraded to a nit", _M,
     "                severity=Severity.MAJOR,\n"
     "                status=Status.CONFIRMED,\n"
     "                summary=(f\"{_portable_path(path)}: route '{node.name}' has no \"\n",
     "                severity=Severity.MINOR,\n"
     "                status=Status.CONFIRMED,\n"
     "                summary=(f\"{_portable_path(path)}: route '{node.name}' has no \"\n"),
    ("the finding stops naming the route", _M,
     '                    "route": node.name,\n', '                    "route": "",\n'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_unauthenticated_route_mutant_is_killed(label, rel, old, new):
    assert_killed(label, ROUTE_TESTS, run_tests_with_mutation(ROUTE_TESTS, rel, old, new))


def test_unauthenticated_route_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        ROUTE_TESTS, _M, "def _is_route(node) -> bool:\n", "def _is_route(node) -> bool:\n",
    )
    assert result.returncode == 0, result.stdout[-2000:]
