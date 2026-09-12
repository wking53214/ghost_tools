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
    ("the door counts the tool's own ledger as the patient's dirt", _OP,
     '        if code == "??" and path in SURGEONS_NOTES:\n            continue\n',
     ""),
    ("the cut sweeps the surgeon's notes into the patient's history", _OP,
     '        _git(root, "add", "-A", "--", ".", *(f":(exclude){note_file}" for note_file in SURGEONS_NOTES))',
     '        _git(root, "add", "-A")'),
    ("only the ledger is recognised as a note", _OP,
     'SURGEONS_NOTES = (".ghost_ledger.json", ".ghost_baseline.json", ".ghost_casefile.json")',
     'SURGEONS_NOTES = (".ghost_ledger.json",)'),
    ("a tracked note that changed is waved through too", _OP,
     '        if code == "??" and path in SURGEONS_NOTES:',
     "        if path in SURGEONS_NOTES:"),
    ("the door stops looking at the tree at all", _OP,
     "        dirt = _dirty_paths(root)\n",
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
