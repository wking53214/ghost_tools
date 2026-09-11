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
    # 1.5.0: the suffix is derived from the finding's own place, so the
    # mutants that mattered changed with it. An ordinal suffix is the very
    # defect an external reviewer named, and it is a mutant now.
    ("the suffix is an ordinal again, so a new sibling renumbers the rest", _S,
     '            f.id = f"{base}-{hashlib.sha256(where.encode(\'utf-8\')).hexdigest()[:6]}"',
     '            f.id = f"{base}-{sorted(group, key=place).index(f) + 1}"'),
    ("the suffix is constant, so a colliding group collapses again", _S,
     '            f.id = f"{base}-{hashlib.sha256(where.encode(\'utf-8\')).hexdigest()[:6]}"',
     '            f.id = f"{base}-x"'),
    ("the count is reported but the id is unchanged", _S,
     '            f.id = f"{base}-{hashlib.sha256(where.encode(\'utf-8\')).hexdigest()[:6]}"\n            renamed += 1\n',
     "            renamed += 1\n"),
    ("the place that feeds the suffix ignores the line", _S,
     '            where = "|".join(str(part) for part in place(f))',
     '            where = f.evidence.file'),
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
