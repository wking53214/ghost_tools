"""A file that moved is not a defect that was fixed.

THE DEFECT THIS FILE GUARDS AGAINST (v1.7.3)

A finding's id is derived from where the finding is. Rename a module byte
for byte and the same defect produces one finding that vanished and one
that is brand new. To a memory keyed by id that reads as a defect resolved
and a different defect opened, and both halves are false:

    the baseline carrying the old id stops matching, so an accepted
      finding starts being reported again and a triaged repository reads
      as untriaged
    the history shows a recovery nobody performed, and the next sighting
      at the new path will be counted as a RETURN

Measured against 1.7.2 by an adversarial harness. Renaming a module is the
most ordinary thing a repository does.

WHY NOT FIX THE ID INSTEAD

There is no content-derived identity that is both stable under a rename
and distinct across files. An id that ignored the path would give two
identical defects in two files one identity, and accepting one would
suppress the other -- the same failure in the worse direction, and
`Tests/test_finding_identity.py` holds that line.

So identity keeps the path and the MEMORY learns to follow it, which is
what the version control system is for.
"""
from __future__ import annotations

import subprocess

import pytest

from ghost_buster.ledger import Ledger, parse_name_status, renames_between
from ghost_buster.schema import (Category, Evidence, Finding, Layer, Severity,
                                 Status)


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def _head(root):
    return _git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "gateway.py").write_text("def unused(a):\n    return a\n")
    (root / "other.py").write_text("x = 1\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    # A test repository must not depend on whoever is running it having a
    # working signing setup. Inherited from global config, signing turned
    # every commit here into a call to an external signer, which failed
    # under load and reported as fifteen errors in a file about renames.
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "tag.gpgsign", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "one")
    return root


def _finding(path, detector="dead_code", summary="'unused' is never referenced"):
    return Finding(
        detector=detector, category=Category.DEAD_CODE, layer=Layer.MECHANICAL,
        severity=Severity.MINOR, status=Status.CONFIRMED,
        summary=summary, detail="",
        evidence=Evidence(file=path, line_start=1, line_end=1))


def _move(root, source, destination):
    _git(root, "mv", source, destination)
    _git(root, "commit", "-q", "-m", "move")
    return _head(root)


# ----------------------------------------------------------- asking git

def test_a_rename_is_reported_as_one(repo):
    before = _head(repo)
    after = _move(repo, "gateway.py", "gateway_v2.py")
    assert renames_between(repo, before, after) == {"gateway.py": "gateway_v2.py"}


def test_an_edit_is_not_a_rename(repo):
    before = _head(repo)
    (repo / "gateway.py").write_text("def unused(a):\n    return a + 1\n")
    _git(repo, "commit", "-qam", "edit")
    assert renames_between(repo, before, _head(repo)) == {}


