"""The enhancement pass, and the two things it must not do.

It must not report the surgeon's work under the patient's name -- the
whole defect of the first serum, which handed a healthy candidate a count
of ghost_buster's own parses and reads.

It must not offer a dose it cannot check. The check is the patient's own
suite, and a suite that passes with the target function emptied is not a
check. Every test here is one of those two, or the silence rule: a sweep
that found nothing says so.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from ghost_buster import serum
from ghost_buster.serum import BLIND, COVERED, UNKNOWN

APP = '''ALLOWED = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]


def covered(items):
    out = []
    for item in items:
        if item in ALLOWED:
            out.append(item)
    return out


def blind(items):
    out = []
    for item in items:
        if item in ALLOWED:
            out.append(item.upper())
    return out
'''

TESTS = '''from app import covered


def test_covered_filters():
    assert covered(["a", "z"]) == ["a"]
'''


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _patient(tmp_path, app=APP, tests=TESTS) -> Path:
    root = tmp_path / "patient"
    root.mkdir()
    (root / "app.py").write_text(app)
    if tests is not None:
        (root / "test_app.py").write_text(tests)
    (root / "pyproject.toml").write_text('[project]\nname = "p"\nversion = "0.1.0"\n')
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
    return root


def _files(root: Path):
    return sorted(root.glob("*.py"))


# ------------------------------------------------------------- the surface

def test_a_site_carries_the_function_that_holds_it():
    """Without the enclosing function there is nothing to empty, so there
    is no verification to run and the dose is unofferable."""
    tree = ast.parse(APP)
    assert serum.enclosing_function(tree, 7) == "covered"
    assert serum.enclosing_function(tree, 16) == "blind"
    assert serum.enclosing_function(tree, 1) == ""


def test_the_innermost_function_wins():
    src = "class C:\n    def m(self):\n        def inner():\n            x = 1\n        return inner\n"
    assert serum.enclosing_function(ast.parse(src), 4) == "C.m.inner"


def test_the_sweep_reports_itself_when_it_finds_nothing(tmp_path):
    """Principle 1, in the feature that showcases it. The first serum
    appended a pitstop count only when there were pitstops, so a clean
    sweep and a sweep that never happened printed identically."""
    root = _patient(tmp_path, app="x = 1\n", tests=None)
    report = serum.assess(root, _files(root))
    assert report.sites == []
    text = "\n".join(serum.render(report))
    assert "enhancement surface: none" in text
    assert "swept" in text


# ---------------------------------------------------------------- the dose

def test_a_site_its_suite_can_see_is_verifiable(tmp_path):
    root = _patient(tmp_path)
    report = serum.assess(root, _files(root), link_siblings=False)
    by_function = {d.site.function: d for d in report.doses}
    assert report.assessed, report.verification_reason
    assert by_function["covered"].verdict == COVERED
    assert "covered() emptied" in by_function["covered"].reason


def test_a_site_its_suite_cannot_see_gets_no_dose(tmp_path):
    """The point of the whole grading. `blind()` is never called by a test,
    so the suite passes with its body replaced by `pass`, so 'the tests
    still pass' after an enhancement there would prove nothing."""
    root = _patient(tmp_path)
    report = serum.assess(root, _files(root), link_siblings=False)
    by_function = {d.site.function: d for d in report.doses}
    assert by_function["blind"].verdict == BLIND
    assert len(report.covered) == 1 and len(report.blind) == 1


def test_a_patient_whose_suite_does_not_pass_in_the_copy_gets_no_verdicts(tmp_path):
    """Fail closed. A baseline that is not green makes every verdict below
    it meaningless, so none is offered and the reason is said once."""
    root = _patient(tmp_path, tests=TESTS + "\n\ndef test_fails():\n    assert False\n")
    report = serum.assess(root, _files(root), link_siblings=False)
    assert not report.assessed
    assert "does not pass in a scratch copy" in report.verification_reason
    assert all(d.verdict == UNKNOWN for d in report.doses)
    assert "NOT ASSESSED" in "\n".join(serum.render(report))


