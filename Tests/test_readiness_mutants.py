"""The proof that Tests/test_readiness.py is not vacuous.

Every mutant here opens the gate: treats unknown as fine, drops a criterion,
or lets a disqualifying finding through. Each is a way to hand the serum to
the wrong patient.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_readiness.py"
_R = "ghost_buster/readiness.py"

MUTANTS = [
    ("unknown counts FOR the patient", _R,
     "        return all(c.met is True for c in self.criteria)",
     "        return all(c.met is not False for c in self.criteria)"),
    ("tests not running is treated as tests passing", _R,
     '        criteria.append(Criterion(TESTS, None, f"tests {checks.get(\'tests\', \'not run\')}; run with --tests"))',
     '        criteria.append(Criterion(TESTS, True, "assumed"))'),
    ("secrets not running is treated as no secrets", _R,
     '        criteria.append(Criterion(SECRETS, None, f"secrets {checks.get(\'secrets\', \'not run\')}; run with --secrets"))',
     '        criteria.append(Criterion(SECRETS, True, "assumed"))'),
    ("a hollow contract stops disqualifying", _R,
     '    n = _count(findings, "dead_end_call")\n    criteria.append(Criterion(HOLLOW, n == 0,',
     '    n = 0\n    criteria.append(Criterion(HOLLOW, n == 0,'),
    ("a minor drifted copy disqualifies", _R,
     '    n = _count(findings, "drifted_copy", Severity.MAJOR)',
     '    n = _count(findings, "drifted_copy")'),
    ("an unparseable file stops disqualifying", _R,
     '    n = _count(findings, "unassessable_file")\n    criteria.append(Criterion(PARSES, n == 0,',
     '    n = 0\n    criteria.append(Criterion(PARSES, n == 0,'),
    ("the render stops saying why", _R,
     '            lines.append(f"  {mark}  {c.name:34s} {c.evidence}")',
     '            lines.append(f"  {mark}  {c.name:34s}")'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_readiness_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_readiness_tests_pass_unmutated():
    result = run_tests_with_mutation(TESTS, _R, 'PARSES = "parses completely"', 'PARSES = "parses completely"')
    assert result.returncode == 0, result.stdout[-2000:]
