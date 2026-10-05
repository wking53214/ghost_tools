"""The second remedy, and the first one that can close a finding.

WHY THIS REMEDY EXISTS (v1.7.0)

The first operation on a full-size patient made one cut, changed four
files and healed nothing. Annotating a name disagreement records it
rather than resolving it, so the finding survives the cut by
construction. The remedy set was documentary; the surgeon could not
treat anything.

A documented test count is the one pool in the library where the correct
value is fully determined by evidence the tool already holds. A README
claiming 390 tests beside a suite that collects 1727 is wrong about a
number somebody just measured, and there is no judgement in the
difference. That is what makes it safe to automate, and why it comes
before the larger pools: 416 dead-code findings and 399 vestigial-name
findings each need a judgement the tree does not contain.

WHAT THESE TESTS HOLD

The happy path is one assertion. Everything else here is a refusal or a
verification, because a remedy that writes to somebody's repository is
mostly the reasons it declines to.

The refusals each protect a different thing. A suite that is not green
protects the sentence around the number: "1727 tests passing" beside
forty failures is accurate arithmetic and a false claim, and rewriting
the digits would make it look checked. A claim that is a delta, a
recorded transition or a quotation protects text that was true when
written. An ambiguous line protects against writing into a span the
finding did not name.

The verifications protect the patient. After writing, the file is read
back and must match what was meant, the claim must read the measured
number, and the file's length must have moved by exactly the difference
between the two numbers. A remedy that cannot prove what it wrote raises,
and the tree goes back.
"""
from __future__ import annotations

import subprocess

import pytest

