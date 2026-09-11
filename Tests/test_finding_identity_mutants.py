"""The proof that Tests/test_finding_identity.py is not vacuous.

Every mutant here either lets two distinct findings share an identity again
-- the measured defect -- or renumbers findings that were never colliding,
which would churn every committed baseline in the library. Both are ways to
be wrong about which finding is which.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_finding_identity.py"
_S = "ghost_buster/schema.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)
    ("nothing is ever disambiguated", _S,
     "        if len(group) < 2:\n            continue\n",
     "        if True:\n            continue\n"),
    ("a duplicate emission is split into two findings", _S,
     "        if len(distinct) < 2:\n            continue\n",
     "        if False:\n            continue\n"),
    ("the first occurrence is renumbered too", _S,
     "            if n == 1:\n                continue\n",
     "            if n == 0:\n                continue\n"),
    ("order depends on scan order, not on place", _S,
     "        for n, f in enumerate(sorted(group, key=place), start=1):\n",
     "        for n, f in enumerate(group, start=1):\n"),
    ("the suffix is constant, so three collide into two", _S,
     '            f.id = f"{base}-{n}"\n',
     '            f.id = f"{base}-2"\n'),
    ("the count is reported but the id is unchanged", _S,
     '            f.id = f"{base}-{n}"\n            renamed += 1\n',
     '            renamed += 1\n'),
    ("place ignores where the finding is, so two places look like one", _S,
     "            return (f.evidence.file, f.evidence.line_start or 0,\n"
     "                    f.evidence.line_end or 0, f.detail)\n",
     "            return (f.evidence.file, f.detail)\n"),
    ("place ignores the detail, so two correlations look like one", _S,
     "                    f.evidence.line_end or 0, f.detail)\n",
     "                    f.evidence.line_end or 0)\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_the_suite_passes_unmutated():
    result = run_tests_with_mutation(TESTS, _S, "def disambiguate_ids(", "def disambiguate_ids(")
    assert result.returncode == 0, result.stdout[-2000:]
