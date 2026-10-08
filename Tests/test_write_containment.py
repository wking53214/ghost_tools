"""Where a write is allowed to land, and where the decision is made.

ONE HOLE, ONE SHAPE

Found by pointing an adversarial harness at the operating mode: a decision
made about one thing, applied to another. The scan judged a file by the name
it walked, and the bytes went to whatever that name resolved to.

The fix is to re-derive the decision from the file about to be written, as it
is now. The README writers that once shared this hole were removed; only
Streamline writes READMEs, so the one remaining writer here is the comment
annotator.

WHAT THESE TESTS DO NOT ASSERT

That the refusal is reported. A remedy returns `(changed, note)` and the
operation discards the note when nothing changed, so these tests assert only
that nothing was written.
"""
from __future__ import annotations

import subprocess


from ghost_buster.annotate import Disagreement, annotate_files, refuses


def _repo(root):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    return root


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


def _disagreement(path, line=1):
    """One name disagreement, enough to give the writer something to do.

    Every containment test below needs real work pending, or the guard can be
    deleted with the test still green.
    """
    return Disagreement(param="count", arg="total",
                        definitions=((str(path), line),),
                        call_sites=((str(path), line + 1),))


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
# The surface, not the case.
#
# This runs the writer over a world where the README is a symlink out of the
# repository. A guard added to one path and not another fails here.
# ---------------------------------------------------------------------------

def _linked_out_world(tmp_path):
    """A repository whose README is a symlink to a file outside it."""
    root = _repo(tmp_path / "repo")
    victim = tmp_path / "outside" / "NOTES.md"
    victim.parent.mkdir()
    victim.write_text("# theirs\n\nThe test suite has 390 tests, all passing.\n")
    (root / "README.md").symlink_to(victim)
    (root / "a.py").write_text("def f(count):\n    return count\n")
    return root, victim


def test_no_writer_follows_a_link_out_of_the_repository(tmp_path):
    """The one remaining writer, over one world."""
    from ghost_buster.operate import _remedy_annotate
    root, victim = _linked_out_world(tmp_path)
    before = victim.read_text()
    files = [root / "README.md", root / "a.py"]

    _remedy_annotate(root, files, [])
    assert victim.read_text() == before, "annotate wrote outside the repository"
