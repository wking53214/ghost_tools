"""The proof that Tests/test_boundary.py is not vacuous.

The whole point of this check is that it sees what neither repository's
CI can, so the mutants that matter make it BLIND again -- stop treating a
guarded import as a boundary, resolve a submodule import against the
whole package, forget that a constant is an export, count a dormant test
as no coverage at all. Each of those returns the seam to the state it was
in before the module existed, which is unverified and silent about it.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

BOUNDARY_TESTS = "Tests/test_boundary.py"
_B = "ghost_buster/boundary.py"
_S = "ghost_buster/structure.py"
_C = "ghost_buster/cli.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    # --- it goes blind ---
    ("a guarded import is no longer treated as a declared boundary", _B,
     "        if not catches_import:\n            continue\n",
     "        if True:\n            continue\n"),
    ("an unresolved cross-repo symbol is not reported", _B,
     "        missing = [n for n in reach.names if n not in exported]\n",
     "        missing = []\n"),
    ("a symbol no test mentions is not reported", _B,
     "        untested = [n for n in reach.names if n and not "
     "re.search(rf\"\\b{re.escape(n)}\\b\", corpus)]\n",
     "        untested = []\n"),
    ("a provider missing from the join is not reported", _B,
     "        if provider is None:\n", "        if False:\n"),
    ("dormant tests are not inventoried, so nothing can age them", _B,
     "    for dormant in joined.dormant_tests:\n", "    for dormant in []:\n"),
    ("only bare ImportError counts, so ModuleNotFoundError guards are missed", _B,
     '        if name in ("ImportError", "ModuleNotFoundError", "Exception", "BaseException"):\n',
     '        if name == "ImportError":\n'),

    # --- it resolves the wrong thing ---
    ("a submodule import is resolved against the whole package", _B,
     "        if reach.source and reach.source != reach.package:\n",
     "        if False:\n"),
    ("a module-level constant stops counting as an export", _S,
     '                    if not t.id.startswith("_"):\n'
     "                        facts.bindings.append(t.id)\n", ""),
    # The line moved into _surface() when re-export collection was added on
    # 2026-09-10; the property it protects is unchanged.
    ("bindings are dropped when computing what a package provides", _B,
     "        return set(m.exported) | set(m.public_names) | set(m.bindings) | set(m.reexports)\n",
     "        return set(m.exported) | set(m.public_names) | set(m.reexports)\n"),
    ("a repository reaching for itself is treated as a boundary", _B,
     "        if provider_root == reach.repo:\n            continue    # reaching for itself; not a boundary\n",
     ""),

    # --- it gets loud ---
    ("every skip counts as a dormant boundary, not only the ones waiting on a checkout", _B,
     "        if reason and _DORMANT_REASON.search(reason):\n",
     "        if reason:\n"),
    ("an unresolved symbol is downgraded from CRITICAL", _B,
     '                "cross repo import unresolved", Severity.CRITICAL, file,\n',
     '                "cross repo import unresolved", Severity.MINOR, file,\n'),
    ("an untested boundary symbol is downgraded to a nit", _B,
     '                "boundary symbol untested", Severity.MAJOR, file,\n',
     '                "boundary symbol untested", Severity.INFORMATIONAL, file,\n'),
    ("dormant tests are inflated to MAJOR, so writing one is punished", _B,
     '            "dormant boundary test", Severity.INFORMATIONAL, file,\n',
     '            "dormant boundary test", Severity.MAJOR, file,\n'),
    ("test files stop counting as coverage, so every crossing reads as untested", _B,
     '            if not (name.startswith("test_") or name.endswith("_test.py")\n'
     '                    or "tests" in p.parts or "test" in p.parts):\n'
     "                continue\n", ""),

    ("a guarded stdlib import counts as a cross-repo boundary", _B,
     "    return package.split(\".\", 1)[0] in _stdlib_names()\n", "    return False\n"),
    ("the single-repo notice stops filtering stdlib", _B,
     "        reaches.extend(f for f in found\n"
     "                       if f.package not in model.packages and not _is_stdlib(f.package))\n",
     "        reaches.extend(f for f in found if f.package not in model.packages)\n"),

    # --- mode handling ---
    ("a non-interactive run prompts anyway and hangs the build", _C,
     "    if args.single_repo or not sys.stdin.isatty():\n        return []\n",
     "    if args.single_repo:\n        return []\n"),
    ("--single-repo is ignored", _C,
     "    if args.single_repo or not sys.stdin.isatty():\n",
     "    if not sys.stdin.isatty():\n"),
    ("--join is ignored and every run is single-repo", _C,
     "    if args.join:\n        return list(args.join)\n", ""),
    ("a single-repo run stops saying its seams went unchecked", _C,
     "        notice = render_single_repo_notice(args.path, files)\n"
     "        if notice:\n            print(notice, file=sys.stderr)\n",
     "        notice = None\n        if notice:\n            print(notice, file=sys.stderr)\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_boundary_mutant_is_killed(label, rel, old, new):
    assert_killed(label, BOUNDARY_TESTS, run_tests_with_mutation(BOUNDARY_TESTS, rel, old, new))


def test_boundary_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        BOUNDARY_TESTS, _B, 'DETECTOR = "boundary"\n', 'DETECTOR = "boundary"\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