def test_a_budget_that_runs_out_is_reported_per_site_not_dropped(tmp_path):
    root = _patient(tmp_path)
    report = serum.assess(root, _files(root), budget=0.001, link_siblings=False)
    assert report.doses, "the sites are still reported"
    assert all(d.verdict == UNKNOWN for d in report.doses)
    assert all("budget" in d.reason for d in report.doses)
    assert "budget" in report.verification_reason


def test_a_site_at_module_scope_says_why_it_cannot_be_assessed(tmp_path):
    """Not silence, and not a verdict either: there is no function body to
    empty, so the check this serum runs does not apply, and it says which."""
    root = _patient(tmp_path)
    at_module_scope = serum.Site(root / "app.py", 1, "list_membership_in_loop",
                                 "`in ALLOWED`", function="")
    doses, assessed, _ = serum.assess_doses(root, [at_module_scope],
                                            link_siblings=False)
    assert assessed
    assert doses[0].verdict == UNKNOWN
    assert "module scope" in doses[0].reason


# ------------------------------------- the two decisions, on their own

def test_the_budget_leaves_room_for_the_run_it_is_about_to_start():
    """Asking whether the time already spent is under budget would start a
    run that cannot finish and then kill it, turning a site that could have
    been graded into an unknown -- and unknown counts against the patient."""
    assert not serum.over_budget(spent=10.0, baseline_seconds=5.0, budget=120.0)
    assert serum.over_budget(spent=10.0, baseline_seconds=5.0, budget=12.0)
    assert not serum.over_budget(spent=10.0, baseline_seconds=5.0, budget=15.1)


def test_a_run_that_did_not_finish_establishes_nothing():
    """The failing-closed case, stated where it can be read. A crashed or
    timed-out run is not evidence that the suite is blind."""
    assert serum.verdict_for(0, "f")[0] == BLIND
    assert serum.verdict_for(1, "f")[0] == COVERED
    assert serum.verdict_for(2, "f")[0] == COVERED
    verdict, reason = serum.verdict_for(-1, "f", tail="timed out")
    assert verdict == UNKNOWN
    assert "did not complete" in reason and "timed out" in reason


def test_the_verdict_names_the_function_it_emptied():
    """A verdict with no subject is unactionable: the reader has to know
    which function the suite could or could not see."""
    assert "covered() emptied" in serum.verdict_for(1, "covered")[1]
    assert "blind() emptied" in serum.verdict_for(0, "blind")[1]


# ----------------------------------------------------- whose numbers those are

def test_the_scans_own_work_is_labelled_as_the_scans():
    """The defect this release exists to fix: these are ghost_buster's
    parses and reads, and they used to print under the patient's name with
    nothing saying so."""
    loud = ["measured redundancy (same input, done again):",
            "    ast.parse   100 calls,   10 distinct,   90 repeated  4.00s (52% of the run)"]
    report = serum.SerumReport(ran=True, files_swept=1)
    report.scan_work = loud
    report.scan_work_material = serum._material(loud)
    text = "\n".join(serum.render(report))
    assert "ghost_buster's, not the patient's" in text
    assert "52% of the run" in text


def test_immaterial_scan_numbers_are_summarised_not_printed():
    """13 repeated reads costing 0.00s on a four-file patient is not a
    finding about anything. Measured on fortress-kernel 2026-09-17, which
    is what the old serum printed as its entire output."""
    quiet = ["measured redundancy (same input, done again):",
             "    read   17 calls,    4 distinct,   13 repeated  0.00s (0% of the run)"]
    assert not serum._material(quiet)
    report = serum.SerumReport(ran=True, files_swept=4)
    report.scan_work = quiet
    report.scan_work_material = False
    text = "\n".join(serum.render(report))
    assert "nothing repeated enough to act on" in text
    assert "17 calls" not in text


def test_a_serum_that_did_not_run_says_so():
    assert "not run" in "\n".join(serum.render(serum.SerumReport(ran=False, reason="no table")))
