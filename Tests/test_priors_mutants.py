"""The proof that Tests/test_priors.py is not vacuous. The working tree is
never modified."""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

PRIORS_TESTS = "Tests/test_priors.py"
_P = "ghost_buster/priors.py"
_C = "ghost_buster/casefile.py"

MUTANTS = [
    ("a decision with no finding id is counted as held", _P,
     "    if not case.finding_id or not case.decision:\n        return UNKNOWN\n",
     "    if not case.finding_id or not case.decision:\n        return HELD\n"),
    ("a later contradicting decision does not count as revisited", _P,
     "    if any(c.decision and c.decision != case.decision for c in later_cases):\n        return REVISITED\n",
     "    if False:\n        return REVISITED\n"),
    ("a fix whose finding is still present reads as held", _P,
     "    return HELD if hist.absent_last_run else OPEN\n",
     "    return HELD\n"),
    ("a fix whose finding came back reads as open", _P,
     "    if hist.returns and hist.last_seen > case.when:\n        return RETURNED\n",
     "    if False:\n        return RETURNED\n"),
    ("the hold rate counts unknowns as judged", _P,
     "    judged = sum(n for k, n in self.verdicts.items() if k != UNKNOWN)\n",
     "    judged = sum(self.verdicts.values())\n"),
    ("only the oldest notes are kept", _P,
     "        if c.note:\n            row.notes.insert(0, c.note)\n",
     "        if c.note:\n            row.notes.append(c.note)\n"),
    ("triage forgets which finding it decided", _C,
     "                                   finding_id=f.id, file=f.evidence.file if f.evidence else \"\",\n                                   decision=str(f.disposition)))\n",
     "                                   decision=str(f.disposition)))\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_priors_mutant_is_killed(label, rel, old, new):
    assert_killed(label, PRIORS_TESTS, run_tests_with_mutation(PRIORS_TESTS, rel, old, new))


def test_priors_tests_pass_unmutated():
    result = run_tests_with_mutation(PRIORS_TESTS, _P, 'HELD = "held"', 'HELD = "held"')
    assert result.returncode == 0, result.stdout[-2000:]
