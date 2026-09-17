"""Source history, and the difference between an oversight and an act.

WHY THIS EXISTS

`unreachable_declared_state` can see that an enum member is not produced.
From one snapshot it cannot see WHY, and the two reasons want different
answers: nobody wired it up (an oversight), or something used to produce it
and a change removed the production while leaving the declaration standing
(a regression wearing an oversight's clothes).

THE CASE THIS WAS BUILT FOR

Relocation. When the last production of a member moves out of library code
and into a test, the state does not become more reachable -- the evidence
that it is unreachable becomes quieter. It is the shape of quieting a
finding rather than answering it.

Note what that does to the snapshot signal. "Only a test produces it", read
without a clock, is weak evidence of nothing much. Read against history --
a test produces it NOW and library code produced it BEFORE -- it is the
strongest signal in this detector. The same observation, escalating instead
of excusing, purely because the timeline is available.

WHAT IS ASSERTED HERE

Real repositories, real commits, real `git log -S`. A stub would prove the
enum has four members and nothing about whether the question can be
answered against git as it actually behaves.
"""
from __future__ import annotations

import subprocess

from ghost_buster import forensics
from ghost_buster.forensics import Provenance

ENUMS = '''\
from enum import Enum


class Phase(str, Enum):
    BUILD = "build"
    GONE = "gone"
'''

LIB_BOTH = '''\
from enums import Phase


def a():
    return Phase.BUILD


def b():
    return Phase.GONE
'''

LIB_ONE = '''\
from enums import Phase


def a():
    return Phase.BUILD
'''

TEST_PRODUCES = '''\
from enums import Phase


def test_gone():
    return Phase.GONE
'''


def _run(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True)


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _run(root, "init", "-q", ".")
    _run(root, "config", "user.email", "t@example.invalid")
    _run(root, "config", "user.name", "t")
    _run(root, "config", "commit.gpgsign", "false")
    return root


def _commit(root, message, **files):
    for name, body in files.items():
        (root / name.replace("__", ".")).write_text(body)
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", message, "--no-gpg-sign")


def _analyse(sources):
    """The real analysis, imported rather than reimplemented.

    If this were a stub, every assertion below would be about the stub. The
    whole value of comparing a past revision to HEAD is that the same
    question is asked at both, so the test has to use the same function the
    detector uses.
    """
    from ghost_buster.mechanical import _analyse_sources
    return _analyse_sources(sources)


def _why(root, budget=forensics.BUDGET):
    return forensics.provenance(root, "Phase", "GONE",
                                analyse=_analyse, budget=budget)


# ---------------------------------------------------------------------------
# The three histories
# ---------------------------------------------------------------------------

def test_a_member_nothing_ever_produced(tmp_path):
    """Declared and never wired up. An oversight, and reported as one."""
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_ONE)
    assert _why(root) is Provenance.NEVER_PRODUCED


def test_a_production_removed_from_library(tmp_path):
    """It used to work. That is a regression, not an oversight, and the
    declaration left behind is a claim the code stopped backing."""
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
    _commit(root, "two", lib__py=LIB_ONE)
    assert _why(root) is Provenance.REMOVED_FROM_LIBRARY


def test_a_production_relocated_into_a_test(tmp_path):
    """THE ONE THIS MODULE EXISTS FOR.

    The production moved from library code into a test in one commit. The
    state is no more reachable than before; only the evidence moved.
    """
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
    _commit(root, "two", lib__py=LIB_ONE, test_gone__py=TEST_PRODUCES)
    assert _why(root) is Provenance.RELOCATED_TO_TESTS


def test_relocation_is_distinguished_from_plain_removal(tmp_path):
    """Both end with library code not producing it. Only one of them put the
    production somewhere quieter, and collapsing the two would lose exactly
    the signal this is for."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    moved, gone = _repo(a), _repo(b)
    for root in (moved, gone):
        _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
    _commit(moved, "two", lib__py=LIB_ONE, test_gone__py=TEST_PRODUCES)
    _commit(gone, "two", lib__py=LIB_ONE)
    assert _why(moved) is not _why(gone)


def test_a_test_that_always_produced_it_is_not_a_relocation(tmp_path):
    """The test produced it before the removal too, so nothing moved. This
    is a removal, and calling it a relocation would manufacture intent out
    of a test that was simply already there."""
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH,
            test_gone__py=TEST_PRODUCES)
    _commit(root, "two", lib__py=LIB_ONE)
    assert _why(root) is Provenance.REMOVED_FROM_LIBRARY


# ---------------------------------------------------------------------------
# Not knowing, said out loud
# ---------------------------------------------------------------------------

def test_outside_a_repository_there_is_no_root(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "m.py").write_text("x = 1\n")
    assert forensics.repo_root([plain / "m.py"]) is None


def test_a_root_that_is_not_a_repository_is_unknown(tmp_path):
    """Every way of failing to read history answers UNKNOWN. A caller that
    could tell them apart would be tempted to treat some as answers."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _why(plain) is Provenance.UNKNOWN


