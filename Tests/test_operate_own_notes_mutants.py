"""The proof that the surgeon's-notes suite is not vacuous.

The first two mutants restore the defect exactly: the door counting the
tool's own ledger as the patient's dirt, and the cut sweeping it into the
patient's history. Both were live in 1.6.0 and were found by putting a
real repository on the table, not by this suite, which is why the suite
now exists.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

_OP = "ghost_buster/operate.py"

NOTES = "Tests/test_operate_own_notes.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)
    # Re-pointed in 1.7.3: the exclusion learned to ask whose edit it is.
    ("the door counts the tool's own ledger as the patient's dirt", _OP,
     '        if path in SURGEONS_NOTES:\n'
     '            if code == "??":\n'
     '                continue\n'
     '            if _was_clean_on_arrival(root, path, arrival):\n'
     '                continue\n',
     ""),
    # v1.7.3. Without this, a committed note counts as dirt however it got
    # that way, and the tool refuses every repository that keeps the record
    # it tells people to keep.
    ("a committed note this run wrote is still counted as the patient's", _OP,
     "            if _was_clean_on_arrival(root, path, arrival):",
     "            if False:"),
    # The other side. Without it, anything a repository committed can be
    # overwritten by the workup and nothing stops the operation.
    ("somebody's real edit to a committed note is treated as ours", _OP,
     "            if _was_clean_on_arrival(root, path, arrival):",
     "            if True:"),
    ("the snapshot is never taken, so nothing can be told apart", _OP,
     "    arrival = dict(arrival or {})",
     "    arrival = {}"),
    ("the cut sweeps the surgeon's notes into the patient's history", _OP,
     '        _git(root, "add", "-A", "--", ".", *(f":(exclude){note_file}" for note_file in SURGEONS_NOTES))',
     '        _git(root, "add", "-A")'),
    ("only the ledger is recognised as a note", _OP,
     'SURGEONS_NOTES = (".ghost_ledger.json", ".ghost_baseline.json", ".ghost_casefile.json")',
     'SURGEONS_NOTES = (".ghost_ledger.json",)'),
    # "a tracked note that changed is waved through too" lived here until
    # 1.7.3. Its claim is unchanged and is now made by "somebody's real edit
    # to a committed note is treated as ours" above, which points at the
    # guard that decides it. Two names for one mutation would report the
    # suite as proving one more thing than it does.
    ("the door stops looking at the tree at all", _OP,
     "        dirt = _dirty_paths(root, arrival)\n",
     "        dirt = []\n"),
    ("porcelain is parsed by column again", _OP,
     "        parts = line.split(None, 1)",
     "        parts = [line[:2], line[3:]] if len(line) > 3 else []"),
    ("the dry run goes back to claiming it wrote nothing", _OP,
     '("  (dry run: no cut written)" if self.dry_run else "")',
     '("  (dry run: nothing written)" if self.dry_run else "")'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, NOTES, run_tests_with_mutation(NOTES, rel, old, new))


def test_the_suite_passes_unmutated():
    anchor = "def _dirty_paths("
    result = run_tests_with_mutation(NOTES, _OP, anchor, anchor)
    assert result.returncode == 0, result.stdout[-1500:]
