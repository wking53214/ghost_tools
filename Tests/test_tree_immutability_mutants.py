"""The proof that Tests/test_tree_immutability.py is not vacuous.

Two kinds of mutant here, and the second kind is the point.

The first blunts the guard: a snapshot that forgets file contents, a compare
that cannot see a deletion, an allow-list that allows everything. Those show
the guard's own tests hold it to its job.

The second breaks REAL PRODUCT CODE in the exact way the guard exists to
catch -- annotating without the flag that asks for it, writing a proposal
beside the original instead of into the output directory, writing a recovery
into the scanned repository. If the suite did not fail on those, it would be
35 docstrings and one more file that agrees with them.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_tree_immutability.py"
_G = "Tests/tree_guard.py"
_BUSTER = "ghost_buster/cli.py"
# The gathering half of the CLI moved to pipeline.py in 1.6.0. The
# mutants below that point at it were re-aimed, not removed: the code
# they mutate is the same code, in its new module.
_PIPELINE = "ghost_buster/pipeline.py"
_RECONSTRUCT = "blackhole_extrapolator/reconstruct.py"
_RECOVER = "blackhole_extrapolator/recover.py"

MUTANTS = [
    # ---- the guard stops guarding
    ("the snapshot forgets what files contain", _G,
     '    return f"{mode:o}:{digest}"', '    return f"{mode:o}"'),
    ("a permission change stops counting", _G,
     "        mode = path.stat().st_mode & 0o777", "        mode = 0"),
    ("deletions are no longer noticed", _G,
     "    deleted = tuple(sorted(set(before.entries) - set(after.entries)))",
     "    deleted = ()"),
    ("modifications are no longer noticed", _G,
     "    modified = tuple(sorted(\n"
     "        path for path, entry in before.entries.items()\n"
     "        if path in after.entries and after.entries[path] != entry))",
     "    modified = ()"),
    ("every new file counts as declared", _G,
     "    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)",
     "    return True"),
    ("a declaration excuses touching what was there", _G,
     "    if changes.modified or changes.deleted or undeclared:",
     "    if undeclared:"),
    ("directories stop being recorded", _G,
     "        for name in list(directories) + files:", "        for name in files:"),
    ("nothing is ignored, so cache churn fails every scan", _G,
     'IGNORE = (".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")',
     "IGNORE = ()"),

    # ---- real product code breaks the real promise
    ("ghost_buster annotates without being asked", _PIPELINE,
     "    if args.annotate_names:", "    if True:"),
    ("a reconstruction is written beside the original", _RECONSTRUCT,
     '    target = into / (path.stem + ".reconstructed.py")',
     '    target = path.parent / (path.stem + ".reconstructed.py")'),
    ("a recovery is written into the scanned repository", _RECOVER,
     "    target = into / recovered_name(recovery.path, root)",
     "    target = Path(recovery.path).parent / recovered_name(recovery.path, root)"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_tree_immutability_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_tree_immutability_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _G, "IGNORE = (", "IGNORE = (")
    assert result.returncode == 0, result.stdout[-2000:]
