"""The proof that Tests/test_boundary_reexport.py is not vacuous.

Each mutant restores one of the two bugs that were live on 2026-09-10,
when joining two real repositories produced two CRITICAL findings against
imports that run fine. Both were already half-known -- the boundary check
carried a written "scope limit" admitting it could not follow a re-export
-- and a caveat in the detail text does not stop a critical from costing
someone a morning.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_boundary_reexport.py"
_B = "ghost_buster/boundary.py"
_S = "ghost_buster/structure.py"

MUTANTS = [
    # --- the src-layout bug: the repository provided nothing at all ---
    ("layout directories are no longer stripped from a module name", _B,
     "        while parts and parts[0] in _PACKAGE_PARENTS:\n            parts.pop(0)\n",
     "        while False:\n            parts.pop(0)\n"),

    # --- the re-export bug ---
    ("a name bound by an import stops counting as provided", _B,
     "        return set(m.exported) | set(m.public_names) | set(m.bindings) | set(m.reexports)\n",
     "        return set(m.exported) | set(m.public_names) | set(m.bindings)\n"),
    ("import bindings are never collected in the first place", _S,
     "                bound = alias.asname or alias.name.split(\".\", 1)[0]\n",
     "                bound = \"_skip\"\n"),
    ("a star-import target is not resolved against the joined set", _B,
     "                    resolved = by_tail.get(target) or by_tail.get(target.split(\".\")[-1])\n",
     "                    resolved = None\n"),

    # --- the abstention must not become a blanket excuse ---
    ("every module is treated as opaque, so nothing is ever reported", _B,
     "        if reach.source in joined.opaque_modules or reach.package in joined.opaque_modules:\n",
     "        if True:\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_reexport_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_the_suite_passes_unmutated():
    result = run_tests_with_mutation(
        TESTS, _B, "    opaque: Set[str] = set()\n", "    opaque: Set[str] = set()\n")
    assert result.returncode == 0, result.stdout[-2000:]
