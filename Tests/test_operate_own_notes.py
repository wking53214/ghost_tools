"""The surgeon's notes are not the patient's dirt.

THE DEFECT THIS FILE GUARDS AGAINST (v1.6.1)

An operation refuses a dirty tree, and it was refusing trees it had
dirtied itself.

A scan writes `.ghost_ledger.json` into the repository it scanned.
`--operate` scans first and operates second, in one process. So the door
check saw the ledger that the same run had just written, and refused.

Measured on ghost_tools at 8ac6744, from a verifiably clean checkout, in
one command: the run created the ledger and then refused its own output.
That made `--operate` impossible with default flags on any repository
that does not already track or ignore the ledger. The library's first
real operation only appeared to work because it happened to be run with
`--no-ledger`, and nothing anywhere said that was required.

There is a second half to the same confusion. The cut committed with
`git add -A`, which would have swept the ledger into the patient's
history as part of a clinical commit. The surgeon's own chart does not
belong in the patient's record.

Both halves are tested here, plus the boundary that keeps the fix
honest: a note the repository TRACKS is somebody's committed file, so a
modification to it is a real edit and the tree is dirty exactly as
before.
"""
from __future__ import annotations

import subprocess
import textwrap

import pytest

from ghost_buster.ledger import RAN
from ghost_buster.mechanical import run_all
from ghost_buster.operate import SURGEONS_NOTES, Refused, _dirty_paths, operate


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


# ------------------------------------------------------------ the door check

def test_an_untracked_ledger_is_not_the_patients_dirt(patient):
    (patient / ".ghost_ledger.json").write_text('{"runs": []}')
    assert _dirty_paths(patient) == []


#: Named here, deliberately, instead of read off SURGEONS_NOTES. A test
#: that iterates the constant it is testing shrinks with it: narrow the
#: constant to one entry and such a test still passes, having checked one
#: file and called it three. A mutant caught exactly that.
THE_THREE_NOTES = (".ghost_ledger.json", ".ghost_baseline.json", ".ghost_casefile.json")


def test_every_note_the_tool_writes_is_covered(patient):
    for name in THE_THREE_NOTES:
        (patient / name).write_text("{}")
    assert _dirty_paths(patient) == []


def test_the_constant_names_every_file_the_tool_writes():
    """The other half: the list above is the whole set, so a fourth
    artefact cannot be added to the tool and quietly go unhandled."""
    assert set(SURGEONS_NOTES) == set(THE_THREE_NOTES)


def test_the_patients_own_edit_is_still_dirt(patient):
    (patient / "queue.py").write_text("def enqueue(a, b):\n    return 0\n")
    assert _dirty_paths(patient) == ["queue.py"]


def test_an_untracked_file_of_the_patients_is_still_dirt(patient):
    (patient / "scratch.py").write_text("x = 1\n")
    assert _dirty_paths(patient) == ["scratch.py"]


def test_a_tracked_note_that_changed_is_a_real_edit(patient):
    """The boundary that keeps the fix honest. A repository that COMMITS
    its baseline has decided that file is part of the project, so a
    change to it is somebody's edit, not the tool's scratch."""
    note = patient / ".ghost_baseline.json"
    note.write_text("[]")
    _git(patient, "add", "-A")
    _git(patient, "commit", "-q", "-m", "track the baseline")
    note.write_text('[{"id": "ghost-1"}]')
    assert _dirty_paths(patient) == [".ghost_baseline.json"]


# ------------------------------------------------- whose edit is it (v1.7.3)
#
# "Tracked, therefore somebody's real edit" turned out to be the wrong test,
# and it reinstated the same deadlock one level down for any repository that
# COMMITS its ledger -- which this tool's own documentation recommends, on
# the grounds that a governance record nobody keeps is worth nothing.
#
# Measured on a clean checkout, in one command, with no harness: commit the
# ledger, run --operate, and the workup writes the ledger, the door sees a
# modified tracked file, and the operation refuses. Every time, forever.
#
# The distinction was never tracked versus untracked. It is whose edit it is.

def _commit_the_ledger(patient, body='{"runs": []}'):
    (patient / ".ghost_ledger.json").write_text(body)
    _git(patient, "add", "-A")
    _git(patient, "commit", "-q", "-m", "keep the governance record")


def test_a_committed_note_this_run_rewrote_is_not_dirt(patient):
    """Clean when we arrived, different now: the difference is ours."""
    from ghost_buster.operate import notes_on_arrival
    _commit_the_ledger(patient)
    arrival = notes_on_arrival(patient)
    (patient / ".ghost_ledger.json").write_text('{"runs": [{"at": "now"}]}')
    assert _dirty_paths(patient, arrival) == []


