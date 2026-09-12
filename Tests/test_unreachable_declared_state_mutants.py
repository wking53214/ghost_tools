"""The proof that Tests/test_unreachable_declared_state.py is not vacuous.

Two directions, and this detector fails in both: missing a state nothing
produces, and flagging an enum that is simply reconstructed from data. The
second would make the detector unusable rather than merely incomplete, so it
has as many mutants as the first.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

DOCS = "Tests/test_unreachable_declared_state.py"
_M = "ghost_buster/mechanical.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)
    # --- missing the state ---
    ("a comparison counts as producing the value", _M,
     "            if isinstance(node, ast.Attribute) and id(node) not in compared:",
     "            if isinstance(node, ast.Attribute):"),
    ("nothing is ever collected as produced", _M,
     "    produced = _members_produced(parsed)",
     "    produced = set(m for members in declared.values() for m in members)"),
    # A "lower-case attributes count as states" mutant lived here and was
    # unkillable: `declared` only ever holds upper-case names, so a
    # lower-case attribute in `produced` can never match one. The filter was
    # a micro-optimisation wearing a guard's clothes and is gone. The
    # DECLARED side's filter is load-bearing and is tested directly.
    # --- the lookup-table blind spot (1.7.6) ---
    ("a lookup table counts as producing every member it names", _M,
     "        for node in tree.body:\n"
     "            if not isinstance(node, ast.Assign):\n"
     "                continue\n",
     "        for node in []:\n"
     "            if not isinstance(node, ast.Assign):\n"
     "                continue\n"),
    ("every constant is treated as a table, so a default is not a production", _M,
     "            if not _is_collection(node.value):\n                continue\n",
     ""),
    ("a local collection counts as a table", _M,
     "        for node in tree.body:\n"
     "            if not isinstance(node, ast.Assign):\n"
     "                continue\n"
     "            if not any(isinstance(target, ast.Name) and target.id.isupper()",
     "        for node in ast.walk(tree):\n"
     "            if not isinstance(node, ast.Assign):\n"
     "                continue\n"
     "            if not any(isinstance(target, ast.Name) and target.id.isupper()"),
    ("lower-case module names count as constant tables", _M,
     "            if not any(isinstance(target, ast.Name) and target.id.isupper()\n"
     "                       for target in node.targets):\n"
     "                continue\n",
     ""),
    ("a frozenset() wrapper hides the table", _M,
     '        if name in ("frozenset", "set", "tuple", "list"):',
     '        if name in ("nothing_at_all",):'),
    # --- flagging what is fine ---
    ("an enum nobody names is reported member by member", _M,
     "        if not live:\n            continue",
     ""),
    ("every class counts as an enum", _M,
     "            if not (bases & _ENUM_BASES):\n                continue",
     ""),
    ("ordinary class attributes count as members", _M,
     "                    if isinstance(target, ast.Name) and target.id.isupper():",
     "                    if isinstance(target, ast.Name):"),
    # --- what the finding says ---
    ("the finding stops saying it is not a reachability claim", _M,
     '                    "It does not claim the state is unreachable. A value read "',
     '                    "This state is unreachable. A value read "'),
    # Not "substitute an empty tree": an empty tree contributes nothing, so
    # that mutant was behaviourally identical to skipping and survived. What
    # the guard actually buys is not walking None.
    ("an unparseable file is walked instead of skipped", _M,
     "        if tree is not None:\n            parsed[path] = tree",
     "        parsed[path] = tree"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, DOCS, run_tests_with_mutation(DOCS, rel, old, new))


def test_the_suite_passes_unmutated():
    anchor = "_ENUM_BASES = frozenset"
    result = run_tests_with_mutation(DOCS, _M, anchor, anchor)
    assert result.returncode == 0, result.stdout[-1500:]
