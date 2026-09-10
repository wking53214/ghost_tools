"""The proof that Tests/test_defaults.py is not vacuous.

A defaults suite is unusually easy to write vacuously: assertions about
flags and log lines all pass trivially if you assert the wrong thing. So
every way of quietly putting the checks back to sleep is broken here, one
at a time, in a scratch copy. Every mutant must be killed.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

DEFAULTS_TESTS = "Tests/test_defaults.py"
_C = "ghost_buster/cli.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- a check goes back to opt-in ---
    ("branch scan silently returns to opt-in", _C,
     '        "--branches", action=argparse.BooleanOptionalAction, default=True,\n',
     '        "--branches", action=argparse.BooleanOptionalAction, default=False,\n'),
    ("test status scan silently returns to opt-in", _C,
     '        "--tests", action=argparse.BooleanOptionalAction, default=True,\n',
     '        "--tests", action=argparse.BooleanOptionalAction, default=False,\n'),
    ("secrets scan silently returns to opt-in", _C,
     '        "--secrets", action=argparse.BooleanOptionalAction, default=True,\n',
     '        "--secrets", action=argparse.BooleanOptionalAction, default=False,\n'),

    # --- the opt-out stops working (the other direction) ---
    ("--no-tests is accepted but ignored", _C,
     '        "--tests", action=argparse.BooleanOptionalAction, default=True,\n',
     '        "--tests", action="store_true", default=True,\n'),

    # --- a declined check goes quiet again: the original bug ---
    ("declining the branch scan leaves no receipt", _C,
     '        _skipped("branch scan", "--no-branches")\n', "        pass\n"),
    ("declining the test scan leaves no receipt", _C,
     '        _skipped("test status scan", "--no-tests")\n', "        pass\n"),
    ("declining the secrets scan leaves no receipt", _C,
     '        _skipped("secrets scan", "--no-secrets")\n', "        pass\n"),
    ("declining correlation leaves no receipt", _C,
     '        _skipped("correlation", "--no-correlate")\n', "        pass\n"),
    ("the receipt is written to stdout, where it corrupts --json", _C,
     '    print(f"ghost_buster: {name} SKIPPED at your request ({flag})", file=sys.stderr)\n',
     '    print(f"ghost_buster: {name} SKIPPED at your request ({flag})")\n'),

    # --- mutation's off-state goes unmentioned ---
    ("mutation being off is no longer announced", _C,
     '        print("ghost_buster: mutation analysis NOT RUN (opt-in: --mutate)", file=sys.stderr)\n',
     "        pass\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_defaults_mutant_is_killed(label, rel, old, new):
    assert_killed(label, DEFAULTS_TESTS, run_tests_with_mutation(DEFAULTS_TESTS, rel, old, new))


def test_defaults_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        DEFAULTS_TESTS, _C, 'def _skipped(name: str, flag: str) -> None:\n',
        'def _skipped(name: str, flag: str) -> None:\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
