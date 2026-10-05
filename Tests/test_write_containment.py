"""Where a write is allowed to land, and where the decision is made.

THREE HOLES, ONE SHAPE

Each of these was found by pointing an adversarial harness at the operating
mode, and all three are the same mistake wearing different clothes: a
decision made about one thing, applied to another.

  the path        writability was judged from the name the scan walked, and
                  the bytes went to whatever that name resolved to
  the tree        `root / "README.md"` was composed and written without
                  asking whether it was still inside `root`
  the moment      writability was decided during the workup and never
                  re-asked, though the repository's own suite runs inside
                  the window and can change the sentence

The fix in all three is the same: re-derive the decision from the file
about to be written, as it is now.

The last two live in `test_remedy_doc_counts.py` rather than here, because
that is the file the mutant harness runs when it deletes the re-derivation:
a guard whose test sits in a file the mutant never runs is a guard nothing
proves.

WHAT THESE TESTS DO NOT ASSERT, AND WHY

That the refusal is reported. A remedy returns `(changed, note)` and the
operation discards the note when nothing changed -- no cut, no note. So a
run in which every claim was declined says nothing about why, and these
tests assert only that nothing was written. The reason IS carried when the
remedy took at least one cut (`test_a_dated_document_is_reported_beside_a_real_cut`).
Closing the rest of that gap means changing what an operation does with a
remedy that declined everything, which is a change to the operation flow
rather than to a write, and is not what these fixes are.
"""
from __future__ import annotations

import subprocess


from ghost_buster.annotate import (Disagreement, annotate_files, refuses,
                                   update_readme)
from ghost_buster.operate import _remedy_doc_counts
from ghost_buster.schema import (Category, Evidence, Finding, Layer, Severity,
                                 Status)


def _repo(root):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    return root


def _claim(file="README.md", line=5, documented="390", collected="1727",
           writable="yes"):
    return Finding(
        detector="doc_count_contradicted_by_run",
        category=Category.DOC_DRIFT, layer=Layer.MECHANICAL,
        severity=Severity.MINOR, status=Status.CONFIRMED,
        summary="measured", detail="",
        attributes={"documented_count": documented, "collected": collected,
                    "passed": collected, "writable": writable,
                    "not_writable_because": ""},
        evidence=Evidence(file=file, line_start=line, line_end=line),
    )


# --------------------------------------------------------------- the tree

def test_a_link_out_of_the_repository_is_refused(tmp_path):
    """The severe one.

    A README that is a symlink to a file outside the repository is an
    ordinary thing for a repository to contain. Writing "the README" then
    writes outside the tree -- beyond the branch the operation opened, so
    beyond anything it can revert, and beyond the commit it then tries to
    make, which fails with nothing to commit and reports a symptom after the
    damage has landed.
    """
    root = _repo(tmp_path / "repo")
    victim = tmp_path / "outside" / "NOTES.md"
    victim.parent.mkdir()
    victim.write_text("# not part of any repository\n")
    (root / "README.md").symlink_to(victim)

    assert refuses(root / "README.md", root) is not None
    assert update_readme(root / "README.md", [], root=root) is False
    assert victim.read_text() == "# not part of any repository\n"


def test_a_path_inside_the_repository_is_allowed(tmp_path):
    root = _repo(tmp_path / "repo")
    (root / "README.md").write_text("# thing\n")
    assert refuses(root / "README.md", root) is None


def test_a_link_that_stays_inside_is_allowed(tmp_path):
    """The check is about where the bytes land, not about symlinks."""
    root = _repo(tmp_path / "repo")
    (root / "docs").mkdir()
    (root / "docs" / "real.md").write_text("# real\n")
    (root / "README.md").symlink_to(root / "docs" / "real.md")
    assert refuses(root / "README.md", root) is None


