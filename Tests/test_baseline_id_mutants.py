"""The proof that the recorded-identity tests in
Tests/test_baseline_integrity.py are not vacuous.

Every mutant here restores the behaviour that was live on 2026-09-10: a
finding re-identified the moment it is read back, so a baseline entry
records one id and the diff hunts for another. Nothing crashes and no
count looks wrong -- accepted findings simply reappear as new, which
reads as a repository that regressed rather than a tool that forgot.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

BASELINE_TESTS = "Tests/test_baseline_integrity.py"
_S = "ghost_buster/schema.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("the recorded id is read but never applied", _S,
     "        recorded = payload.get(\"id\")\n        if recorded:\n            finding.id = recorded\n",
     "        recorded = payload.get(\"id\")\n        if recorded:\n            pass\n"),
    ("the recorded id is never read", _S,
     "        recorded = payload.get(\"id\")\n",
     "        recorded = None\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_baseline_id_mutant_is_killed(label, rel, old, new):
    assert_killed(label, BASELINE_TESTS, run_tests_with_mutation(BASELINE_TESTS, rel, old, new))


def test_baseline_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        BASELINE_TESTS, _S, "        recorded = payload.get(\"id\")\n",
        "        recorded = payload.get(\"id\")\n",
    )
    assert result.returncode == 0, result.stdout[-2000:]
