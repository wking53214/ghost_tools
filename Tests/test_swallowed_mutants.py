"""The proof that Tests/test_swallowed.py is not vacuous.

Swallowing is sometimes correct, so the mutants that matter are the ones
that lose the breadth distinction: a detector that rates `except ImportError:
pass` the same as `except Exception: pass` is one nobody reads twice.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_swallowed.py"
_S = "ghost_buster/swallowed.py"

MUTANTS = [
    # Breadth is the whole severity argument.
    ("a narrow handler is rated like a broad one", _S,
     "            severity=Severity.MAJOR if broad else Severity.MINOR,",
     "            severity=Severity.MAJOR,"),
    ("a broad handler is rated like a narrow one", _S,
     "            severity=Severity.MAJOR if broad else Severity.MINOR,",
     "            severity=Severity.MINOR,"),
    ("BaseException stops counting as everything", _S,
     '_CATCHES_EVERYTHING = frozenset({"Exception", "BaseException"})',
     '_CATCHES_EVERYTHING = frozenset({"Exception"})'),
    ("a bare except stops counting as everything", _S,
     '        if self.caught == BARE:\n            return True',
     "        if False:\n            return True"),
    ("a tuple is matched whole instead of by its members", _S,
     '        names = {n.strip(" ()") for n in self.caught.split(",")}\n'
     "        return bool(names & _CATCHES_EVERYTHING)",
     "        return self.caught in _CATCHES_EVERYTHING"),

    # What counts as swallowing.
    ("a handler that does something counts as empty", _S,
     "    return len(body) == 1 and isinstance(body[0], ast.Pass)",
     "    return True"),
    ("a docstring counts as handling the exception", _S,
     "        body = body[1:]\n    return len(body) == 1 and isinstance(body[0], ast.Pass)",
     "        return False\n    return len(body) == 1 and isinstance(body[0], ast.Pass)"),
    ("any pass anywhere is a swallowed exception", _S,
     "            if isinstance(node, ast.ExceptHandler) and _swallows(node):",
     "            if isinstance(node, (ast.ExceptHandler, ast.Pass)) and _swallows(node):"),

    # Test files.
    ("teardown cleanup in tests is reported", _S,
     "        if is_test_path(path):\n            continue",
     "        if False:\n            continue"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_swallowed_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_swallowed_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _S, 'DETECTOR = "swallowed_exception"',
                                     'DETECTOR = "swallowed_exception"')
    assert result.returncode == 0, result.stdout[-2000:]
