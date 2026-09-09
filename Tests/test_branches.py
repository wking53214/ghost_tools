"""Tests for ghost_buster/branches.py, exercised against real git
repositories built in tmp_path -- there is no way to test a ref-graph
check honestly against parsed strings the way mechanical.py's AST
detectors can be tested; the repository IS the input.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ghost_buster.branches import scan
from ghost_buster.schema import Category, Severity, Status


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "a.txt").write_text("one\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-q", "-m", "initial")
    return path


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", message)


def test_non_git_directory_reports_did_not_run(tmp_path):
    findings, report = scan(tmp_path)
    assert findings == []
    assert report.ran is False
    assert "not a git repository" in report.reason


def test_missing_base_branch_reports_did_not_run(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    findings, report = scan(repo, base_branch="does-not-exist")
    assert findings == []
    assert report.ran is False
    assert "does-not-exist" in report.reason


def test_no_other_branches_scans_cleanly_with_nothing_found(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    findings, report = scan(repo)
    assert findings == []
    assert report.ran is True
    assert report.base_branch == "main"
    assert report.branches_scanned == 0


def test_branch_pointing_at_the_same_commit_as_base_is_not_flagged(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "branch", "same-as-main")
    findings, _ = scan(repo)
    assert findings == []


def test_fast_forward_mergeable_branch_is_not_flagged(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "b.txt", "two\n", "add b")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feature")
    findings, report = scan(repo)
    assert findings == []
    assert report.branches_scanned == 1


def test_squash_merged_branch_is_not_flagged(tmp_path):
    # The exact false-positive this module exists to avoid: a branch
    # whose commits are gone from base's ancestry (squashed into one new
    # commit) but whose content is fully present.
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "b.txt", "two\n", "add b")
    _commit(repo, "c.txt", "three\n", "add c")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--squash", "feature")
    _git(repo, "commit", "-q", "-m", "squash feature")
    findings, report = scan(repo)
    assert findings == []
    assert report.branches_scanned == 1


def test_squash_merged_branch_is_still_not_flagged_after_base_moves_on(tmp_path):
    # Base picking up MORE commits after the squash must not resurrect
    # the finding -- the comparison is against the merge-base, not
    # against base's current tip alone.
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "b.txt", "two\n", "add b")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--squash", "feature")
    _git(repo, "commit", "-q", "-m", "squash feature")
    _commit(repo, "d.txt", "later\n", "unrelated later work on main")
    findings, _ = scan(repo)
    assert findings == []


def test_unmerged_branch_with_unique_content_is_flagged(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "orphan-work")
    _commit(repo, "d.txt", "four\n", "add d, never merged")
    _git(repo, "checkout", "-q", "main")

    findings, report = scan(repo)

    assert len(findings) == 1
    f = findings[0]
    assert f.category == Category.UNMERGED_BRANCH
    assert f.layer.value == "mechanical"
    assert f.severity == Severity.MAJOR
    assert f.status == Status.CONFIRMED
    assert "orphan-work" in f.summary
    assert "main" in f.summary
    assert "pull-request state" in f.detail
    assert "orphan-work" in f.evidence.file
    assert report.branches_scanned == 1


def test_diverged_branch_partially_absorbed_is_still_flagged(tmp_path):
    # A branch that shares some history with a squash-merge but ALSO has
    # its own extra commit on top must not be waved through just because
    # part of it matches.
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "b.txt", "two\n", "add b")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--squash", "feature")
    _git(repo, "commit", "-q", "-m", "squash feature")
    _git(repo, "checkout", "-q", "feature")
    _commit(repo, "e.txt", "extra\n", "more work after the squash landed")
    _git(repo, "checkout", "-q", "main")

    findings, _ = scan(repo)

    assert len(findings) == 1
    assert "feature" in findings[0].summary


def test_branch_whose_commits_net_to_zero_diff_is_not_flagged(tmp_path):
    # Not an ancestor of base (it has two commits base doesn't), but its
    # tip is byte-identical to its own merge-base -- work done, then
    # reverted. Nothing would be lost by deleting it.
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "reverted-work")
    _commit(repo, "b.txt", "two\n", "add b")
    (repo / "b.txt").unlink()
    _git(repo, "rm", "-q", "b.txt")
    _git(repo, "commit", "-q", "-m", "revert b, net zero change")
    _git(repo, "checkout", "-q", "main")

    findings, _ = scan(repo)

    assert findings == []


def test_finding_id_is_stable_across_repeated_scans(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "orphan-work")
    _commit(repo, "d.txt", "four\n", "add d")
    _git(repo, "checkout", "-q", "main")

    first, _ = scan(repo)
    second, _ = scan(repo)

    assert first[0].id == second[0].id


def test_finding_id_is_unaffected_by_new_commits_on_the_same_branch(tmp_path):
    # The finding tracks "this branch is unmerged", not the exact commit
    # or diffstat -- otherwise every new commit on a long-lived branch
    # would look like a brand new finding to baseline diffing.
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "orphan-work")
    _commit(repo, "d.txt", "four\n", "add d")
    _git(repo, "checkout", "-q", "main")
    before, _ = scan(repo)

    _git(repo, "checkout", "-q", "orphan-work")
    _commit(repo, "f.txt", "five\n", "more unmerged work")
    _git(repo, "checkout", "-q", "main")
    after, _ = scan(repo)

    assert before[0].id == after[0].id


def test_local_and_remote_tracking_copy_of_the_same_branch_counts_once(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main", "--bare")

    repo = _init_repo(tmp_path / "repo")
    _git(repo, "remote", "add", "origin", str(upstream))
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "-b", "topic")
    _commit(repo, "b.txt", "two\n", "topic work")
    _git(repo, "push", "-q", "origin", "topic")
    _git(repo, "checkout", "-q", "main")

    findings, report = scan(repo)

    assert report.branches_scanned == 1
    assert len(findings) == 1
    assert findings[0].summary.count("'topic'") + findings[0].summary.count("'origin/topic'") == 1


def test_remote_only_branch_with_no_local_copy_is_flagged(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main", "--bare")

    repo = _init_repo(tmp_path / "repo")
    _git(repo, "remote", "add", "origin", str(upstream))
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "-b", "topic")
    _commit(repo, "b.txt", "two\n", "topic work")
    _git(repo, "push", "-q", "origin", "topic")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "branch", "-D", "topic")

    findings, _ = scan(repo)

    assert len(findings) == 1
    assert "origin/topic" in findings[0].summary


def test_explicit_base_branch_is_honored_over_the_default_candidates(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "release")
    _git(repo, "checkout", "-q", "-b", "topic")
    _commit(repo, "b.txt", "two\n", "topic work, unmerged into release too")
    _git(repo, "checkout", "-q", "release")

    findings, report = scan(repo, base_branch="release")

    assert report.base_branch == "release"
    assert len(findings) == 1
    assert "release" in findings[0].summary
