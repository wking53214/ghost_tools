"""The proof that Tests/test_speed.py is not vacuous.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_speed.py"
_S = "ghost_buster/speed.py"

MUTANTS = [
    ("a memo behind a None check is reported as a pitstop", _S,
     "                            and id(node) not in memo\n",
     "                            and True\n"),
    ("a container filled every pass is reported as invariant (cns_map's defaultdict again)", _S,
     "                            and id(node) not in filled\n",
     "                            and True\n"),
    ("filling through a subscript store does not count", _S,
     "            elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, ast.Store):\n"
     "                target = node\n",
     "            elif False:\n                target = node\n"),
    ("side effects in the loop are ignored (operate.py's rescan is 'invariant' again)", _S,
     "                            and not _may_change(parts, node)):\n",
     "                            and True):\n"),
    ("a method call on the argument is not a change", _S,
     "                if (isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name)\n"
     "                        and callee.value.id in args):\n                    return True\n",
     "                if False:\n                    return True\n"),
    ("a store into the argument is not a change", _S,
     "                if isinstance(base, ast.Name) and base.id in args:\n                    return True\n",
     "                if False:\n                    return True\n"),
    ("a tiny constant is reported like a long list", _S,
     "                            and lists.get(node.comparators[0].id, 0) > _SMALL_LITERAL):\n",
     "                            and node.comparators[0].id in lists):\n"),
    ("a set literal counts as a list", _S,
     "        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple)):",
     "        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):"),
    ("a call that uses the loop variable is reported anyway", _S,
     "                            and not (_names(node) & variant)\n",
     "                            and True\n"),
    ("a name bound inside the loop body counts as invariant", _S,
     "        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):\n            out.add(n.id)",
     "        if False:\n            out.add(n.id)"),
    ("constant-time builtins are reported as pitstops", _S,
     "                            and node.func.id not in _CHEAP",
     "                            and True"),
    ("the loop requirement is dropped", _S,
     "            if not isinstance(loop, _LOOPS):\n                continue",
     "            if False:\n                continue"),
    ("tests are scanned", _S,
     "        if is_test_path(path):\n            continue\n        tree = corpus.parse(path)",
     "        if False:\n            continue\n        tree = corpus.parse(path)"),
    ("a pitstop is rated above MINOR", _S,
     "            severity=Severity.MINOR,\n            status=Status.CONFIRMED,\n            summary=f\"{p.path.name}:{p.line} {p.what} inside a loop\",",
     "            severity=Severity.MAJOR,\n            status=Status.CONFIRMED,\n            summary=f\"{p.path.name}:{p.line} {p.what} inside a loop\","),
    ("repeated work is counted as distinct", _S,
     "                prof.calls[\"ast.parse\"][hash(key)] += 1",
     "                prof.calls[\"ast.parse\"][id(object())] += 1"),
    ("the profiler leaves ast.parse wrapped", _S,
     "        for obj, name, original in self._saved:\n            setattr(obj, name, original)",
     "        pass"),
    ("nothing-twice is claimed when something was", _S,
     "        if all(r.repeated == 0 for r in self.redundancies()):",
     "        if True:"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_speed_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_speed_tests_pass_unmutated():
    result = run_tests_with_mutation(TESTS, _S, 'LIST_IN_LOOP = "list_membership_in_loop"', 'LIST_IN_LOOP = "list_membership_in_loop"')
    assert result.returncode == 0, result.stdout[-2000:]
