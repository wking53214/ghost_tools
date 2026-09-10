"""The proof that Tests/test_insecure_default.py is not vacuous.

Two failure directions matter equally here. Going quiet loses a
CRITICAL. Getting loud -- firing on a public API's CORS policy, on a
test fixture, on DEBUG read from the environment -- is how a security
detector gets ignored, which loses the same CRITICAL more slowly.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

INSECURE_TESTS = "Tests/test_insecure_default.py"
_M = "ghost_buster/mechanical.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- it goes quiet ---
    ("the detector is unregistered, so run_all never calls it", _M,
     '@register("insecure_default")\ndef detect_insecure_default',
     "def detect_insecure_default"),
    ("DEBUG = True is no longer reported", _M,
     '            if target.id == "DEBUG" and _is_true(node.value):\n',
     "            if False:\n"),
    ("ALLOWED_HOSTS = ['*'] is no longer reported", _M,
     '            elif target.id == "ALLOWED_HOSTS" and _is_star_list(node.value):\n',
     "            elif False:\n"),
    ("run(debug=True) is no longer reported", _M,
     '    if name == "run" and _is_true(_kwarg(node, "debug")):\n',
     "    if False:\n"),
    ("verify=False is no longer reported", _M,
     "    if isinstance(verify, ast.Constant) and verify.value is False:\n",
     "    if False:\n"),
    ("a bare '*' origin string stops counting as wide open", _M,
     '    if isinstance(node, ast.Constant):\n        return node.value == "*"\n',
     "    if isinstance(node, ast.Constant):\n        return False\n"),
    ("only FastAPI's CORS spelling is recognised, so Flask apps are missed", _M,
     '    origins = _kwarg(node, "allow_origins") or _kwarg(node, "origins")\n'
     '    creds = _kwarg(node, "allow_credentials") or _kwarg(node, "supports_credentials")\n',
     '    origins = _kwarg(node, "allow_origins")\n'
     '    creds = _kwarg(node, "allow_credentials")\n'),

    # --- it gets loud ---
    ("CORS is reported on any origin even without credentials", _M,
     "    if origins is not None and _is_star_list(origins) and _is_true(creds):\n",
     "    if origins is not None and _is_star_list(origins):\n"),
    ('test files are scanned, so every permissive fixture is a CRITICAL', _M,
     '        if _looks_like_a_test(path):\n            continue\n        tree = _parse(path)\n        if tree is None:\n            continue   # unassessable_file says so; see that detector\n',
     '        tree = _parse(path)\n        if tree is None:\n            continue   # unassessable_file says so; see that detector\n'),
    ("a tests/ directory no longer exempts its contents", _M,
     '        or bool(parts & {"tests", "test", "testing", "fixtures"})\n', ""),
    ("DEBUG read from the environment is reported as enabled", _M,
     "def _is_true(node) -> bool:\n"
     "    return isinstance(node, ast.Constant) and node.value is True\n",
     "def _is_true(node) -> bool:\n    return node is not None\n"),
    ("verify=True is reported as disabled", _M,
     "    if isinstance(verify, ast.Constant) and verify.value is False:\n",
     "    if isinstance(verify, ast.Constant):\n"),
    ('non-python files are scanned, so prose about DEBUG is a CRITICAL', _M,
     '    for path in sorted(f for f in files if f.suffix == ".py"):\n        if _looks_like_a_test(path):\n            continue\n        tree = _parse(path)\n        if tree is None:\n            continue   # unassessable_file says so; see that detector\n',
     '    for path in sorted(files):\n        if _looks_like_a_test(path):\n            continue\n        tree = _parse(path)\n        if tree is None:\n            continue   # unassessable_file says so; see that detector\n'),

    # --- it says the wrong thing ---
    ("a public debug console is downgraded to a nit", _M,
     '    "DEBUG": (\n        Severity.CRITICAL,\n',
     '    "DEBUG": (\n        Severity.MINOR,\n'),
    ("the finding stops pointing at a line", _M,
     "                        line_start=getattr(node, \"lineno\", None),\n",
     "                        line_start=None,\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_insecure_default_mutant_is_killed(label, rel, old, new):
    assert_killed(label, INSECURE_TESTS, run_tests_with_mutation(INSECURE_TESTS, rel, old, new))


def test_insecure_default_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        INSECURE_TESTS, _M, "def _insecure_nodes(node):\n", "def _insecure_nodes(node):\n",
    )
    assert result.returncode == 0, result.stdout[-2000:]