def test_a_delete_and_an_unrelated_add_is_not_a_rename(repo):
    before = _head(repo)
    (repo / "gateway.py").unlink()
    (repo / "totally_different.py").write_text("import os\nprint(os.name)\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "replace")
    assert "gateway.py" not in renames_between(repo, before, _head(repo))


@pytest.mark.parametrize("before,after", [("", "abc"), ("abc", ""), ("a", "a")])
def test_nothing_to_compare_answers_nothing(repo, before, after):
    assert renames_between(repo, before, after) == {}


def test_a_directory_that_is_not_a_repository_answers_nothing(tmp_path):
    """Best effort throughout. A repository is not required to use this
    tool, and a memory that raised here would take the whole run down."""
    assert renames_between(tmp_path, "a" * 40, "b" * 40) == {}


# --------------------------------------------- the status codes themselves

def test_a_rename_line_is_read_as_a_move():
    assert parse_name_status("R100\told.py\tnew.py\n") == {"old.py": "new.py"}
    assert parse_name_status("R096\ta/x.py\tb/x.py") == {"a/x.py": "b/x.py"}


def test_a_copy_is_not_a_move():
    """`C100` has the same three-field shape as a rename and is not one:
    the old file is still there, so treating it as a move would take a live
    finding's history away from a file that still has the defect in it."""
    assert parse_name_status("C100\told.py\tcopy.py") == {}


@pytest.mark.parametrize("line", [
    "M\tchanged.py", "A\tadded.py", "D\tgone.py", "T\ttype_changed",
    "U\tunmerged.py", "", "not a status line at all",
])
def test_nothing_else_is_a_move(line):
    assert parse_name_status(line) == {}


def test_several_moves_in_one_diff():
    assert parse_name_status(
        "R100\ta.py\tb.py\nM\tc.py\nR090\td.py\te.py") == {
            "a.py": "b.py", "d.py": "e.py"}


# ------------------------------------------------- carrying the history

def _ledger_with_history(repo, path, runs=3):
    ledger = Ledger(repo / ".ghost_ledger.json")
    for _ in range(runs):
        ledger.record([_finding(path)], checks={}, commit=_head(repo),
                      tool_version="t", root=repo)
    return ledger


def test_a_renamed_finding_keeps_its_history(repo):
    ledger = _ledger_with_history(repo, "gateway.py")
    old_id = _finding("gateway.py").id
    before = ledger.findings[old_id]
    assert before.consecutive == 3

    after_commit = _move(repo, "gateway.py", "gateway_v2.py")
    ledger.record([_finding("gateway_v2.py")], checks={}, commit=after_commit,
                  tool_version="t", root=repo)

    new_id = _finding("gateway_v2.py").id
    assert new_id != old_id
    assert old_id not in ledger.findings, "the old id was left behind as absent"
    carried = ledger.findings[new_id]
    assert carried.consecutive == 4, "the streak was broken by a rename"
    assert carried.returns == 0, "a rename was counted as a regression"
    assert carried.first_seen == before.first_seen
    assert carried.renamed_from == "gateway.py"


def test_a_module_with_two_findings_in_it_moves(repo):
    """The ordinary case, not the exception.

    Two unused functions in one module are two findings, and moving the
    module moves both. A memory that carries a history only when exactly
    one candidate sits at the destination refuses the common case.

    They are told apart by their summaries, which name the SYMBOL and are
    therefore unchanged by a rename.
    """
    (repo / "gateway.py").write_text(
        "def unused_a(a):\n    return a\n\n\ndef unused_b(b):\n    return b\n")
    _git(repo, "commit", "-qam", "two of them")

    first = _finding("gateway.py", summary="'unused_a' is never referenced")
    second = _finding("gateway.py", summary="'unused_b' is never referenced")
    ledger = Ledger(repo / ".ghost_ledger.json")
    for _ in range(2):
        ledger.record([first, second], checks={}, commit=_head(repo),
                      tool_version="t", root=repo)
    assert ledger.findings[first.id].consecutive == 2

    after = _move(repo, "gateway.py", "gateway_v2.py")
    moved_a = _finding("gateway_v2.py", summary="'unused_a' is never referenced")
    moved_b = _finding("gateway_v2.py", summary="'unused_b' is never referenced")
    ledger.record([moved_a, moved_b], checks={}, commit=after,
                  tool_version="t", root=repo)

    assert first.id not in ledger.findings and second.id not in ledger.findings
    assert ledger.findings[moved_a.id].consecutive == 3
    assert ledger.findings[moved_b.id].consecutive == 3
    assert ledger.findings[moved_a.id].renamed_from == "gateway.py"
    assert ledger.findings[moved_a.id].summary == "'unused_a' is never referenced", (
        "the two histories were swapped")


def test_the_new_path_is_recorded(repo):
    ledger = _ledger_with_history(repo, "gateway.py")
    after = _move(repo, "gateway.py", "gateway_v2.py")
    ledger.record([_finding("gateway_v2.py")], checks={}, commit=after,
                  tool_version="t", root=repo)
    assert ledger.findings[_finding("gateway_v2.py").id].file == "gateway_v2.py"


def test_a_finding_that_really_went_away_is_still_absent(repo):
    """The boundary. Following renames must not make every disappearance
    look like a move."""
    ledger = _ledger_with_history(repo, "gateway.py")
    after = _move(repo, "gateway.py", "gateway_v2.py")
    ledger.record([], checks={}, commit=after, tool_version="t", root=repo)
    remaining = [h for h in ledger.findings.values()]
    assert len(remaining) == 1
    assert remaining[0].absent_last_run is True
    assert remaining[0].consecutive == 0


def test_a_finding_that_went_away_is_not_carried_onto_its_neighbour(repo):
    """A file that did NOT move carries nothing.

    Two unused functions in one module are two findings. Remove one and add
    another, and the file is untouched by any rename -- so the departed
    finding must be recorded as absent, not re-keyed onto the newcomer that
    happens to share its file and detector.

    Looking up a finding's own path in the rename map with a default of
    "itself" turns every disappearance into a move. That is the mutant this
    kills.
    """
    ledger = Ledger(repo / ".ghost_ledger.json")
    gone = _finding("gateway.py", summary="'unused_a' is never referenced")
    ledger.record([gone], checks={}, commit=_head(repo), tool_version="t",
                  root=repo)

    # Something else moves in the same commit, so the rename map is not
    # empty and the lookup below is actually reached. Without this the
    # whole function returns early and the case proves nothing -- measured.
    _git(repo, "mv", "other.py", "other_v2.py")
    (repo / "gateway.py").write_text("def unused_b(b):\n    return b\n")
    _git(repo, "commit", "-qam", "swap the function, and move something else")
    arrived = _finding("gateway.py", summary="'unused_b' is never referenced")
    ledger.record([arrived], checks={}, commit=_head(repo), tool_version="t",
                  root=repo)

    assert ledger.findings[gone.id].absent_last_run is True
    assert ledger.findings[arrived.id].renamed_from == ""
    assert ledger.findings[arrived.id].consecutive == 1, (
        "a newcomer inherited a streak it never earned")


def test_a_different_detector_at_the_new_path_is_not_the_same_finding(repo):
    """Same file, different defect. Carrying the history across would be
    inventing a continuity nobody observed."""
    ledger = _ledger_with_history(repo, "gateway.py")
    after = _move(repo, "gateway.py", "gateway_v2.py")
    ledger.record([_finding("gateway_v2.py", detector="long_function")],
                  checks={}, commit=after, tool_version="t", root=repo)
    old = ledger.findings[_finding("gateway.py").id]
    assert old.absent_last_run is True


def test_two_candidates_at_the_new_path_carry_nothing(repo):
    """A memory that guesses which finding this used to be is inventing
    continuity."""
    ledger = _ledger_with_history(repo, "gateway.py")
    after = _move(repo, "gateway.py", "gateway_v2.py")
    ledger.record([_finding("gateway_v2.py", summary="'a' is never referenced"),
                   _finding("gateway_v2.py", summary="'b' is never referenced")],
                  checks={}, commit=after, tool_version="t", root=repo)
    assert ledger.findings[_finding("gateway.py").id].absent_last_run is True


def test_a_history_already_at_the_new_id_is_not_overwritten(repo):
    """Two histories merging is a worse lie than one history restarting.

    The first run records a finding at a path that does not exist yet. The
    ledger neither knows nor checks -- it is a map from id to history -- and
    that is exactly the collision this guard is about: the id the carry
    would land on is already taken.

    Built this way rather than by deleting a real file, because git reports
    "delete one, rename another onto its name" as a plain delete and the
    carry path is never reached at all. Measured; the first version of this
    test proved nothing.
    """
    ledger = Ledger(repo / ".ghost_ledger.json")
    ledger.record([_finding("gateway.py"), _finding("gateway_v2.py")],
                  checks={}, commit=_head(repo), tool_version="t", root=repo)
    squatter = ledger.findings[_finding("gateway_v2.py").id]
    assert squatter.renamed_from == ""

    after = _move(repo, "gateway.py", "gateway_v2.py")
    ledger.record([_finding("gateway_v2.py")], checks={}, commit=after,
                  tool_version="t", root=repo)

    kept = ledger.findings[_finding("gateway_v2.py").id]
    assert kept.renamed_from == "", "an existing history was clobbered"
    assert kept.consecutive == 2, "an existing streak was replaced"
    # The one that could not be carried is recorded as absent rather than
    # silently dropped.
    assert ledger.findings[_finding("gateway.py").id].absent_last_run is True


def test_without_a_root_nothing_is_followed(repo):
    """Callers that do not say where the repository is lose nothing they
    had. The old behaviour is the default."""
    ledger = _ledger_with_history(repo, "gateway.py")
    after = _move(repo, "gateway.py", "gateway_v2.py")
    ledger.record([_finding("gateway_v2.py")], checks={}, commit=after,
                  tool_version="t")
    assert ledger.findings[_finding("gateway.py").id].absent_last_run is True


def test_the_first_run_has_nothing_to_follow(repo):
    """No previous commit recorded means no comparison is possible."""
    ledger = Ledger(repo / ".ghost_ledger.json")
    ledger.record([_finding("gateway.py")], checks={}, commit=_head(repo),
                  tool_version="t", root=repo)
    assert len(ledger.findings) == 1


def test_the_carried_history_survives_being_written_and_read(repo):
    ledger = _ledger_with_history(repo, "gateway.py")
    after = _move(repo, "gateway.py", "gateway_v2.py")
    ledger.record([_finding("gateway_v2.py")], checks={}, commit=after,
                  tool_version="t", root=repo)
    ledger.save()

    reread = Ledger(repo / ".ghost_ledger.json")
    carried = reread.findings[_finding("gateway_v2.py").id]
    assert carried.consecutive == 4
    assert carried.renamed_from == "gateway.py"
