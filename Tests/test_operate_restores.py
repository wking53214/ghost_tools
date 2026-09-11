"""The tree goes back, whatever happened on the table.

Every test in test_operate.py that asserts restoration asserts it after a
SUCCESSFUL operation. That was the whole coverage, and it was the reason a
real defect sat here undetected: the return to the original branch was the
last statement of a linear function, so any exception in between left the
repository checked out on the operation branch, sometimes with uncommitted
edits. Four forced failures reproduced it, one of them through the CLI.

So these are the failure-path tests. Each breaks the operation at a
different point -- the remedy, the re-examination, the commit -- and then
asserts the only thing that matters to somebody whose scan just crashed:
the tree is on the branch it came in on, and it is clean.
"""
from __future__ import annotations

import subprocess
import textwrap

import pytest

from ghost_buster import operate as opmod
from ghost_buster.ledger import RAN
from ghost_buster.mechanical import run_all
from ghost_buster.operate import LeftOnTheTable, Refused, operate


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


PATIENT = {
    "queue.py": '''\
        def enqueue(recipient_pub, payload):
            return (recipient_pub, payload)
    ''',
    "caller.py": '''\
        from queue import enqueue


        def send(cust_pub, payload):
            return enqueue(cust_pub, payload)
    ''',
    "README.md": "# patient\n",
}


@pytest.fixture
def patient(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for rel, body in PATIENT.items():
        (root / rel).write_text(textwrap.dedent(body))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "admit")
    return root


def _workup(root):
    files = sorted(root.rglob("*.py")) + sorted(root.rglob("*.md"))
    return files, run_all(files), {"tests": RAN, "secrets": RAN}


def _state(root):
    return _git(root, "branch", "--show-current"), _git(root, "status", "--porcelain")


class Boom(RuntimeError):
    """A failure from outside this module's control."""


# --------------------------------------------------- the three break points

def test_a_remedy_that_raises_leaves_the_tree_where_it_found_it(patient, monkeypatch):
    files, findings, checks = _workup(patient)

    def exploding(root, files):
        raise Boom("the remedy failed")

    monkeypatch.setitem(opmod.REMEDIES, "annotate", exploding)
    with pytest.raises(Boom):
        operate(patient, files, findings, checks, branch="ghost/op")

    assert _state(patient) == ("main", "")


def test_a_re_examination_that_raises_leaves_the_tree_where_it_found_it(patient):
    """The remedy has already written to the tree when this fires, so the
    restoration has real edits to discard -- the case that left an
    uncommitted README behind before this existed."""
    files, findings, checks = _workup(patient)

    def exploding(files):
        raise Boom("the re-examination failed")

    with pytest.raises(Boom):
        operate(patient, files, findings, checks, branch="ghost/op", rescan=exploding)

    assert _state(patient) == ("main", "")


def test_a_commit_the_repository_rejects_leaves_the_tree_where_it_found_it(patient):
    """A pre-commit hook that refuses is a policy, not a bug, and the
    surgeon has to survive it. Before this, the tree was left on the
    operation branch with the remedy's edits staged."""
    hook = patient / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    files, findings, checks = _workup(patient)

    with pytest.raises(Refused):
        operate(patient, files, findings, checks, branch="ghost/op")

    assert _state(patient) == ("main", "")


def test_an_interrupt_leaves_the_tree_where_it_found_it(patient):
    """KeyboardInterrupt is not an Exception. A `finally` catches it; an
    `except Exception` would not, which is why this test names it."""
    files, findings, checks = _workup(patient)

    def interrupted(files):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        operate(patient, files, findings, checks, branch="ghost/op", rescan=interrupted)

    assert _state(patient) == ("main", "")


# ------------------------------------------------------ what is NOT discarded

def test_cuts_that_completed_survive_on_their_branch(patient):
    """Restoration discards the tool's uncommitted edits, never its commits.
    A cut that completed is evidence, and the branch keeps it."""
    files, findings, checks = _workup(patient)
    op = operate(patient, files, findings, checks, branch="ghost/op")

    assert op.cuts, "the fixture is meant to produce one cut"
    assert _git(patient, "rev-parse", "ghost/op") == op.cuts[0].commit
    assert _state(patient) == ("main", "")


def test_a_detached_patient_goes_back_to_its_commit_after_a_failure(patient):
    """No branch to protect, only a commit -- and the failure path has to
    honour that too, or a detached patient is left on the table."""
    head = _git(patient, "rev-parse", "HEAD")
    _git(patient, "checkout", "-q", "--detach", head)
    files, findings, checks = _workup(patient)

    def exploding(files):
        raise Boom("the re-examination failed")

    with pytest.raises(Boom):
        operate(patient, files, findings, checks, branch="ghost/op", rescan=exploding)

    assert _git(patient, "branch", "--show-current") == ""
    assert _git(patient, "rev-parse", "HEAD") == head
    assert _git(patient, "status", "--porcelain") == ""


# ------------------------------------------------- when restoration fails too

def test_a_failed_restoration_says_which_branch_the_tree_is_on(patient, monkeypatch):
    """Silence here is the worst outcome: the caller would believe the
    original failure was the whole story."""
    files, findings, checks = _workup(patient)
    real_git = opmod._git

    def broken_git(root, *args):
        if args and args[0] in ("reset", "checkout") and "-b" not in args:
            raise Refused("git reset: disk is full")
        return real_git(root, *args)

    def exploding(files):
        raise Boom("the re-examination failed")

    monkeypatch.setattr(opmod, "_git", broken_git)
    with pytest.raises(LeftOnTheTable) as caught:
        operate(patient, files, findings, checks, branch="ghost/op", rescan=exploding)

    assert "main" in str(caught.value)
    assert isinstance(caught.value.__cause__, Refused)


def test_a_dry_run_needs_no_restoration(patient):
    """It opens no branch and writes nothing, so there is nothing to put
    back, and the guard must not invent work on a tree it never touched."""
    files, findings, checks = _workup(patient)
    before = _state(patient)
    op = operate(patient, files, findings, checks, branch="ghost/op", dry_run=True)

    assert op.dry_run and not op.cuts
    assert _state(patient) == before
    assert "ghost/op" not in _git(patient, "branch", "--format=%(refname:short)")
