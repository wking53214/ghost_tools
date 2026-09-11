"""The proof that Tests/test_operate_restores.py is not vacuous.

Every mutant here breaks the restoration in a way that a happy-path test
would never notice, which is exactly how the defect these tests exist for
survived: the operation returned the tree correctly whenever nothing went
wrong, and nothing tested what happened when something did.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_operate_restores.py"
_O = "ghost_buster/operate.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)
    ("the guard yields but never restores", _O,
     '    try:\n        yield\n    finally:\n        try:\n            _git(root, "reset", "-q", "--hard", "HEAD")\n',
     '    try:\n        yield\n    finally:\n        try:\n            pass\n'),
    ("the tree goes back but keeps the tool's edits", _O,
     '            _git(root, "reset", "-q", "--hard", "HEAD")\n            _git(root, "checkout", "-q", return_to)\n',
     '            _git(root, "checkout", "-q", return_to)\n'),
    ("the edits are discarded but the branch is not", _O,
     '            _git(root, "reset", "-q", "--hard", "HEAD")\n            _git(root, "checkout", "-q", return_to)\n',
     '            _git(root, "reset", "-q", "--hard", "HEAD")\n'),
    ("restoration runs only when nothing raised", _O,
     "    try:\n        yield\n    finally:\n",
     "    try:\n        yield\n    except BaseException:\n        raise\n    else:\n"),
    ("a failed restoration is swallowed", _O,
     '            raise LeftOnTheTable(\n',
     '            _ = LeftOnTheTable(\n'),
    ("the operation is guarded, the commit is not", _O,
     "    _git(root, \"checkout\", \"-q\", \"-b\", branch)\n    with _on_the_table(root, return_to):\n",
     "    _git(root, \"checkout\", \"-q\", \"-b\", branch)\n    if True:\n"),
    ("a detached patient goes back to a branch name", _O,
     "    return_to = came_in_on or head_before\n",
     "    return_to = came_in_on or 'HEAD'\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_the_suite_passes_unmutated():
    """The control. Without it, a mutant list that kills everything because
    the suite is broken would look like proof."""
    result = run_tests_with_mutation(TESTS, _O, "def _cut(", "def _cut(")
    assert result.returncode == 0, result.stdout[-2000:]