def test_a_committed_note_somebody_else_had_edited_is_still_dirt(patient):
    """The boundary the fix must not cross.

    An uncommitted edit to a committed record is somebody's work. It was
    already different from HEAD before this run touched anything, and
    proceeding would let the workup overwrite it.
    """
    from ghost_buster.operate import notes_on_arrival
    _commit_the_ledger(patient)
    (patient / ".ghost_ledger.json").write_text('{"runs": [], "mine": true}')
    arrival = notes_on_arrival(patient)          # snapshot AFTER their edit
    (patient / ".ghost_ledger.json").write_text('{"runs": [{"at": "now"}]}')
    assert _dirty_paths(patient, arrival) == [".ghost_ledger.json"]


def test_a_note_that_was_not_there_on_arrival_is_not_assumed_clean(patient):
    """No entry means no evidence, and no evidence refuses rather than
    proceeds. An absent or unreadable note must not read as 'ours'."""
    _commit_the_ledger(patient)
    (patient / ".ghost_ledger.json").write_text('{"runs": [{"at": "now"}]}')
    assert _dirty_paths(patient, {}) == [".ghost_ledger.json"]


def test_the_old_callers_lose_nothing(patient):
    """Without a snapshot the door behaves exactly as it did before."""
    _commit_the_ledger(patient)
    (patient / ".ghost_ledger.json").write_text('{"runs": [{"at": "now"}]}')
    assert _dirty_paths(patient) == [".ghost_ledger.json"]


def test_the_operation_proceeds_past_a_committed_ledger(patient):
    """The deadlock, end to end.

    This is the shape a real repository has after taking the tool's own
    advice about keeping the record.
    """
    from ghost_buster.operate import notes_on_arrival
    _commit_the_ledger(patient)
    arrival = notes_on_arrival(patient)
    files, findings, checks = _workup(patient)
    (patient / ".ghost_ledger.json").write_text('{"runs": [{"at": "now"}]}')
    op = operate(patient, files, findings, checks, branch="ghost/op",
                 arrival=arrival)
    assert op.came_in_untouched


def test_a_committed_ledger_somebody_edited_still_stops_the_operation(patient):
    from ghost_buster.operate import notes_on_arrival
    _commit_the_ledger(patient)
    (patient / ".ghost_ledger.json").write_text('{"runs": [], "mine": true}')
    arrival = notes_on_arrival(patient)
    files, findings, checks = _workup(patient)
    with pytest.raises(Refused):
        operate(patient, files, findings, checks, branch="ghost/op2",
                arrival=arrival)


def test_the_operation_proceeds_past_its_own_ledger(patient):
    """The end-to-end shape of the defect: a scan wrote a ledger, and the
    operation in the same process refused it."""
    files, findings, checks = _workup(patient)
    (patient / ".ghost_ledger.json").write_text('{"runs": []}')
    op = operate(patient, files, findings, checks, branch="ghost/op")
    assert op.came_in_untouched
    assert _git(patient, "branch", "--show-current") == "main"


def test_the_operation_still_refuses_the_patients_dirt(patient):
    files, findings, checks = _workup(patient)
    (patient / "queue.py").write_text("def enqueue(a, b):\n    return 0\n")
    with pytest.raises(Refused) as refusal:
        operate(patient, files, findings, checks, branch="ghost/op")
    assert "queue.py" in str(refusal.value)


# ------------------------------------------------------------- the cut commit

def test_a_cut_never_commits_the_surgeons_notes(patient):
    """`git add -A` would have put the ledger in the patient's history."""
    files, findings, checks = _workup(patient)
    (patient / ".ghost_ledger.json").write_text('{"runs": []}')
    op = operate(patient, files, findings, checks, branch="ghost/op")
    assert op.cuts, "the annotate remedy made no cut, so this proves nothing"
    for cut in op.cuts:
        listed = _git(patient, "show", "--name-only", "--format=", cut.commit).split()
        assert listed, f"cut {cut.step} committed nothing"
        for name in SURGEONS_NOTES:
            assert name not in listed, f"cut {cut.step} committed {name}"


def test_the_ledger_survives_the_operation_unread_and_uncommitted(patient):
    """It is still there afterwards, still untracked. The operation
    neither adopts it nor deletes it."""
    files, findings, checks = _workup(patient)
    ledger = patient / ".ghost_ledger.json"
    ledger.write_text('{"runs": []}')
    operate(patient, files, findings, checks, branch="ghost/op")
    assert ledger.is_file()
    assert _git(patient, "status", "--porcelain") == "?? .ghost_ledger.json"


# ------------------------------------------------------------- what it claims

def test_a_dry_run_does_not_claim_to_have_written_nothing(patient):
    """It writes the ledger, like every scan. What it does not write is a
    cut, and that is what the line now says."""
    files, findings, checks = _workup(patient)
    rendered = operate(patient, files, findings, checks, dry_run=True).render()
    assert "no cut written" in rendered
    assert "nothing written" not in rendered
