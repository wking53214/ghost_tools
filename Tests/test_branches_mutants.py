"""The proof that Tests/test_branches.py is not vacuous: break
ghost_buster/branches.py one way at a time in a scratch copy and run only
that file. Every mutant here must be killed.

ghost_buster --mutate --mutate-only test_branches.py reports zero
candidates: every assertion in that file is either a call result compared
directly (`f.category == Category.UNMERGED_BRANCH`) or a membership/count
check the shape scanner doesn't treat as weak. The tool has nothing to
mutate there, which is not the same as having proven the tests check
anything -- the same gap test_gate_mutants.py and test_polish_mutants.py
exist to close for their own modules.

An initial exploratory run of 16 mutants found four survivors. Two turned
out not to be real gaps and are not here:

- Forcing `_is_ancestor` to always return False, and skipping its
  early-continue in scan() entirely, both survived every existing test.
  Not a bug: an ancestor branch's merge-base with base is its own tip, so
  `_is_squash_absorbed`'s empty-diff case recognizes it as absorbed on its
  own. `_is_ancestor` is a cheap fast path, not a correctness requirement
  (see its docstring); removing it can only make a correct scan slower,
  never wrong, so it is deliberately not treated as load-bearing here.
- Swapping the argument order in `git merge-base base branch` to
  `git merge-base branch base` survived because it is not actually a
  mutant: `git merge-base` is documented as symmetric in its two-ref
  form. The "mutation" produces identical output, so nothing to kill.

The third and fourth were real gaps, fixed in Tests/test_branches.py
before this file was written, not by weakening this file's requirements:
a branch whose commits net to zero diff against its own merge-base (work
done, then reverted -- not an ancestor, but nothing would be lost by
deleting it) had no test, and the code path that decides "nothing to
compare, treat as absorbed" for that exact case had no test pinning it
either. Both mutants are included below and both are now killed.

Two more were added after the first whole-library run (37 repositories),
which found both: a transcript-dump repo whose diff contained a
Windows-1252 byte crashed the scan outright (and, with only the exception
swallowed, would have read as silently absorbed instead -- a false
negative, worse than the crash), and every clone-shaped checkout counted
refs/remotes/origin/HEAD as a phantom branch because git shortens that
ref to the bare word "origin".

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

BRANCH_TESTS = "Tests/test_branches.py"
_B = "ghost_buster/branches.py"

# (label, file, exact text to replace, replacement)
MUTANTS = [
    ("squash-absorption always true (would hide every real orphan branch)", _B,
     '    merge_base = _run(root, ["merge-base", base, branch])\n',
     '    return True\n    merge_base = _run(root, ["merge-base", base, branch])\n'),
    ("squash-absorption always false (would flag every squash-merged branch)", _B,
     '    merge_base = _run(root, ["merge-base", base, branch])\n',
     '    return False\n    merge_base = _run(root, ["merge-base", base, branch])\n'),
    ("squash check skipped entirely in scan()", _B,
     '        if _is_squash_absorbed(root, name, base):\n            continue\n',
     ''),
    ("branch's own diff compared against the wrong side", _B,
     '    branch_patch = _patch_id(root, ["diff", merge_base, branch])\n',
     '    branch_patch = _patch_id(root, ["diff", merge_base, base])\n'),
    ("a net-zero branch diff treated as unmerged instead of absorbed", _B,
     '    if branch_patch is None:\n'
     '        # Nothing to compare: branch introduces no diff at all relative to\n'
     '        # its own merge-base, so there is nothing for it to be missing.\n'
     '        return True\n',
     '    if branch_patch is None:\n        return False\n'),
    ("base-commit range reversed (never finds the squash commit)", _B,
     '    base_commits = _run(root, ["log", "--format=%H", f"{merge_base}..{base}"])\n',
     '    base_commits = _run(root, ["log", "--format=%H", f"{base}..{merge_base}"])\n'),
    ("dedup by sha disabled (local + remote copy of one branch double-reported)", _B,
     '            if sha in seen_shas:\n                continue\n            seen_shas.add(sha)\n',
     '            seen_shas.add(sha)\n'),
    ("base branch not excluded from its own scan list", _B,
     '            if name == "origin/HEAD" or _short_name(name) == base_name:\n                continue\n',
     '            if name == "origin/HEAD":\n                continue\n'),
    ("severity hardcoded to MINOR instead of MAJOR", _B,
     '        severity=Severity.MAJOR,\n', '        severity=Severity.MINOR,\n'),
    ("category hardcoded wrong", _B,
     '        category=Category.UNMERGED_BRANCH,\n', '        category=Category.OTHER,\n'),
    ("git-repository check always true (masks a non-git directory)", _B,
     '    return _run(root, ["rev-parse", "--git-dir"]) is not None\n', '    return True\n'),
    ("decode errors no longer replaced (a non-UTF-8 diff silently reads as absorbed)", _B,
     '            capture_output=True, text=True, errors="replace", timeout=timeout,\n',
     '            capture_output=True, text=True, timeout=timeout,\n'),
    ("origin/HEAD counted as a branch on every clone-shaped checkout", _B,
     '            if name == "origin/HEAD" or _short_name(name) == base_name:\n',
     '            if _short_name(name) == base_name:\n'),
    ("base-branch resolution never fails (masks a missing base branch)", _B,
     '    for candidate in candidates:\n'
     '        if candidate and _run(root, ["rev-parse", "--verify", "--quiet", candidate]) is not None:\n'
     '            return candidate\n    return None\n',
     '    return candidates[0]\n'),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_branch_scanner_mutant_is_killed(label, rel, old, new):
    assert_killed(label, BRANCH_TESTS, run_tests_with_mutation(BRANCH_TESTS, rel, old, new))


def test_branch_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        BRANCH_TESTS, _B, 'DETECTOR = "unmerged_branch"\n', 'DETECTOR = "unmerged_branch"\n',
    )
    assert result.returncode == 0, result.stdout[-2000:]