def test_running_out_of_budget_is_unknown_not_never(tmp_path):
    """THE ONE THAT KEEPS THIS HONEST.

    Reporting the end of the search as the end of the history is the exact
    mistake this tool exists to find in other people's code. When the walk
    stops early the answer is that it does not know.
    """
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_ONE)
    # Three commits that change the text's count without ever producing it.
    for n, body in enumerate([
            "from enums import Phase\ndef c(x):\n    return x is Phase.GONE\n",
            "from enums import Phase\ndef c(x):\n    return x is not None\n",
            "from enums import Phase\ndef c(x):\n    return x is Phase.GONE\n"]):
        _commit(root, "cmp%d" % n, cmp__py=body)
    assert _why(root, budget=1) is Provenance.UNKNOWN
    # With the budget to finish, it answers.
    assert _why(root, budget=50) is Provenance.NEVER_PRODUCED


def test_unknown_is_not_never_produced():
    """Stated as an identity because the whole design rests on it: a caller
    collapsing these two would be inventing history it could not read."""
    assert Provenance.UNKNOWN is not Provenance.NEVER_PRODUCED


def test_repo_root_finds_the_top_from_a_nested_file(tmp_path):
    root = _repo(tmp_path)
    nested = root / "pkg" / "deep"
    nested.mkdir(parents=True)
    (nested / "m.py").write_text("x = 1\n")
    _commit(root, "one", enums__py=ENUMS)
    found = forensics.repo_root([nested / "m.py"])
    assert found is not None and found.resolve() == root.resolve()


def test_a_root_commit_has_no_parent_and_does_not_crash(tmp_path):
    """The parent of a root commit is spelled "" and produces nothing, which
    is TRUE and is not the same as unreadable.

    Reached by putting the member's name in the root commit as a comparison,
    so the walk runs all the way back to a commit with no parent instead of
    answering earlier. Without that the empty-parent branch is a guard no
    test can fail on, and an unprovable guard is worse than no guard: it
    looks checked.
    """
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_ONE,
            cmp__py="from enums import Phase\ndef c(x):\n    return x is Phase.GONE\n")
    _commit(root, "two", cmp__py="def c(x):\n    return x is None\n")
    assert forensics._parent(root, "HEAD~1") == ""
    assert _why(root) is Provenance.NEVER_PRODUCED


# ---------------------------------------------------------------------------
# What the detector does with the answer
# ---------------------------------------------------------------------------

def _severity(root):
    from pathlib import Path
    from ghost_buster.mechanical import detect_unreachable_declared_state
    files = sorted(p for p in Path(root).rglob("*.py") if ".git" not in p.parts)
    found = [f for f in detect_unreachable_declared_state(files)
             if f.attributes.get("member") == "GONE"]
    assert len(found) == 1, found
    return found[0].severity, found[0].attributes["provenance"]


def test_history_raises_the_severity_of_a_removal(tmp_path):
    """An oversight is MINOR. A removal is MAJOR. Same snapshot, different
    history, and the history is what separates them."""
    from ghost_buster.schema import Severity
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    never, removed = _repo(a), _repo(b)
    _commit(never, "one", enums__py=ENUMS, lib__py=LIB_ONE)
    _commit(removed, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
    _commit(removed, "two", lib__py=LIB_ONE)
    assert _severity(never) == (Severity.MINOR, "never_produced")
    assert _severity(removed) == (Severity.MAJOR, "removed_from_library")


def test_relocation_into_a_test_raises_rather_than_lowers(tmp_path):
    """THE INVERSION.

    Version 1.7.7 read "only a test produces it" as grounds to LOWER the
    severity. Against history the same observation is grounds to raise it,
    because the interesting question was never whether a test produces the
    member but whether library code stopped.
    """
    from ghost_buster.schema import Severity
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
    _commit(root, "two", lib__py=LIB_ONE, test_gone__py=TEST_PRODUCES)
    severity, provenance = _severity(root)
    from ghost_buster.baseline import _rank
    assert provenance == "relocated_to_tests"
    assert severity is Severity.MAJOR
    # Ordered by the project's own rank, not by `<`. Severity is a str Enum,
    # so "major" < "minor" compares alphabetically and would pass here by
    # coincidence while asserting nothing about severity.
    assert _rank(severity) < _rank(Severity.MINOR)


def test_history_off_asks_git_nothing(tmp_path, monkeypatch):
    """`history=False` has to mean it, or a caller that needs a pure function
    of the files on disk does not have one."""
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
    _commit(root, "two", lib__py=LIB_ONE)

    def explode(*a, **k):  # pragma: no cover - the point is it is not called
        raise AssertionError("git was consulted with history=False")

    monkeypatch.setattr(forensics, "repo_root", explode)
    monkeypatch.setattr(forensics, "provenance", explode)

    from ghost_buster.mechanical import detect_unreachable_declared_state
    files = sorted(p for p in root.rglob("*.py") if ".git" not in p.parts)
    found = detect_unreachable_declared_state(files, history=False)
    assert [f.attributes["provenance"] for f in found] == ["unknown"]


# ---------------------------------------------------------------------------
# The failure paths, exercised rather than assumed
# ---------------------------------------------------------------------------

def test_git_failing_to_launch_is_not_an_empty_answer(monkeypatch):
    """If git cannot run at all, `_git` must say so. Returning "" would make
    "no output" and "no git" the same value, and every caller reads no output
    as a real answer."""
    def explode(*a, **k):
        raise OSError("no git here")
    monkeypatch.setattr(subprocess, "run", explode)
    assert forensics._git(forensics.Path("."), "status") is None


def test_an_unreadable_revision_stops_the_walk(tmp_path, monkeypatch):
    """A readable log over unreadable revisions is still unreadable history.
    Skipping the revision and carrying on would let the walk fall off the end
    and answer NEVER_PRODUCED from a search that never looked."""
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
    _commit(root, "two", lib__py=LIB_ONE)
    monkeypatch.setattr(forensics, "_produced_at", lambda *a, **k: None)
    assert _why(root) is Provenance.UNKNOWN


def test_the_transition_is_not_always_the_newest_change(tmp_path):
    """A later commit can touch the member's name without being the commit
    that removed the production -- a comparison added after the fact is
    enough. Examining only the newest candidate would miss the removal and
    report not knowing."""
    root = _repo(tmp_path)
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
    _commit(root, "two", lib__py=LIB_ONE)
    _commit(root, "three",
            cmp__py="from enums import Phase\ndef c(x):\n    return x is Phase.GONE\n")
    assert _why(root) is Provenance.REMOVED_FROM_LIBRARY


def test_not_knowing_never_escalates(tmp_path):
    """THE RULE THAT MAKES THE HISTORY LAYER SAFE TO ADD.

    An unreadable history must grade at the weight of what was actually
    observed -- a declared, unproduced member -- and never at the weight of
    the thing it failed to check. A layer that escalated on UNKNOWN would
    turn "this is not a git repository" into a MAJOR finding.
    """
    from ghost_buster.schema import Severity
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "enums.py").write_text(ENUMS)
    (plain / "lib.py").write_text(LIB_ONE)
    assert forensics.repo_root([plain / "lib.py"]) is None
    severity, provenance = _severity(plain)
    assert provenance == "unknown"
    assert severity is Severity.MINOR


