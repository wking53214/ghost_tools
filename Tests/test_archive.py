"""An archive is not a patient (ghost_buster/archive.py). The scan runs;
candidacy is not assessed; the surgeon refuses; the receipt says why."""
from __future__ import annotations

from ghost_buster.archive import MARKER, marked
from ghost_buster.cli import main

QUIET = ["--no-branches", "--no-tests", "--no-secrets", "--no-project", "--no-correlate",
         "--no-ledger", "--single-repo"]


def _repo(tmp_path, reason=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def unused():\n    pass\n")
    if reason is not None:
        (repo / MARKER).write_text(reason)
    return repo


def test_no_marker_means_no_archive(tmp_path):
    assert marked(_repo(tmp_path)) is None


def test_the_marker_carries_its_reason_on_one_line(tmp_path):
    repo = _repo(tmp_path, "a corpus of exported\n  transcripts, kept as data\n")
    a = marked(repo)
    assert a is not None and a.reason == "a corpus of exported transcripts, kept as data"
    assert "this repository is an archive: a corpus of exported transcripts" in a.receipt()


def test_an_empty_marker_is_still_an_archive_and_says_no_reason(tmp_path):
    a = marked(_repo(tmp_path, ""))
    assert a is not None and "no reason given" in a.receipt()


def test_findings_are_still_reported_and_candidacy_is_not_assessed(tmp_path, capsys):
    repo = _repo(tmp_path, "specimens kept flattened on purpose")
    main([str(repo), *QUIET, "--baseline", str(tmp_path / "b.json")])
    out, err = capsys.readouterr()
    assert "this repository is an archive: specimens kept flattened on purpose" in err
    assert "dead_code" in out or "unused" in out
    assert "serum candidacy: not assessed (archive: specimens kept flattened on purpose)" in out
    assert "CANDIDATE" not in out and "parses completely" not in out


def test_the_surgeon_refuses_an_archive(tmp_path, capsys):
    repo = _repo(tmp_path, "history")
    rc = main([str(repo), *QUIET, "--operate", "--operate-dry-run", "--baseline", str(tmp_path / "b.json")])
    _, err = capsys.readouterr()
    assert rc == 2
    assert "refused: an archive is not a patient" in err


def test_a_repository_without_the_marker_is_assessed_as_before(tmp_path, capsys):
    repo = _repo(tmp_path)
    main([str(repo), *QUIET, "--baseline", str(tmp_path / "b.json")])
    out, _ = capsys.readouterr()
    assert "serum candidacy:" in out and "parses completely" in out
