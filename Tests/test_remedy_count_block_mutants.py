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
    ("a block already current is rewritten and counted as a cut", _OP,
     "        if match.group(1) == body:\n            continue          # already current; not a cut\n",
     ""),
    ("only the first block in the tree is maintained", _OP,
     "        changed += 1\n\n    if not changed:\n        return 0, \"\"\n    return changed, (f\"{changed} maintained",
     "        changed += 1\n        break\n\n    if not changed:\n        return 0, \"\"\n    return changed, (f\"{changed} maintained"),
    ("the number is never checked after writing", _OP,
     "        if again is None or measured not in again.group(1):",
     "        if False:"),
    ("the document outside the block is allowed to move", _OP,
     "        if written[:again.start(1)] != text[:match.start(1)] or \\\n"
     "                written[again.end(1):] != text[match.end(1):]:",
     "        if False:"),
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
