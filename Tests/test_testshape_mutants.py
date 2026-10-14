"""The proof that Tests/test_testshape.py is not vacuous: break
ghost_buster/testshape.py one way at a time in a scratch copy and run only
that file. Every mutant here must be killed.

A detector whose whole subject is tests that cannot fail had better have
tests that can. The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_testshape.py"
_S = "ghost_buster/testshape.py"

MUTANTS = [
    ("a stub is reported as merely assertless (MINOR, not MAJOR)", _S,
     "    if _is_stub(body):\n        return \"stub\"\n",
     "    if _is_stub(body):\n        return \"assertless\"\n"),
    ("the assert statement no longer counts as an assertion", _S,
     "        if isinstance(node, (ast.Assert, ast.Raise)):\n            plain.append(node)\n",
     "        if isinstance(node, ast.Raise):\n            plain.append(node)\n"),
    ("a helper imported from a sibling module no longer counts", _S,
     "        out |= {alias for name, alias in names if name in defined}\n",
     "        pass\n"),
    ("a local helper that asserts no longer counts", _S,
     "            elif _asserts_itself(name) or name in helpers:\n",
     "            elif _asserts_itself(name):\n"),
    ("a mock assertion is treated as a real one", _S,
     "            if name in _MOCK_ASSERTIONS and isinstance(node.func, ast.Attribute):\n                mock.append(node)\n",
     "            if name in _MOCK_ASSERTIONS and isinstance(node.func, ast.Attribute):\n                plain.append(node)\n"),
    ("xfail and skip no longer excuse a test", _S,
     "            if _excused(func):\n                continue\n",
     "            if False:\n                continue\n"),
    ("non-test files are read as test files", _S,
     "        if path.suffix != \".py\" or not _is_test_file(path):\n",
     "        if path.suffix != \".py\":\n"),
    ("methods of a test class are no longer seen", _S,
     "                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith(\"test\"):\n                    yield item\n",
     "                if False:\n                    yield item\n"),
    ("the identity changes when the line moves", _S,
     "        identity_key=f\"{shape}: {func.name}\",\n",
     "        identity_key=None,\n"),
    ("a docstring-only body is no longer a stub", _S,
     "    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \\\n            and isinstance(body[0].value.value, str):\n        body = body[1:]\n",
     "    if False:\n        body = body[1:]\n"),
]


@pytest.mark.parametrize("label, path, old, new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, path, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, path, old, new))
