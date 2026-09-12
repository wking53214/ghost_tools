"""Shared harness for the hand-mutant suites (test_gate_mutants.py,
test_polish_mutants.py): copy the project to a scratch directory, apply one
exact-text mutation, run one test file there, return the result.

ghost_buster --mutate finds its candidates by shape (weak assertions, unread
results, guarded assertions, restated sets). A well-shaped test is never a
candidate, so the tool cannot vouch for it; these suites are the hand-made
complement for the pieces of logic whose failure mode is "passes
everything". The working tree is never modified.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv")


def run_tests_with_mutation(
    test_file: str, rel: str, old: str, new: str,
) -> subprocess.CompletedProcess:
    """Run `test_file` in a scratch copy of the project where the single
    occurrence of `old` in `rel` has been replaced by `new`."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = pathlib.Path(tmp) / "ghost_tools"
        shutil.copytree(ROOT, copy, ignore=_IGNORE)
        target = copy / rel
        source = target.read_text()
        assert source.count(old) == 1, f"mutation site not found exactly once in {rel}: {old!r}"
        target.write_text(source.replace(old, new))
        return subprocess.run(
            # `-n0` because pyproject sets `addopts = "-n auto"` for the outer
            # suite, and a copied tree carries that pyproject with it. Without
            # this every one of the 634 mutants spins up its own worker pool to
            # run a single test file -- measured 2026-09-10, 0.45s per mutant
            # became 0.98s, and the parallelism that was supposed to make the
            # suite faster made each mutant slower. Parallelism belongs at the
            # outer level, where there are 584 independent jobs to spread.
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "-n0", test_file],
            cwd=copy, capture_output=True, text=True, timeout=120,
        )


def assert_killed(label: str, test_file: str, result: subprocess.CompletedProcess) -> None:
    assert result.returncode != 0, (
        f"mutant survived: {label}\nevery test in {test_file} passed with the code broken\n"
        + result.stdout[-2000:]
    )
    assert "failed" in result.stdout or "error" in result.stdout, result.stdout[-2000:]
