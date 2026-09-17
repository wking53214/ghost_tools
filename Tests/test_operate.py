"""The surgeon operates, on a table, and never on the patient's own branch.

Every test here builds a real git repository, because the claims are about
branches and commits and a mock cannot refuse the way git does.
"""
from __future__ import annotations

import subprocess
import textwrap

import pytest

from ghost_buster.casefile import EXPOSED, HEALED, Casefile
from ghost_buster.ledger import RAN
from ghost_buster.mechanical import run_all
from ghost_buster.operate import Refused, operate


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


# A patient with one name disagreement: the one remedy v1 carries has
# something to do, and re-examination has something to notice.
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


# ------------------------------------------------------------- refusals

def test_refuses_a_dirty_tree(patient):
    (patient / "scratch.py").write_text("x = 1\n")
    files, findings, checks = _workup(patient)
    with pytest.raises(Refused, match="dirty"):
        operate(patient, files, findings, checks)


def test_refuses_without_a_repository(tmp_path):
    (tmp_path / "m.py").write_text("x = 1\n")
    with pytest.raises(Refused, match="table"):
        operate(tmp_path, [tmp_path / "m.py"], [], {})


# ------------------------------------------------------------ the table

def test_the_patient_comes_off_the_table_on_the_branch_it_came_in_on(patient):
    files, findings, checks = _workup(patient)
    before = _git(patient, "rev-parse", "HEAD")
    op = operate(patient, files, findings, checks, branch="ghost/op")
    assert _git(patient, "branch", "--show-current") == "main"
    assert _git(patient, "rev-parse", "HEAD") == before
    assert op.came_in_untouched
    assert op.came_in_on == "main"


def test_a_detached_patient_goes_back_to_its_commit(patient):
    """No branch to protect, only a commit. The first patient came in
    detached and was left on the table; this is that bug, pinned."""
    files, findings, checks = _workup(patient)
    before = _git(patient, "rev-parse", "HEAD")
    _git(patient, "checkout", "-q", "--detach", before)
    op = operate(patient, files, findings, checks, branch="ghost/op")
    assert _git(patient, "rev-parse", "HEAD") == before
    assert _git(patient, "branch", "--show-current") == ""
    assert op.came_in_untouched
    assert op.came_in_on == "detached HEAD"
    assert _git(patient, "rev-parse", "ghost/op") == op.cuts[0].commit


def test_each_cut_is_a_commit_on_the_table(patient):
    files, findings, checks = _workup(patient)
    op = operate(patient, files, findings, checks, branch="ghost/op")
    assert len(op.cuts) == 1
    cut = op.cuts[0]
    assert cut.remedy == "annotate"
    assert cut.changed_files >= 2                      # two .py files and the README
    assert _git(patient, "rev-parse", "ghost/op") == cut.commit
    assert "operate: annotate" in _git(patient, "log", "-1", "--format=%s", "ghost/op")
    assert "name-disagreement" in _git(patient, "show", "ghost/op:queue.py")


def test_re_examination_records_what_the_cut_did(patient):
    """Annotating does not close the disagreement -- it writes it down --
    so nothing is healed and nothing new is exposed. The chain says so
    rather than claiming a cure."""
    files, findings, checks = _workup(patient)
    op = operate(patient, files, findings, checks, branch="ghost/op")
    cut = op.cuts[0]
    assert cut.healed == 0
    assert cut.exposed == []


def test_a_cut_that_heals_is_recorded_in_the_case_file(patient, tmp_path):
    """A remedy that removes a finding records HEALED against its shape."""
    files, findings, checks = _workup(patient)
    casefile = Casefile(tmp_path / "cases.json")

    def rescan(_files):
        return []           # pretend the cut healed everything

    op = operate(patient, files, findings, checks, casefile=casefile,
                 branch="ghost/op", rescan=rescan)
    assert op.cuts[0].healed == len(findings) > 0
    assert casefile.prior("name_disagreement").counts.get(HEALED) == 1
    assert (tmp_path / "cases.json").exists(), "outcomes are saved"


def test_what_the_second_look_cannot_see_is_carried_not_healed(patient, tmp_path):
    """The re-examination is run_all. A committed secret comes from
    gitleaks, which run_all does not run, so its absence from the second
    look means nothing. It is carried forward, still on the table, still
    failing candidacy. The first patient reported eight of these healed
    by writing comments."""
    from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status
    secret = Finding(detector="committed_secret", category=Category.COMMITTED_SECRET,
                     layer=Layer.MECHANICAL, severity=Severity.CRITICAL,
                     status=Status.CONFIRMED, summary="a key in history",
                     evidence=Evidence(file="x.py"))
    files, findings, checks = _workup(patient)
    casefile = Casefile(tmp_path / "cases.json")
    op = operate(patient, files, list(findings) + [secret], checks, casefile=casefile,
                 branch="ghost/op", rescan=lambda _files: [])
    cut = op.cuts[0]
    assert cut.healed == len(findings) > 0
    assert secret.id not in cut.closed
    assert secret.id in {f.id for f in op.on_the_table}
    assert not op.readiness_after.candidate
    assert "committed secret" in op.readiness_after.render()
    assert casefile.prior("committed_secret").counts.get(HEALED) is None


