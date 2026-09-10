"""The proof that Tests/test_copies.py is not vacuous.

The mutants that matter here loosen what counts as "the same file" or as
"drift". Either direction ruins it: too loose and unrelated modules sharing
three helper names become a finding, too strict and reformatting reads as a
behavioural change.

TWO MUTANTS WERE WRITTEN AND REMOVED, because neither can be distinguished
and a mutant that cannot fail is not evidence of anything. `if len(members)
< 2: continue` is an early-out that the byte-identical check would catch
anyway, since one file's digests are always one digest. `_definitions`
returning `{}` instead of `None` on a parse failure is caught by the
MINIMUM_DEFINITIONS floor, since zero is below three. Both guards are worth
keeping for clarity and cost; neither is load-bearing on its own.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_copies.py"
_C = "ghost_buster/copies.py"

MUTANTS = [
    # duplicate_file's finding stays duplicate_file's.
    ("byte-identical copies are reported here too", _C,
     "        if len(digests) == 1:\n            continue",
     "        if False:\n            continue"),

    # What counts as the same file.
    ("three shared names stop being the minimum", _C,
     "MINIMUM_DEFINITIONS = 3", "MINIMUM_DEFINITIONS = 1"),

    # What counts as drift. Both directions are wrong.
    ("reformatting counts as a behavioural change", _C,
     "        ast.dump(node, annotate_fields=True, include_attributes=False).encode()",
     "        ast.dump(node, annotate_fields=True, include_attributes=True).encode()"),
    ("nothing ever counts as drift", _C,
     "        differing = sorted(\n"
     "            name for name in names\n"
     "            if len({definitions[name] for _, definitions in members}) > 1)",
     "        differing = []"),

    # The split that decides how loudly it speaks.
    ("a drifted copy is rated no worse than a tidy one", _C,
     "            severity=Severity.MAJOR if drifted else Severity.MINOR,",
     "            severity=Severity.MINOR,"),
    ("drift stops being parallel implementation", _C,
     "            category=(Category.PARALLEL_IMPLEMENTATION if drifted\n"
     "                      else Category.DUPLICATION),",
     "            category=Category.DUPLICATION,"),

    # The finding has to say WHICH definitions stopped matching.
    ("the differing names are no longer named", _C,
     '        shown = ", ".join(f"`{n}`" for n in group.differing[:SHOWN])',
     '        shown = ""'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_copies_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_copies_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _C, "MINIMUM_DEFINITIONS = 3",
                                     "MINIMUM_DEFINITIONS = 3")
    assert result.returncode == 0, result.stdout[-2000:]
