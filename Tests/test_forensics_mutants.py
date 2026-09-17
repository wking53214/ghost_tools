"""The proof that Tests/test_forensics.py is not vacuous.

The failure mode this guards against is specific and tempting. Every
question here can be answered "NEVER_PRODUCED" and most of the time that
will look right, because most unproduced members really were never
produced. A history layer that quietly degrades to its most common answer
whenever it cannot read the history would pass a suite that only ever
checked the common case, and would be worse than not having one: it would
report the end of its own search as the end of the repository's history.

So the mutants here are mostly collapses. Each one turns a distinction the
module makes into the answer it would have given anyway.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

DOCS = "Tests/test_forensics.py"
_F = "ghost_buster/forensics.py"
_M = "ghost_buster/mechanical.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)
    # --- not knowing, collapsed into knowing ---
    ("unreadable history is reported as never produced", _F,
     "    if log is None:\n        return Provenance.UNKNOWN",
     "    if log is None:\n        return Provenance.NEVER_PRODUCED"),
    ("running out of budget is reported as never produced", _F,
     "    if len(commits) > budget:",
     "    if False:"),
    ("an unreadable revision is reported as never produced", _F,
     "        if after is None or before is None:\n"
     "            return Provenance.UNKNOWN",
     "        if after is None or before is None:\n"
     "            continue"),
    ("a failing git command looks like an empty answer", _F,
     "    if out.returncode != 0:\n        return None",
     "    if out.returncode != 0:\n        return ''"),
    ("git failing to run at all is swallowed", _F,
     "    except (OSError, subprocess.SubprocessError):\n        return None",
     "    except (OSError, subprocess.SubprocessError):\n        return ''"),
    # --- the distinction the module exists for ---
    ("relocation into a test is reported as an ordinary removal", _F,
     "                return Provenance.RELOCATED_TO_TESTS",
     "                return Provenance.REMOVED_FROM_LIBRARY"),
    ("a test that already produced it counts as a relocation", _F,
     "            if member not in test_before and member in test_after:",
     "            if member in test_after:"),
    ("a removal is reported as never produced", _F,
     "            return Provenance.REMOVED_FROM_LIBRARY\n"
     "        if member in lib_after:",
     "            return Provenance.NEVER_PRODUCED\n"
     "        if member in lib_after:"),
    ("the library/test split is ignored, so nothing is ever a relocation", _M,
     "        (tests if _looks_like_a_test(path) else library)[path] = tree",
     "        library[path] = tree"),
    # --- the walk itself ---
    ("the parent of a root commit is unreadable rather than empty", _F,
     '    if rev == "":\n        return set(), set()',
     '    if False:\n        return set(), set()'),
    ("only the newest candidate commit is examined", _F,
     "    for commit in commits[:budget]:",
     "    for commit in commits[:1]:"),
    ("no commits found is read as unreadable rather than as an answer", _F,
     "    if not commits:\n        # git answered, and the answer is that this text never entered a\n"
     "        # Python file. Nothing ever produced it.\n"
     "        return Provenance.NEVER_PRODUCED",
     "    if not commits:\n        return Provenance.UNKNOWN"),
    ("git grep finding nothing is treated as a failure", _F,
     '        if _git(root, "rev-parse", "--verify", "--quiet", rev + "^{commit}"):\n'
     "            return []",
     '        if False:\n            return []'),
    # --- what the detector does with the answer ---
    ("history does not change the severity at all", _M,
     "                severity=_HISTORY_SEVERITY[provenance],",
     "                severity=Severity.MINOR,"),
    ("a removal is graded no higher than an oversight", _M,
     "    forensics.Provenance.REMOVED_FROM_LIBRARY: Severity.MAJOR,",
     "    forensics.Provenance.REMOVED_FROM_LIBRARY: Severity.MINOR,"),
    ("a relocation is graded no higher than an oversight", _M,
     "    forensics.Provenance.RELOCATED_TO_TESTS: Severity.MAJOR,",
     "    forensics.Provenance.RELOCATED_TO_TESTS: Severity.MINOR,"),
    ("not knowing is graded as if it were a removal", _M,
     "    forensics.Provenance.UNKNOWN: Severity.MINOR,",
     "    forensics.Provenance.UNKNOWN: Severity.MAJOR,"),
    ("history is asked about declarations from another repository", _M,
     "            if root is not None and _within(root, path):",
     "            if root is not None:"),
    ("history is consulted even when the caller said not to", _M,
     "    root = forensics.repo_root(files) if history else None",
     "    root = forensics.repo_root(files)"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, DOCS, run_tests_with_mutation(DOCS, rel, old, new))


def test_the_suite_passes_unmutated():
    anchor = "BUDGET = 20"
    result = run_tests_with_mutation(DOCS, _F, anchor, anchor)
    assert result.returncode == 0, result.stdout[-1500:]