def test_a_cut_that_exposes_is_recorded_too(patient, tmp_path):
    """Finding the spread: what a cut reveals is the next thing on the
    table, and the case file learns that this remedy exposes things."""
    files, findings, checks = _workup(patient)
    casefile = Casefile(tmp_path / "cases.json")
    extra = list(findings)

    def rescan(_files):
        from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status
        return extra + [Finding(detector="dead_end_call", category=Category.DEAD_CODE,
                                layer=Layer.MECHANICAL, severity=Severity.MAJOR,
                                status=Status.CONFIRMED, summary="revealed",
                                evidence=Evidence(file="x.py"))]

    op = operate(patient, files, findings, checks, casefile=casefile,
                 branch="ghost/op", rescan=rescan)
    assert len(op.cuts[0].exposed) == 1
    assert casefile.prior("dead_end_call").counts.get(EXPOSED) == 1


# ------------------------------------------------------------ candidacy

def test_the_serum_is_offered_only_to_a_candidate(patient):
    """And what a candidate gets is about the PATIENT. Until 1.8.1 the
    assertion here was `"measured redundancy" in op.serum`, which is the
    profiler's count of ghost_buster's own parses and reads -- a serum that
    passed this test while telling the patient nothing about itself."""
    files, findings, checks = _workup(patient)
    op = operate(patient, files, findings, checks, branch="ghost/op")
    assert op.readiness_after is not None
    if op.readiness_after.candidate:
        assert any("enhancement surface" in s for s in op.serum)
        assert op.serum_report is not None and op.serum_report.ran
    else:
        assert op.serum == []
        assert op.serum_report is None


def test_an_unexamined_patient_is_not_a_candidate(patient):
    files, findings, _ = _workup(patient)
    op = operate(patient, files, findings, {}, branch="ghost/op")
    assert not op.readiness_after.candidate
    assert op.serum == []
    assert "could not examine" in op.render()


def test_a_dry_run_writes_nothing(patient):
    files, findings, checks = _workup(patient)
    before = _git(patient, "rev-parse", "HEAD")
    op = operate(patient, files, findings, checks, dry_run=True, branch="ghost/op")
    assert op.cuts == []
    assert "dry run" in op.render()
    assert _git(patient, "rev-parse", "HEAD") == before
    assert "ghost/op" not in _git(patient, "branch", "--list")
    assert "name-disagreement" not in (patient / "queue.py").read_text()


def test_untouched_can_say_no(patient):
    """The check has to be able to fail, or it is a docstring. Build the
    record of an operation whose patient branch moved and ask."""
    from ghost_buster.operate import Operation
    from ghost_buster.readiness import assess
    op = Operation(root=patient, branch="ghost/op", came_in_on="main",
                   head_before="aaaa", readiness_before=assess([], {}))
    op.head_after = "bbbb"
    assert not op.came_in_untouched
    assert "MODIFIED" in op.render()
    op.head_after = "aaaa"
    assert op.came_in_untouched


def test_the_report_names_what_is_left_for_a_human(patient):
    files, findings, checks = _workup(patient)
    op = operate(patient, files, findings, checks, branch="ghost/op")
    text = op.render()
    assert "OPERATIVE REPORT" in text
    assert "before" in text and "after" in text
    assert "untouched" in text

def test_the_after_block_marks_what_the_re_examination_could_not_see(patient):
    """The cut re-runs the detectors; it does not re-run the suite or the
    secrets scan. Before this, the after-block read `suite ran clean` in
    exactly the words the workup used, for an examination that never
    happened."""
    files, findings, checks = _workup(patient)
    op = operate(patient, files, findings, checks, branch="ghost/op")

    assert op.cuts, "the fixture is meant to produce a cut"
    carried = {c.name for c in op.readiness_after.carried}
    assert carried == {"tests run and pass", "no committed secrets"}
    assert "carried from the workup" in op.render()
    assert not op.readiness_before.carried, "the workup established its own evidence"


def test_nothing_is_carried_when_no_cut_was_made(patient):
    """With no cut the tree is the one the workup examined, so the
    after-block is the workup, not a stale copy of it."""
    files, findings, checks = _workup(patient)
    op = operate(patient, files, findings, checks, branch="ghost/op", dry_run=True)

    assert not op.cuts
    assert not op.readiness_after.carried
