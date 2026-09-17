"""The proof that the marked-block suite is not vacuous.

The first mutant is the one that matters: a tool that writes its own
markers into a repository that never handed anything over.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

_OP = "ghost_buster/operate.py"

BLOCK = "Tests/test_remedy_count_block.py"

MUTANTS = [
    ("the tool writes into a document that has no block", _OP,
     "        if match is None:\n            continue\n",
     "        if match is None:\n            text = text + COUNT_BLOCK_OPEN + '\\n\\n' "
     "+ COUNT_BLOCK_CLOSE + '\\n'\n            path.write_text(text, encoding='utf-8')\n"
     "            match = _COUNT_BLOCK.search(text)\n"),
    ("a suite that is not green still supplies a number", _OP,
     '                     and f.attributes.get("collected") == f.attributes.get("passed")),',
     "                     ),"),
    # v1.7.1: there used to be two guards here -- an explicit "the digits
    # already read the measured number" test and this one. With the body no
    # longer replaced whole they became exactly redundant, neither could be
    # made to fail alone, and one of them was decoration. The explicit one
    # went; this is the survivor and it is load-bearing.
    ("a block already current is rewritten and counted as a cut", _OP,
     "        if meant == text:\n            continue          # already current; not a cut\n",
     ""),
    ("only the first block in the tree is maintained", _OP,
     "        changed += 1\n\n    if not changed:\n        return 0, \"\"\n    note = (f\"{changed} maintained",
     "        changed += 1\n        break\n\n    if not changed:\n        return 0, \"\"\n    note = (f\"{changed} maintained"),
    ("the number is never checked after writing", _OP,
     "        if again is None or measured not in again.group(1):",
     "        if False:"),
    # v1.7.1: the block body is no longer replaced whole, so the guard that
    # matters is the one around THE DIGITS. The old check -- bytes outside
    # the block -- could not fail for the defect that mattered, because the
    # loss was inside it.
    ("the document outside the count is allowed to move", _OP,
     "        elif written[:start] != text[:start] or \\\n"
     "                written[start + len(measured):] != text[end:]:",
     "        elif False:"),
    ("a dated document has its count maintained anyway", _OP,
     "        if _DATED_DOCUMENT.search(path.name):",
     "        if False:"),
    ("prose in the block is replaced instead of left alone", _OP,
     "            if body.strip():",
     "            if False:"),
    ("a block with two counts is written into anyway", _OP,
     "        elif len(claims) > 1:",
     "        elif False:"),
    ("a run that measured nothing still writes", _OP,
     "    if not measured:\n        return 0, \"\"\n",
     "    measured = measured or \"0\"\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, BLOCK, run_tests_with_mutation(BLOCK, rel, old, new))


def test_the_suite_passes_unmutated():
    anchor = "def _remedy_count_block("
    result = run_tests_with_mutation(BLOCK, _OP, anchor, anchor)
    assert result.returncode == 0, result.stdout[-1500:]
