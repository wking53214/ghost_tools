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
    # --- the __members__ data path (1.8.1) ---
    ("a `__members__.get` deserialiser goes invisible again", _M,
     '            elif (isinstance(node, ast.Call)\n                  and isinstance(node.func, ast.Attribute)\n                  and node.func.attr == "get"\n                  and members_mapping_of(node.func.value) is not None\n                  and node.args):\n                enum, arg = members_mapping_of(node.func.value), node.args[0]\n',
     ''),
    ("a `__members__[name]` deserialiser goes invisible again", _M,
     '            elif (isinstance(node, ast.Subscript)\n                  and members_mapping_of(node.value) is not None):\n                enum, arg = members_mapping_of(node.value), node.slice\n',
     ''),
    ("any attribute named __members__ answers for any enum", _M,
     '        if (isinstance(node, ast.Attribute) and node.attr == "__members__"\n                and isinstance(node.value, ast.Name)\n                and node.value.id in declared):\n            return node.value.id\n',
     '        if isinstance(node, ast.Attribute) and node.attr == "__members__":\n            return next(iter(declared), None)\n'),
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
    # --- a test production is not a production (1.7.7) ---
    ("a test producing the state hides it entirely", _M,
     "    in_library = _members_produced(library)",
     "    in_library = _members_produced(parsed)"),
    ("test files are not recognised, so every file counts as library", _M,
     "               if not _looks_like_a_test(path)}",
     "               if True}"),
    ("the finding stops saying the production was a test", _M,
     '                     if only_tests else "no code ever puts anything into it")',
     '                     if False else "no code ever puts anything into it")'),
    # --- evidence that costs nothing does not buy a lower severity (1.7.8) ---
    #
    # The mutant IS version 1.7.7. It reported a test-only state at
    # INFORMATIONAL on the reasoning that somebody constructing the state
    # deliberately is weak evidence it was meant to be unreachable. A test
    # file is the cheapest artifact anyone can add to a repository, so that
    # graded willingness to type and handed an adversary a free way to quiet
    # this detector.
    ("a test producing the state buys a lower severity, as in 1.7.7", _M,
     "                severity=_HISTORY_SEVERITY[provenance],",
     "                severity=(Severity.INFORMATIONAL if only_tests\n"
     "                          else _HISTORY_SEVERITY[provenance]),"),
    # "history does not change the severity at all" lives in
    # test_forensics_mutants.py: every fixture here runs in a temporary
    # directory that is not a repository, so provenance is UNKNOWN and the
    # escalation has nothing to show. A mutant belongs with the suite that
    # can kill it, not with the suite it was written next to.
    # --- structural reachability (1.7.8) ---
    ("building the enum from a value is not noticed", _M,
     "            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)\n"
     "                    and node.func.id in declared and node.args):\n"
     "                enum, arg = node.func.id, node.args[0]",
     "            if False:\n"
     "                enum, arg = None, None"),
    ("a non-literal argument names one member instead of any", _M,
     "            else:\n                out[enum] |= set(declared[enum])",
     "            else:\n                pass"),
    ("a literal argument is treated as a blanket data path", _M,
     "            if isinstance(arg, ast.Constant):",
     "            if False:"),
    ("a reachable member is reported as unreachable anyway", _M,
     "            if reachable and not claims:",
     "            if False:"),
    ("a data path written in a test counts as a data path", _M,
     "    from_data = _reachable_from_data(library, declared)",
     "    from_data = _reachable_from_data(parsed, declared)"),
    # --- declared intent, checked rather than believed (1.7.8) ---
    ("a documented data path is reported anyway", _M,
     "            if reachable and claims:\n                continue",
     "            if False:\n                continue"),
    ("a claim the code does not back is quieted instead of escalated", _M,
     "                    severity=Severity.CRITICAL,",
     "                    severity=Severity.INFORMATIONAL,"),
    ("a bare claim suppresses the finding", _M,
     "            if claims:\n"
     "                # A claim the code does not back. Worse than saying nothing,",
     "            if claims:\n"
     "                continue\n"
     "                # A claim the code does not back. Worse than saying nothing,"),
    ("a member name is matched inside a longer member name", _M,
     '                 if re.search(r"\\b" + re.escape(m) + r"\\b", line)}',
     '                 if re.search(re.escape(m), line)}'),
    ("a blanket claim is ignored", _M,
     "        elif _BLANKET_MEMBER.search(line):",
     "        elif False:"),
    ("any line at all counts as a claim", _M,
     "        if not _CLAIMS_FROM_DATA.search(line):\n            continue",
     ""),
    ("a state arriving only from data is filed as informational", _M,
     "                    severity=Severity.MINOR,\n"
     "                    status=Status.CONFIRMED,\n"
     "                    summary=(f\"'{enum}.{member}' is produced only by reading \"",
     "                    severity=Severity.INFORMATIONAL,\n"
     "                    status=Status.CONFIRMED,\n"
     "                    summary=(f\"'{enum}.{member}' is produced only by reading \""),
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
     '                    + "It does not claim the state is unreachable. What is "',
     '                    + "This state is unreachable. What is "'),
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
