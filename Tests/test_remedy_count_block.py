"""A block the repository hands over, and the tool keeps current.

WHY THIS EXISTS BESIDE THE DOC-COUNT REMEDY (v1.7.0)

The doc-count remedy rewrites a number inside somebody's prose. That is
why it carries six refusals and five claim shapes, and why its measured
precision had to be earned: of 65 candidate claims across the library it
accepts none, because every one is a count of another project, of a
single test file, or of a moment in the past. That is the correct answer
and it leaves the tool unable to maintain anything.

A sentence cannot say "this number is yours to keep current". A block
can. Inside the markers the number is the tool's; outside them nothing is
touched. The distinction is a fact about the document rather than a
judgement about English, which is the whole point.

The rule that keeps it honest is that the tool never writes the markers
itself. A scanner that inserts its own markup into somebody's README
uninvited has decided something that was not its to decide, and the first
thing this remedy would then do is change 38 repositories nobody asked to
change. No block, no cut.
"""
from __future__ import annotations

import subprocess

import pytest

from ghost_buster.operate import (COUNT_BLOCK_CLOSE, COUNT_BLOCK_OPEN, RemedyFailed,
                                  _remedy_count_block)
from ghost_buster.schema import (Category, Evidence, Finding, Layer, Severity,
                                 Status)


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _measured(collected=1727, passed=None):
    return Finding(
        detector="doc_count_contradicted_by_run",
        category=Category.DOC_DRIFT, layer=Layer.MECHANICAL,
        severity=Severity.MINOR, status=Status.CONFIRMED,
        summary="measured", detail="",
        attributes={"documented_count": "390", "collected": str(collected),
                    "passed": str(collected if passed is None else passed)},
        evidence=Evidence(file="README.md", line_start=1, line_end=1),
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text(
        "# thing\n\nIntro prose nobody may touch.\n\n"
        f"{COUNT_BLOCK_OPEN}\n390 tests, all passing.\n{COUNT_BLOCK_CLOSE}\n\n"
        "Closing prose, also untouchable.\n")
    return root


def _files(root):
    return sorted(root.rglob("*.md"))


def test_the_block_is_set_to_the_measured_number(repo):
    changed, note = _remedy_count_block(repo, _files(repo), [_measured()])
    assert changed == 1 and "1727" in note
    assert "1727 tests, all passing." in (repo / "README.md").read_text()


def test_prose_outside_the_block_is_untouched(repo):
    before = (repo / "README.md").read_text()
    _remedy_count_block(repo, _files(repo), [_measured()])
    after = (repo / "README.md").read_text()
    for line in ("# thing", "Intro prose nobody may touch.", "Closing prose, also untouchable."):
        assert line in after
    assert before.split(COUNT_BLOCK_OPEN)[0] == after.split(COUNT_BLOCK_OPEN)[0]
    assert before.split(COUNT_BLOCK_CLOSE)[1] == after.split(COUNT_BLOCK_CLOSE)[1]


def test_no_block_means_no_cut(tmp_path):
    """The rule that keeps this honest. A repository that has not handed
    anything over gets nothing written to it, ever."""
    root = tmp_path / "plain"
    root.mkdir()
    (root / "README.md").write_text("# plain\n\nA suite of 390 tests, all passing.\n")
    assert _remedy_count_block(root, _files(root), [_measured()]) == (0, "")
    assert "390" in (root / "README.md").read_text()


def test_a_block_already_current_is_not_a_cut(repo):
    _remedy_count_block(repo, _files(repo), [_measured()])
    assert _remedy_count_block(repo, _files(repo), [_measured()]) == (0, "")


def test_nothing_is_written_without_a_measured_run(repo):
    """The number comes from a suite that ran. No run, no number, no cut."""
    assert _remedy_count_block(repo, _files(repo), []) == (0, "")
    assert "390" in (repo / "README.md").read_text()


def test_a_suite_that_is_not_green_supplies_no_number(repo):
    """Same rule the doc-count remedy applies: "all passing" beside forty
    failures is a false sentence, and this block writes that sentence."""
    assert _remedy_count_block(repo, _files(repo), [_measured(1727, passed=1687)]) == (0, "")
    assert "390" in (repo / "README.md").read_text()


def test_every_block_in_the_tree_is_maintained(repo):
    (repo / "docs.md").write_text(
        f"# docs\n\n{COUNT_BLOCK_OPEN}\n1 tests, all passing.\n{COUNT_BLOCK_CLOSE}\n")
    changed, _ = _remedy_count_block(repo, _files(repo), [_measured()])
    assert changed == 2
    assert "1727" in (repo / "docs.md").read_text()


def test_a_write_that_disturbs_the_document_raises(repo, monkeypatch):
    import pathlib
    real = pathlib.Path.write_text

    def also_edit_the_prose(self, data, *a, **k):
        return real(self, data.replace("Intro prose", "INTRO PROSE"), *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", also_edit_the_prose)
    with pytest.raises(RemedyFailed) as failure:
        _remedy_count_block(repo, _files(repo), [_measured()])
    assert "outside the block changed" in str(failure.value)


def test_a_write_that_loses_the_number_raises(repo, monkeypatch):
    import pathlib
    real = pathlib.Path.write_text

    def drop_the_number(self, data, *a, **k):
        return real(self, data.replace("1727", "?"), *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", drop_the_number)
    with pytest.raises(RemedyFailed) as failure:
        _remedy_count_block(repo, _files(repo), [_measured()])
    assert "does not hold 1727" in str(failure.value)