def test_no_root_makes_no_containment_claim(tmp_path):
    """A caller that did not say where the patient is gets no promise, and
    the absence is explicit rather than a silently passing check."""
    assert refuses(tmp_path / "anywhere.md", None) is None


# ------------------------------------------------------- uninvited markup

def test_a_section_recording_nothing_is_not_created(tmp_path):
    """The count-block remedy states the principle -- a scanner that inserts
    its own markup uninvited has decided something that was not its to
    decide -- and this module was doing exactly that, with a table reading
    `_none_`."""
    root = _repo(tmp_path / "repo")
    readme = root / "README.md"
    readme.write_text("# thing\n\nNothing else.\n")
    assert update_readme(readme, [], root=root) is False
    assert readme.read_text() == "# thing\n\nNothing else.\n"


def test_an_existing_block_is_still_maintained_when_empty(tmp_path):
    """A repository carrying the block opted in, and "no disagreements, this
    block records that the check ran" is then a fact somebody asked for."""
    from ghost_buster.annotate import BEGIN, END
    root = _repo(tmp_path / "repo")
    readme = root / "README.md"
    readme.write_text(f"# thing\n\n{BEGIN}\nstale contents\n{END}\n")
    assert update_readme(readme, [], root=root) is True
    assert "records that the check ran" in readme.read_text()


def _disagreement(path, line=1):
    """One name disagreement, enough to give the writers something to say.

    Every containment test below needs real work pending. With nothing to
    write, `update_readme` declines for having nothing to record and the
    containment guard can be deleted with the test still green -- measured,
    the mutant survived.
    """
    return Disagreement(param="count", arg="total",
                        definitions=((str(path), line),),
                        call_sites=((str(path), line + 1),))


def test_a_link_out_of_the_repository_is_refused_with_work_pending(tmp_path):
    """The severe one, with something to write.

    Containment is the only thing standing between this and a write outside
    the tree -- beyond the branch an operation opened, so beyond anything it
    can revert, and beyond the commit it then tries to make, which fails
    with nothing to commit and reports a symptom after the damage.
    """
    root = _repo(tmp_path / "repo")
    victim = tmp_path / "outside" / "NOTES.md"
    victim.parent.mkdir()
    victim.write_text("# theirs\n")
    (root / "README.md").symlink_to(victim)
    (root / "a.py").write_text("def f(count):\n    return count\n")

    assert update_readme(root / "README.md",
                         [_disagreement(root / "a.py")], root=root) is False
    assert victim.read_text() == "# theirs\n"


def test_a_source_file_outside_the_repository_is_refused(tmp_path):
    """The same hole on the other writer. `annotate_files` walks the corpus
    and writes comments into it; a source file that is a link out carries
    those comments outside the tree."""
    root = _repo(tmp_path / "repo")
    outside = tmp_path / "outside" / "theirs.py"
    outside.parent.mkdir()
    outside.write_text("def f(count):\n    return count\n")
    link = root / "linked.py"
    link.symlink_to(outside)

    changed = annotate_files([_disagreement(link)], [link], root=root)
    assert changed == []
    assert "ghost_buster" not in outside.read_text()


def test_a_source_file_inside_the_repository_is_annotated(tmp_path):
    """The guard must not close the writer it guards."""
    root = _repo(tmp_path / "repo")
    source = root / "a.py"
    source.write_text("def f(count):\n    return count\n")
    changed = annotate_files([_disagreement(source)], [source], root=root)
    assert changed == [source]
    assert "ghost_buster" in source.read_text()


# ------------------------------------------------------ which name is used

