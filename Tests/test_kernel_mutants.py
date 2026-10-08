"""The proof that Tests/test_kernel.py is not vacuous. The working tree is
never modified."""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

KERNEL_TESTS = "Tests/test_kernel.py"
_K = "ghost_buster/kernel.py"
_C = "ghost_buster/cli.py"
# The gathering half of the CLI moved to pipeline.py in 1.6.0. The
# mutants below that point at it were re-aimed, not removed: the code
# they mutate is the same code, in its new module.
_P = "ghost_buster/pipeline.py"

MUTANTS = [
    ("a docstring counts as a change, so every documented copy reads as drifted", _K,
     "        ast.dump(_strip_docstrings(node), annotate_fields=True, include_attributes=False).encode()\n",
     "        ast.dump(node, annotate_fields=True, include_attributes=False).encode()\n"),
    ("the overlap gate is removed, so every same-name class is a drifted contract", _K,
     "            if against and shared / len(against) >= SHARED_MEMBERS:\n",
     "            if against:\n"),
    ("the gate is inverted", _K,
     "            if against and shared / len(against) >= SHARED_MEMBERS:\n",
     "            if against and shared / len(against) < SHARED_MEMBERS:\n"),
    ("class-level members are ignored, so a drifted enum is a coincidence", _K,
     "        elif isinstance(n, ast.Assign):\n            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}\n",
     "        elif False:\n            pass\n"),
    ("the kernel's own files are patients", _K,
     "        if _inside(path, roots):\n",
     "        if False:\n"),
    ("test files are scanned", _K,
     "        if is_test_path(path):\n            continue\n        if _inside(path, roots):\n",
     "        if _inside(path, roots):\n"),
    ("a name the kernel defines twice keeps its first shape", _K,
     "    return {name: found[0] for name, found in seen.items() if len(found) == 1}\n",
     "    return {name: found[0] for name, found in seen.items()}\n"),
    ("a missing kernel path runs anyway", _K,
     "    if missing:\n",
     "    if False:\n"),
    ("a shadow is downgraded", _K,
     "        severity=Severity.MAJOR,\n",
     "        severity=Severity.MINOR,\n"),
    ("the CLI never runs it", _P,
     "    if args.kernel:\n        kernel_findings, kernel_report = check_kernel(files, args.kernel)\n",
     "    if False:\n        kernel_findings, kernel_report = check_kernel(files, args.kernel)\n"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_kernel_mutant_is_killed(label, rel, old, new):
    assert_killed(label, KERNEL_TESTS, run_tests_with_mutation(KERNEL_TESTS, rel, old, new))


def test_kernel_tests_pass_unmutated():
    result = run_tests_with_mutation(KERNEL_TESTS, _K, 'KERNEL_SHADOW = "kernel_shadow"', 'KERNEL_SHADOW = "kernel_shadow"')
    assert result.returncode == 0, result.stdout[-2000:]
