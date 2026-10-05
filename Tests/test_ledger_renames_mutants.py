"""The proof that Tests/test_ledger_renames.py is not vacuous.

Following a rename is a memory deciding that two ids are one finding, so
the failures that matter are both directions of that decision: refusing a
move that happened, and inventing a continuity nobody observed. Every
mutant below is one of the two.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

DOCS = "Tests/test_ledger_renames.py"
_L = "ghost_buster/ledger.py"

# One mutant is deliberately absent. Deleting the `out.returncode != 0`
# early-out is behaviourally equivalent under every git output that can be
# produced here: git writes its errors to stderr, so a failed call leaves
# stdout empty and the parser returns nothing either way. The guard stays --
# a non-zero exit after partial output would otherwise be parsed as fact --
# and it is recorded here as unproven rather than left looking proven.
MUTANTS = [
    # (label, file, exact text to replace, replacement)
    # --- refusing a move that happened ---
    ("renames are never followed at all", _L,
     "        self._follow_renames(findings, seen_now, commit, root)\n",
     ""),
    # Not "remove -M": git detects renames by default, so removing it
    # changes nothing under a default config and the mutant survived. What
    # -M actually buys is immunity to a user who set `diff.renames=false`,
    # and this is that user.
    ("renames are turned off, as a user's own config may have done", _L,
     '"diff", "--name-status", "-M",',
     '"diff", "--name-status", "--no-renames",'),
    ("only a lone candidate is ever carried, so a module with two "
     "findings in it never moves", _L,
     "            named = [f for f in candidates if f.summary == hist.summary]\n"
     "            if len(named) == 1:\n"
     "                new_id = named[0].id\n"
     "            elif len(candidates) == 1:\n",
     "            named = []\n"
     "            if False:\n"
     "                new_id = named[0].id\n"
     "            elif len(candidates) == 1:\n"),
    # --- inventing a continuity nobody observed ---
    ("any file counts as renamed, whatever git said", _L,
     '        if len(parts) == 3 and parts[0].startswith("R"):',
     "        if len(parts) == 3:"),
    ("an existing history at the new id is clobbered", _L,
     "            if new_id == fid or new_id in self.findings:",
     "            if new_id == fid:"),
    ("several indistinguishable candidates are carried onto the first", _L,
     "            elif len(candidates) == 1:\n"
     "                new_id = candidates[0].id\n"
     "            else:\n"
     "                continue",
     "            else:\n"
     "                new_id = candidates[0].id"),
    ("a different detector at the new path counts as the same finding", _L,
     "            candidates = here.get((hist.detector, destination), [])",
     "            candidates = [f for d, p in here for f in here[(d, p)]\n"
     "                          if p == destination]"),
    ("a finding that really went away is carried onto something", _L,
     "            destination = moved.get(hist.file)\n"
     "            if destination is None:\n"
     "                continue\n",
     "            destination = moved.get(hist.file, hist.file)\n"),
    # --- the refusals that keep it best-effort ---
    ("the first run compares against nothing and proceeds", _L,
     "        if root is None or not previous or not commit:",
     "        if False:"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, DOCS, run_tests_with_mutation(DOCS, rel, old, new))


def test_the_suite_passes_unmutated():
    anchor = "    def _follow_renames(self, findings: Sequence[Finding], seen_now: set,"
    result = run_tests_with_mutation(DOCS, _L, anchor, anchor)
    assert result.returncode == 0, result.stdout[-1500:]
