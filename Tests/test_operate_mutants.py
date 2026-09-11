"""The proof that Tests/test_operate.py is not vacuous.

The mutants that matter are the ones that break the safety model: operate
on a dirty tree, leave the patient on the table, hand the serum to a
patient nobody examined, or forget what the cut taught.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_operate.py"
_O = "ghost_buster/operate.py"

MUTANTS = [
    ("a dirty tree is operated on", _O,
     '    if not dry_run and _git(root, "status", "--porcelain"):',
     "    if False:"),
    ("the patient is left on the table", _O,
     '    if not dry_run:\n        _git(root, "checkout", "-q", return_to)',
     "    if False:\n        _git(root, \"checkout\", \"-q\", return_to)"),
    ("a detached patient is sent back to 'HEAD', which is the table", _O,
     "    return_to = came_in_on or head_before",
     '    return_to = came_in_on or "HEAD"'),
    ("findings the second look cannot see are counted as healed", _O,
     "        carried = [f for f in current if f.detector not in re_examines]",
     "        carried = []"),
    ("a dry run opens a branch anyway", _O,
     '    if not dry_run:\n        _git(root, "checkout", "-q", "-b", branch)',
     '    if True:\n        _git(root, "checkout", "-q", "-b", branch)'),
    ("a cut is not staged, so nothing is committed", _O,
     '        _git(root, "add", "-A")\n        _git(root, "commit", "-q", "-m",',
     '        pass\n        _git(root, "commit", "-q", "-m",'),
    ("what a cut healed is not learned", _O,
     "            for fid in closed:\n                casefile.record_outcome(by_id[fid], HEALED, f\"by {name}\")",
     "            for fid in []:\n                casefile.record_outcome(by_id[fid], HEALED, f\"by {name}\")"),
    ("what a cut exposed is not learned", _O,
     "            for fid in exposed:\n                casefile.record_outcome(by_id[fid], EXPOSED, f\"by {name}\")",
     "            for fid in []:\n                casefile.record_outcome(by_id[fid], EXPOSED, f\"by {name}\")"),
    ("the serum goes to a patient nobody examined", _O,
     "    if op.readiness_after.candidate:",
     "    if True:"),
    ("the untouched check compares nothing", _O,
     "        return self.head_after == self.head_before",
     "        return True"),
    ("healed and exposed are computed backwards", _O,
     "        closed = sorted(_ids(current) - _ids(after))\n        exposed = sorted(_ids(after) - _ids(current))",
     "        closed = sorted(_ids(after) - _ids(current))\n        exposed = sorted(_ids(current) - _ids(after))"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_operate_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_operate_tests_pass_unmutated():
    result = run_tests_with_mutation(TESTS, _O, "class Refused(Exception):", "class Refused(Exception):")
    assert result.returncode == 0, result.stdout[-2000:]