def test_a_finding_names_the_file_not_the_link_to_it(tmp_path):
    """De-duplication kept whichever name sorted first, and that is arbitrary.

    When the link sorted first, every finding in the file named the link --
    so a reader who followed the reported path and looked at its history saw
    a symlink that had never changed, and concluded nothing had happened.
    The bytes were in the other file, which no finding mentioned.
    """
    from ghost_buster.pipeline import _collect_files

    root = _repo(tmp_path / "repo")
    (root / "docs").mkdir()
    (root / "docs" / "project_notes.md").write_text("# notes\n")
    (root / "README.md").symlink_to(root / "docs" / "project_notes.md")

    gathered = _collect_files(root)
    names = {p.name for p in gathered}
    assert "project_notes.md" in names
    assert "README.md" not in names
    assert len([p for p in gathered if p.suffix == ".md"]) == 1


def test_a_link_with_no_real_file_in_the_tree_is_still_scanned(tmp_path):
    """A README linked outside the repository has no in-tree twin to prefer,
    so it stays in the corpus and is still READ. Reporting on it is safe;
    writing to it is what `refuses` stops."""
    from ghost_buster.pipeline import _collect_files

    root = _repo(tmp_path / "repo")
    outside = tmp_path / "outside" / "NOTES.md"
    outside.parent.mkdir()
    outside.write_text("# outside\n")
    (root / "README.md").symlink_to(outside)

    assert {p.name for p in _collect_files(root)} == {"README.md"}


def test_an_ordinary_tree_is_unchanged(tmp_path):
    """The fix must be invisible to a repository with no symlinks in it."""
    from ghost_buster.pipeline import _collect_files

    root = _repo(tmp_path / "repo")
    (root / "a.py").write_text("x = 1\n")
    (root / "b.md").write_text("# b\n")
    (root / "pkg").mkdir()
    (root / "pkg" / "c.py").write_text("y = 2\n")
    assert [p.name for p in _collect_files(root)] == ["a.py", "b.md", "c.py"]


# ---------------------------------------------------------------------------
# The surface, not the case. (v1.7.2)
#
# 1.7.1 fixed containment in two writers and missed the third, and the case
# that found the hole did not exercise it -- so the case passed and the class
# stayed open. An adversarial variant one dimension away (the same world with
# a maintained block in it) walked straight back out of the repository.
#
# This test therefore runs EVERY writer over ONE world. A guard added to one
# path and not another fails here rather than in six weeks.
# ---------------------------------------------------------------------------

def _linked_out_world(tmp_path):
    """A repository whose README is a symlink to a file outside it, carrying
    everything each of the three writers looks for."""
    from ghost_buster.operate import COUNT_BLOCK_CLOSE, COUNT_BLOCK_OPEN
    root = _repo(tmp_path / "repo")
    victim = tmp_path / "outside" / "NOTES.md"
    victim.parent.mkdir()
    victim.write_text(
        "# theirs\n\n"
        "The test suite has 390 tests, all passing.\n\n"
        f"{COUNT_BLOCK_OPEN}\n390 tests, all passing.\n{COUNT_BLOCK_CLOSE}\n")
    (root / "README.md").symlink_to(victim)
    (root / "a.py").write_text("def f(count):\n    return count\n")
    return root, victim


def test_no_writer_follows_a_link_out_of_the_repository(tmp_path):
    """All three, over one world."""
    from ghost_buster.operate import (_remedy_annotate, _remedy_count_block)
    root, victim = _linked_out_world(tmp_path)
    before = victim.read_text()
    files = [root / "README.md", root / "a.py"]

    for remedy in (_remedy_annotate, _remedy_count_block, _remedy_doc_counts):
        remedy(root, files, [_claim(file="README.md", line=3)])
        assert victim.read_text() == before, (
            "%s wrote outside the repository" % remedy.__name__)


def test_the_block_remedy_declines_a_link_out_of_the_repository(tmp_path):
    """The specific hole 1.7.1 left, named so a regression is readable."""
    from ghost_buster.operate import _remedy_count_block
    root, victim = _linked_out_world(tmp_path)
    changed, _ = _remedy_count_block(root, [root / "README.md"],
                                     [_claim(file="README.md", line=3)])
    assert changed == 0
    assert "390 tests" in victim.read_text()
