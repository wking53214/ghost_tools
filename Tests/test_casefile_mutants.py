"""The proof that Tests/test_casefile.py is not vacuous.

The mutant that matters most is the one that makes a prior HIDE a finding:
that is the failure the module's docstring says it will never have, and the
suite has to be able to see it happen.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_casefile.py"
_C = "ghost_buster/casefile.py"

MUTANTS = [
    ("retirement forgets that a later decision overrides an earlier one", "ghost_buster/casefile.py",
     "        for case in sorted(self.cases, key=lambda c: c.when):\n            if case.finding_id and case.outcome in (\"real\", \"false\"):\n",
     "        for case in sorted(self.cases, key=lambda c: c.when, reverse=True):\n            if case.finding_id and case.outcome in (\"real\", \"false\"):\n"),
    ("suppress teaches nothing", _C,
     '_DISPOSITION_OUTCOME = {"fix": "real", "suppress": "false", "document": "real"}',
     '_DISPOSITION_OUTCOME = {"fix": "real", "document": "real"}'),
    ("document counts as false", _C,
     '_DISPOSITION_OUTCOME = {"fix": "real", "suppress": "false", "document": "real"}',
     '_DISPOSITION_OUTCOME = {"fix": "real", "suppress": "false", "document": "false"}'),
    ("an unknown outcome is accepted", _C,
     "        if outcome not in OUTCOMES:\n            raise ValueError",
     "        if False:\n            raise ValueError"),
    ("shape ignores the attributes", _C,
     '    return f"{finding.detector}|{attrs}" if attrs else finding.detector',
     "    return finding.detector"),
    ("an unseen shape stops falling back to the detector", _C,
     "            if matching:\n                return Prior(detector, shape, dict(Counter(c.outcome for c in matching)))",
     "            return Prior(detector, shape, dict(Counter(c.outcome for c in matching)))"),
    ("a suppressed shape is dropped from the report", _C,
     "        return {f.id: self.prior(f.detector, shape_of(f)) for f in findings}",
     "        return {f.id: p for f in findings for p in [self.prior(f.detector, shape_of(f))] if not p.counts.get('false')}"),
    ("the note is not saved", _C,
     '            {"cases": [asdict(c) for c in self.cases]}, indent=2) + "\\n", encoding="utf-8")',
     '            {"cases": [dict(asdict(c), note="") for c in self.cases]}, indent=2) + "\\n", encoding="utf-8")'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_casefile_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_casefile_tests_pass_unmutated():
    result = run_tests_with_mutation(TESTS, _C, 'HEALED = "healed"', 'HEALED = "healed"')
    assert result.returncode == 0, result.stdout[-2000:]
