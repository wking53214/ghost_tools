"""The swizzle gate's choice of base revision, and what it does when there is none.

The gate used to resolve its base inline and, when it could not (a first push, a
force-push that orphaned the old head, a shallow checkout), print a warning and
exit 0: a gate that passes because it had nothing to compare against is not a
gate. The logic now lives in `.github/scripts/resolve-swizzle-base.sh` and has
three outcomes, each held here:

    0  a base (stdout): run the comparison
    3  the repository's very first commit: the one allowed skip, announced
    1  no base where one must exist: the gate FAILS
"""
from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "resolve-swizzle-base.sh"
WORKFLOW = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
ZEROS = "0" * 40


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo, name):
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    return path


def _run(repo, event, before=""):
    env = {**os.environ, "EVENT": event, "BEFORE": before}
    return subprocess.run(["bash", str(SCRIPT), str(repo)], env=env, capture_output=True, text=True)


def test_a_pull_request_is_compared_against_the_first_parent_of_the_merge_commit(repo):
    base = _commit(repo, "base")
    _git(repo, "checkout", "-q", "-b", "topic")
    _commit(repo, "topic")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main2")
    main_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "topic")
    result = _run(repo, "pull_request")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == main_head != base


def test_a_push_is_compared_against_the_previous_head(repo):
    before = _commit(repo, "one")
    _commit(repo, "two")
    result = _run(repo, "push", before)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == before


def test_a_push_with_no_previous_head_fails_where_history_exists(repo):
    _commit(repo, "one")
    _commit(repo, "two")
    for before in (ZEROS, "", "1234567890123456789012345678901234567890"):
        result = _run(repo, "push", before)
        assert result.returncode == 1, (before, result.stdout, result.stderr)
        assert result.stdout == ""
        assert "::error::swizzle gate" in result.stderr


def test_the_first_commit_is_the_one_allowed_skip_and_it_is_loud(repo):
    _commit(repo, "one")
    result = _run(repo, "push", ZEROS)
    assert result.returncode == 3
    assert result.stdout == ""
    assert "::warning::swizzle gate: SKIPPED on purpose" in result.stderr
    assert "first commit" in result.stderr


def test_a_pull_request_without_a_base_fails_even_on_a_single_commit(repo):
    _commit(repo, "one")
    result = _run(repo, "pull_request")
    assert result.returncode == 1
    assert "::error::swizzle gate" in result.stderr


def test_a_shallow_clone_fails_instead_of_reading_its_cut_off_root_as_the_first_commit(repo, tmp_path):
    _commit(repo, "one")
    _commit(repo, "two")
    _commit(repo, "three")
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", repo.resolve().as_uri(), str(clone)],
                   check=True, capture_output=True)
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "true"
    for event, before in (("push", ZEROS), ("push", ""), ("pull_request", "")):
        result = _run(clone, event, before)
        assert result.returncode == 1, (event, result.returncode, result.stdout, result.stderr)
        assert result.stdout == ""
        assert "::error::swizzle gate" in result.stderr and "shallow" in result.stderr
    # the full history of the same repository is still the allowed non-skip
    assert _run(repo, "push", _git(repo, "rev-parse", "HEAD~1")).returncode == 0


def test_an_unknown_event_fails_rather_than_passing(repo):
    _commit(repo, "one")
    result = _run(repo, "workflow_dispatch")
    assert result.returncode == 1
    assert "workflow_dispatch" in result.stderr


def test_the_script_is_executable_because_the_workflow_runs_it_directly():
    assert os.access(SCRIPT, os.X_OK)


def test_the_workflow_uses_the_script_and_no_longer_passes_on_a_missing_base():
    assert "resolve-swizzle-base.sh" in WORKFLOW
    assert "no reachable base revision" not in WORKFLOW
    gate = WORKFLOW[WORKFLOW.index("      - name: Regression gate"):]
    # the only exit 0 in the step is the explicit first-commit outcome (rc 3)
    assert gate.count("exit 0") == 1
    assert 'if [ "$rc" -eq 3 ]' in gate