def test_splitting_a_relocation_across_commits_still_escalates(tmp_path):
    """THE OBVIOUS EVASION, AND WHY IT BUYS NOTHING.

    Relocation is recognised when the production leaves library code and
    appears in a test IN THE SAME COMMIT. Anyone wanting to avoid that label
    can simply use two commits, in either order.

    They still land on REMOVED_FROM_LIBRARY, which carries the same severity.
    That is the property worth holding: the precise label is lost, the
    escalation is not, so there is no severity to be gained by splitting the
    change up. A future version that escalated ONLY relocation would create
    exactly the incentive this test says does not exist.
    """
    for first_removal in (True, False):
        root = _repo(tmp_path / ("a" if first_removal else "b"))
        _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
        if first_removal:
            _commit(root, "two", lib__py=LIB_ONE)
            _commit(root, "three", test_gone__py=TEST_PRODUCES)
        else:
            _commit(root, "two", test_gone__py=TEST_PRODUCES)
            _commit(root, "three", lib__py=LIB_ONE)
        assert _why(root) is Provenance.REMOVED_FROM_LIBRARY


def test_the_two_escalations_carry_the_same_weight(tmp_path):
    """Stated directly, because the test above depends on it."""
    from ghost_buster.mechanical import _HISTORY_SEVERITY
    assert (_HISTORY_SEVERITY[Provenance.RELOCATED_TO_TESTS]
            is _HISTORY_SEVERITY[Provenance.REMOVED_FROM_LIBRARY])


def test_a_declaration_outside_the_repository_is_not_asked_about(tmp_path):
    """A scan can be handed files from more than one place -- `--join` reads
    two repositories at once. Asking THIS repository's history about a member
    declared in another one returns a confident NEVER_PRODUCED off a search
    of the wrong history, which is the most misleading answer available."""
    root = _repo(tmp_path / "inside")
    _commit(root, "one", enums__py=ENUMS, lib__py=LIB_BOTH)
    _commit(root, "two", lib__py=LIB_ONE)

    # A DIFFERENT enum name, because members are matched by name: two enums
    # called Phase in one scan collapse into one entry, which is a separate
    # documented limitation and not what this test is about.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "enums.py").write_text(ENUMS.replace("Phase", "Stage"))
    (outside / "lib.py").write_text(LIB_ONE.replace("Phase", "Stage"))

    from ghost_buster.mechanical import detect_unreachable_declared_state
    files = sorted(p for p in root.rglob("*.py") if ".git" not in p.parts)
    files += sorted(outside.rglob("*.py"))
    answers = {f.attributes["enum"]: f.attributes["provenance"]
               for f in detect_unreachable_declared_state(files)}
    # Inside the repository the history is read. Outside it, the honest
    # answer is that this repository's history has nothing to say.
    assert answers == {"Phase": "removed_from_library", "Stage": "unknown"}