from ghost_buster.operate import RemedyFailed, _remedy_doc_counts, operate
from ghost_buster.ledger import RAN
from ghost_buster.mechanical import run_all
from ghost_buster.schema import (Category, Evidence, Finding, Layer, Severity,
                                 Status)


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _claim(root, path, documented, collected, passed=None, line=1,
           writable="yes", unexamined=0):
    """The correlation finding the remedy acts on, built as correlate.py
    builds it. Constructed here rather than produced by a scan so each test
    can vary one field; a test that runs the whole pipeline to reach this
    point would be measuring the pipeline."""
    return Finding(
        detector="doc_count_contradicted_by_run",
        category=Category.DOC_DRIFT,
        layer=Layer.MECHANICAL,
        severity=Severity.MINOR,
        status=Status.CONFIRMED,
        summary=f"'{path}' claims {documented} test(s); the suite collects {collected}",
        detail="",
        attributes={
            "documented_count": str(documented),
            "collected": str(collected),
            "passed": str(collected if passed is None else passed),
            # The detector's verdict, carried by the connector. Tests that
            # are about a different refusal set it to yes so that refusal is
            # the only thing under examination.
            "writable": writable,
            "not_writable_because": "" if writable == "yes" else "a dated or versioned document",
            # Test files that produced no result either way. Zero by
            # default, so every test written before this existed still
            # describes the run it always described.
            "unexamined": str(unexamined),
        },
        evidence=Evidence(file=str(root / path), line_start=line, line_end=line),
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# thing\n\nThe suite has 390 tests passing.\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "admit")
    return root


# ------------------------------------------------------------ the happy path

def test_a_stale_count_is_replaced_with_the_measured_one(repo):
    changed, note = _remedy_doc_counts(
        repo, [], [_claim(repo, "README.md", 390, 1727, line=3)])
    assert changed == 1
    assert "1727" in note or "1 documented" in note
    assert (repo / "README.md").read_text() == "# thing\n\nThe suite has 1727 tests passing.\n"


def test_nothing_but_the_number_moves(repo):
    """The sentence around the claim is the author's. Only digits change."""
    before = (repo / "README.md").read_text()
    _remedy_doc_counts(repo, [], [_claim(repo, "README.md", 390, 1727, line=3)])
    after = (repo / "README.md").read_text()
    assert before.replace("390", "") == after.replace("1727", "")


def test_no_claims_means_no_cut(repo):
    assert _remedy_doc_counts(repo, [], []) == (0, "")


def test_a_finding_from_another_detector_is_not_touched(repo):
    """It acts on the correlation, which exists only when --tests ran. A
    static drift finding carries a lower bound, and writing a lower bound
    would replace a stale number with a wrong one."""
    drift = _claim(repo, "README.md", 390, 1727, line=3)
    drift.detector = "doc_test_count_drift"
    assert _remedy_doc_counts(repo, [], [drift]) == (0, "")
    assert "390" in (repo / "README.md").read_text()


# ---------------------------------------------------------------- refusals

def test_a_suite_that_is_not_green_goes_to_a_human(repo):
    changed, note = _remedy_doc_counts(
        repo, [], [_claim(repo, "README.md", 390, 1727, passed=1687, line=3)])
    assert changed == 0
    # No cut, so no note: a remedy that wrote nothing does not describe a
    # cut in the commit message of one.
    assert note == ""
    assert "390" in (repo / "README.md").read_text()


@pytest.mark.parametrize("sentence,shape", [
    ("This release gained 390 tests.", "delta"),
    ("It went from 200 to 390 tests, then settled.", "transition"),
    ('The other project claimed "390 tests".', "quotation"),
    # Each of these names the suite, so `why_not_writable` passes them and
    # `claim_shape` is the only thing left to refuse them. Without one of
    # these the claim-shape re-check can be deleted with this test still
    # green, because the writability re-derivation added in 1.7.1 declines
    # the three above for saying nothing about what they count. Measured:
    # the mutant survived until these were added.
    ("The test suite gained 390 tests this quarter.", "delta, naming the suite"),
    ("The test suite went from 200 to 390 tests.", "transition, naming the suite"),
])
def test_a_claim_that_is_not_a_total_is_left_alone(repo, sentence, shape):
    (repo / "README.md").write_text(f"# thing\n\n{sentence}\n")
    changed, _ = _remedy_doc_counts(
        repo, [], [_claim(repo, "README.md", 390, 1727, line=3)])
    assert changed == 0, f"a {shape} was overwritten"
    assert "390" in (repo / "README.md").read_text()


def test_two_identical_claims_on_one_line_are_ambiguous(repo):
    """Ambiguity is the reason, and the only reason.

    The sentence names the suite on purpose. Without that, `why_not_writable`
    refuses it for saying nothing about what it counts, and the ambiguity
    check could be deleted with this test still passing -- which it was, and
    the mutant survived until the wording was fixed.
    """
    (repo / "README.md").write_text(
        "# thing\n\nThe test suite has 390 tests, and still 390 tests, "
        "collected.\n")
    changed, _ = _remedy_doc_counts(
        repo, [], [_claim(repo, "README.md", 390, 1727, line=3)])
    assert changed == 0
    assert (repo / "README.md").read_text().count("390") == 2


def test_a_file_outside_the_patient_is_refused(repo, tmp_path):
    """Containment is the reason, and the only reason.

    The wording below is an ordinary live claim on purpose: an earlier
    version of this test said "Claims 390 tests passing", which the
    named-subject rule declines all by itself, so the test passed while the
    containment check was removed.

    The FILENAME is README.md for the same reason, and it is the second time
    this test has had to be rescued from a guard that covered for the one it
    is about. `why_not_writable` is now re-derived from the resolved file at
    write time (v1.7.1), and its first question is whether the name is a
    current-state document -- so an outside file called `elsewhere.md` was
    refused for its NAME, and the containment check could be deleted with
    this test still passing. Measured: the mutant survived.
    """
    outside = tmp_path / "README.md"
    outside.write_text("The test suite has 390 tests passing.\n")
    claim = _claim(repo, "README.md", 390, 1727, line=1)
    claim.evidence.file = str(outside)
    claim.evidence.absolute_file = str(outside)
    changed, _ = _remedy_doc_counts(repo, [], [claim])
    assert changed == 0
    assert outside.read_text() == "The test suite has 390 tests passing.\n"


def test_a_line_past_the_end_of_the_file_is_refused(repo):
    changed, _ = _remedy_doc_counts(
        repo, [], [_claim(repo, "README.md", 390, 1727, line=99)])
    assert changed == 0


# ----------------------------------------------------- the verification

def test_a_number_that_did_not_land_raises(repo, monkeypatch):
    """First verification. If the claim on disk does not read the measured
    number afterwards, the write failed or went somewhere else, and the
    remedy raises rather than reporting a cut it cannot prove."""
    import pathlib
    real = pathlib.Path.write_text

    def write_the_old_number(self, data, *a, **k):
        return real(self, data.replace("1727", "390"), *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", write_the_old_number)
    with pytest.raises(RemedyFailed) as failure:
        _remedy_doc_counts(repo, [], [_claim(repo, "README.md", 390, 1727, line=3)])
    assert "does not read 1727" in str(failure.value)


def test_a_write_that_disturbs_the_rest_of_the_file_raises(repo, monkeypatch):
    """Second verification, and orthogonal to the first. The number landed
    correctly here; something else moved with it, and everything outside
    the claim belongs to whoever wrote it."""
    import pathlib
    real = pathlib.Path.write_text

    def also_edit_the_heading(self, data, *a, **k):
        return real(self, data.replace("# thing", "# THING"), *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", also_edit_the_heading)
    with pytest.raises(RemedyFailed) as failure:
        _remedy_doc_counts(repo, [], [_claim(repo, "README.md", 390, 1727, line=3)])
    assert "outside the claim changed" in str(failure.value)


# ------------------------------------------------------ end to end, on a table

def test_the_operation_heals_the_static_finding(tmp_path):
    """The point of the whole remedy: a finding closes.

    The static detector flags a documented count far below the number of
    test_* functions it can see. Once the doc says the measured number,
    that detector has nothing to report, and the re-examination records it
    as healed rather than merely annotated.
    """
    root = tmp_path / "patient"
    (root / "Tests").mkdir(parents=True)
    (root / "Tests" / "test_all.py").write_text(
        "".join(f"def test_case_{i}():\n    assert True\n\n" for i in range(60)))
    (root / "README.md").write_text("# patient\n\nA suite of 4 tests, passing.\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "admit")

    files = sorted(root.rglob("*.py")) + sorted(root.rglob("*.md"))
    findings = run_all(files)
    drift = [f for f in findings if f.detector == "doc_test_count_drift"]
    assert drift, "the fixture does not produce the finding this test is about"

    findings.append(_claim(root, "README.md", 4, 60, line=3))
    op = operate(root, files, findings, {"tests": RAN, "secrets": RAN},
                 branch="ghost/op")

    # annotate runs first and writes its own table into the README, so it
    # makes a cut too. What matters is which cut closed the finding.
    cuts = {c.remedy: c for c in op.cuts}
    assert "doc_counts" in cuts, f"the remedy did not fire: {sorted(cuts)}"
    assert drift[0].id in cuts["doc_counts"].closed, (
        "the static finding did not close; "
        f"doc_counts closed {cuts['doc_counts'].closed}")
    # The cut lives on the operation branch. The tree went back to main, so
    # the working copy still reads 4 and the branch is where the work is.
    assert "60 tests" in _git(root, "show", "ghost/op:README.md")
    assert "4 tests" in (root / "README.md").read_text()
    assert op.came_in_untouched
    assert _git(root, "branch", "--show-current") == "main"


# ------------------------------- the fifth claim shape, found by this remedy

def test_a_count_belonging_to_another_project_is_not_a_claim_about_ours():
    """The shape this remedy found, on the way to shipping.

    ghost_tools' own CHANGELOG had exactly one live test-count claim in the
    whole repository: "(herald 390 tests, observe-perceive 565, gsa-815 19
    modules, sentinel_os 968 ...)", the corpus a feature was calibrated
    against. Four other projects' suites, listed as evidence.

    Every earlier shape passed it, so the detector raised a finding, the
    connector confirmed it with this suite's measured number, and the
    remedy was one commit from writing 1727 over another project's true
    390. Fixed in claim_shape rather than in the remedy, because the
    detector and the connector were both wrong about it too.
    """
    from ghost_buster.mechanical import claim_shape
    real = "calibrated on four real suites before shipping (herald "
    assert claim_shape(real) == "attributed to a named subject"


@pytest.mark.parametrize("before", [
    "The suite has ", "A suite of ", "", "Tests: ", "It now collects ",
    "and still ", "with all ", "roughly ",
])
def test_an_ordinary_lead_in_is_still_a_claim_about_this_suite(before):
    """The other half. A rule that silences a real claim is worse than the
    false positive it removes, because nothing then tells anyone the doc
    is stale."""
    from ghost_buster.mechanical import claim_shape
    assert claim_shape(before) is None


def test_the_new_shape_silences_nothing_that_was_already_measured():
    """Measured before shipping, against the 1.2.4 library sweep: of 65
    drift findings across 38 repositories, this rule silences zero. It
    removes one false positive, in this repository, and costs nothing
    elsewhere. If that ever stops being true the trade has changed and
    somebody should look again."""
    from ghost_buster.mechanical import claim_shape
    already_measured = [
        "The suite has ", "collected ", "There are ", "now ", "of ",
        "and ", "with ", "totalling ", "reaching ", "",
    ]
    assert [claim_shape(c) for c in already_measured] == [None] * len(already_measured)


# ------------------------------- reporting and writing are different questions

def test_a_claim_the_detector_refused_is_never_written(repo):
    """The gate that makes the remedy safe by construction rather than by
    coincidence. Every earlier refusal in this file is the remedy noticing
    something itself; this one is the remedy obeying a verdict the detector
    reached with the document in front of it."""
    changed, note = _remedy_doc_counts(
        repo, [], [_claim(repo, "README.md", 390, 1727, line=3, writable="no")])
    assert changed == 0
    assert note == ""
    assert "390" in (repo / "README.md").read_text()


@pytest.mark.parametrize("filename,before,after,reason", [
    ("FINAL_STATUS.md", "the suite has ", " tests", "not a current-state document"),
    ("CHANGELOG.md", "the suite has ", " tests", "not a current-state document"),
    ("README.md", "run `test_circuit_breaker.py`, ", " tests",
     "scoped to a file, command or subset"),
    ("README.md", "| **AUGUR** (", " tests in the suite", "a table row or labelled list entry"),
    ("README.md", "the July 2026 governance status recorded ", " tests in the suite",
     "a dated or historical sentence"),
    ("README.md", "covered by ", " tests", "does not assert about the whole suite"),
])
def test_each_signal_names_its_own_reason(filename, before, after, reason):
    """Six signals, each with a reason a human can read. Every one was a
    real false positive in the library before it was a rule."""
    from ghost_buster.mechanical import why_not_writable
    assert why_not_writable(filename, before, after) == reason


@pytest.mark.parametrize("before,after", [
    ("The project ships with ", " tests passing across the suite."),
    ("## Tests\n\n", " tests, all passing."),
    ("Test suite: ", " tests passing"),
])
def test_the_shapes_a_real_claim_takes_are_writable(before, after):
    """The other half, and the half that matters more. A predicate that
    refuses everything is not precise, it is broken. The first of these is
    the one recorded true positive, and it needs the text AFTER the number:
    "135 tests passing across the suite" names its subject last."""
    from ghost_buster.mechanical import why_not_writable
    assert why_not_writable("README.md", before, after) is None


def test_a_bare_count_saying_nothing_is_refused():
    """Deliberate, and the case the marked block exists for. "429 tests,
    all passing." alone on a line could be the suite or a section, and the
    text does not say. A project that wants that number maintained can hand
    the tool a block to own instead of having its prose guessed at."""
    from ghost_buster.mechanical import why_not_writable
    assert why_not_writable("README.md", "\n", " tests, all passing.\n") == \
        "does not assert about the whole suite"


# ---------------------------------------------------------------------------
# The writability verdict is re-derived at the write, from the file being
# written. (v1.7.1)
#
# `finding.attributes["writable"]` was decided during the workup, about the
# text as it was then and the path the scan walked. Both can have moved by
# the time this runs, and an adversarial harness moved both.
# ---------------------------------------------------------------------------

def test_a_claim_that_became_dated_during_the_workup_is_refused(repo):
    """The repository's own suite runs during the workup -- this tool starts
    it -- so a test that rewrites a document executes inside the window
    between the reading and the writing.

    The finding still says `writable: yes`, decided about a live sentence
    that no longer exists. Re-running `claim_shape` is not enough: that
    answers the REPORTING question, and a dated sentence passes it. The
    predicate that authorises a write is the one that has to be re-asked.
    """
    (repo / "README.md").write_text(
        "# thing\n\nAs of 2026-01-14 the test suite had 390 tests, all "
        "passing.\n")
    changed, _ = _remedy_doc_counts(
        repo, [], [_claim(repo, "README.md", 390, 1727, line=3)])
    assert changed == 0
    assert "390" in (repo / "README.md").read_text()


def test_writability_is_judged_on_the_file_that_is_actually_written(repo):
    """README.md is a link to a document whose own name the same rule
    refuses. The verdict was reached about the link and the bytes go to the
    target, so a file that is not a current-state document was rewritten --
    while the finding named a path whose history shows no change."""
    (repo / "docs").mkdir(exist_ok=True)
    target = repo / "docs" / "project_notes.md"
    target.write_text("# notes\n\nThe test suite has 390 tests, all passing.\n")
    link = repo / "LINKED.md"
    link.symlink_to(target)
    claim = _claim(repo, "LINKED.md", 390, 1727, line=3)
    changed, _ = _remedy_doc_counts(repo, [], [claim])
    assert changed == 0
    assert "390" in target.read_text()


def test_a_live_claim_is_still_written(repo):
    """The re-derivation must not close the feature it guards."""
    (repo / "README.md").write_text(
        "# thing\n\nThe test suite has 390 tests, all passing.\n")
    changed, _ = _remedy_doc_counts(
        repo, [], [_claim(repo, "README.md", 390, 1727, line=3)])
    assert changed == 1
    assert "1727 tests" in (repo / "README.md").read_text()


# ---------------------------------------------------------------------------
# A suite that did not finish running (v1.7.3)
#
# `passed == collected` is satisfied by a suite with a whole file missing
# from it: a module that cannot be imported contributes to neither side, so
# the subtraction says green.
#
# Measured by an adversarial harness against 1.7.2: a README was rewritten
# to "The test suite has 30 tests, all passing." over a repository where one
# test file could not be collected -- and the SAME run reported the blocked
# module as a finding of its own, naming the missing import. The tool knew
# and certified anyway.
#
# That is the one failure a reader cannot catch by looking at the diff.
# Every byte is in a permitted place and the document is now false.
# ---------------------------------------------------------------------------

def test_a_suite_that_did_not_finish_running_is_not_rewritten(repo):
    readme = repo / "README.md"
    readme.write_text("# thing\n\nThe test suite has 12 tests, all passing.\n")
    changed, note = _remedy_doc_counts(
        repo, [readme],
        [_claim(repo, "README.md", 12, 30, line=3, unexamined=1)])
    assert changed == 0
    assert "12 tests" in readme.read_text()


def test_the_refusal_says_which_number_is_not_a_total(repo):
    """A refusal a human cannot act on is a refusal they will override.

    Reported BESIDE a real cut, because that is the only way a remedy's
    note reaches anybody: a run that declines everything returns no note at
    all, which is a limitation of the operation flow rather than of this
    guard and is recorded in `test_write_containment.py`.

    The human is not left with nothing in that case. The finding itself is
    MAJOR and its detail says why subtracting one number from the other
    reads as green. The note is the second telling, not the only one.
    """
    readme = repo / "README.md"
    readme.write_text("# thing\n\nThe test suite has 12 tests, all passing.\n")
    other = repo / "CONTRIBUTING.md"
    other.write_text("# contributing\n\nThe test suite has 9 tests, all passing.\n")
    _, note = _remedy_doc_counts(
        repo, [readme, other],
        [_claim(repo, "README.md", 12, 30, line=3, unexamined=2),
         _claim(repo, "CONTRIBUTING.md", 9, 30, line=3)])
    assert "did not finish running" in note or "not a total" in note
    assert "12 tests" in readme.read_text(), "the unexamined claim stood"


def test_a_suite_that_fully_ran_is_still_rewritten(repo):
    """The control. This refusal must not close the remedy it guards."""
    readme = repo / "README.md"
    readme.write_text("# thing\n\nThe test suite has 12 tests, all passing.\n")
    changed, _ = _remedy_doc_counts(
        repo, [readme],
        [_claim(repo, "README.md", 12, 30, line=3, unexamined=0)])
    assert changed == 1
    assert "30 tests" in readme.read_text()


def test_a_finding_that_never_heard_of_unexamined_behaves_as_before(repo):
    """An absent attribute reads as zero rather than as a refusal. A finding
    from an older run, or from a connector that does not publish it, must
    not be declined on a number nobody supplied."""
    readme = repo / "README.md"
    readme.write_text("# thing\n\nThe test suite has 12 tests, all passing.\n")
    claim = _claim(repo, "README.md", 12, 30, line=3)
    del claim.attributes["unexamined"]
    changed, _ = _remedy_doc_counts(repo, [readme], [claim])
    assert changed == 1


def test_a_non_numeric_unexamined_does_not_decline_and_does_not_raise(repo):
    """Garbage in the attribute is not evidence of an unexamined file. It
    must not crash the remedy and must not be read as a refusal -- a guard
    that fires on malformed input fires on the wrong repositories."""
    readme = repo / "README.md"
    readme.write_text("# thing\n\nThe test suite has 12 tests, all passing.\n")
    claim = _claim(repo, "README.md", 12, 30, line=3)
    claim.attributes["unexamined"] = "several"
    changed, _ = _remedy_doc_counts(repo, [readme], [claim])
    assert changed == 1
