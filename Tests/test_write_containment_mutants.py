"""The proof that the containment suite is not vacuous.

Three guards were added in 1.7.1 and each one exists because an adversarial
harness got past its absence. A guard with no mutant behind it is a guard
nobody has shown to be load-bearing, and this file is the showing.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

_ANNOTATE = "ghost_buster/annotate.py"
_PIPELINE = "ghost_buster/pipeline.py"

TESTS = "Tests/test_write_containment.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)

    # The severe one. A README that is a symlink out of the repository, and
    # a write that follows it -- outside the branch the operation opened, so
    # outside anything it can revert.
    ("the README is written wherever it resolves to", _ANNOTATE,
     "    if refuses(path, root) is not None:\n        return False\n",
     ""),
    ("source notes are written wherever they resolve to", _ANNOTATE,
     "        if refuses(path, root) is not None:\n            continue\n",
     ""),
    ("containment is computed and then ignored", _ANNOTATE,
     "        target = Path(path).resolve()\n        target.relative_to(Path(root).resolve())\n",
     "        target = Path(path).resolve()\n"),

    # Markup nobody asked for. The count-block remedy states the principle
    # and this module was breaking it, with a table reading `_none_`.
    ("a section recording nothing is appended anyway", _ANNOTATE,
     "    elif not disagreements:\n        return False\n",
     ""),

    # A finding has to name the path whose history will show the change.
    ("the link is reported instead of the file it points at", _PIPELINE,
     "            if out[already].is_symlink() and not p.is_symlink():\n                out[already] = p\n",
     ""),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))
