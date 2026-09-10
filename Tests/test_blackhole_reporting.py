"""What a report says about its own limits, and what it declines to render.

Three changes from the first real run of the extrapolator, 2026-09-10:

  * A void whose INFERRED section is empty is half a Void -- the
    undeterminable list without anything the evidence forced. Those were 25%
    of a 10,144-line report.
  * "Not declared as a dependency" means one thing in a project with a
    manifest and something else in a project without one, and the tool said
    the same sentence either way.
  * The single most useful line the tool printed was a note that an
    uninitialised submodule might explain an absence. Every wrong claim made
    about one module that day came from a scan narrower than the claim drawn
    from it, so that note is generalised into a scan-level check.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from blackhole_extrapolator.cli import main
from blackhole_extrapolator.detect import false_absence_hints


def _repo(parent: Path, name: str, files: dict) -> Path:
    root = parent / name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))
    return root


# ------------------------------------------------------ C: shapeless voids

def _shapeless_repo(tmp_path) -> Path:
    """`gone` is named by a bare import and used with no attribute, so
    nothing constrains its shape; `shaped` is used as `shaped.render(1)`,
    which does."""
    return _repo(tmp_path, "svc", {
        "a.py": "import gone_qqq\n",
        "b.py": "def go():\n    return shaped_qqq.render(1)\n",
        "c.py": "def stop():\n    return gone_qqq\n",
    })


def test_a_void_that_constrains_no_shape_is_named_not_rendered(tmp_path, capsys):
    main([str(_shapeless_repo(tmp_path))])
    out = capsys.readouterr().out
    assert "`shaped_qqq` is reached for and is not there" in out
    assert "constrains no shape at all -- named, not outlined" in out
    assert "gone_qqq" in out                      # named
    assert "`gone_qqq` is reached for" not in out  # not rendered


def test_all_renders_the_shapeless_ones_too(tmp_path, capsys):
    main([str(_shapeless_repo(tmp_path)), "--all"])
    out = capsys.readouterr().out
    assert "`gone_qqq` is reached for and is not there" in out
    assert "constrains no shape at all -- named, not outlined" not in out


def test_the_collapse_is_by_shape_and_never_by_confidence(tmp_path, capsys):
    """Measured after the classification pass: shapeless voids sit at 0.35
    and 0.40 alongside fourteen that DO have a shape. A numeric cutoff set
    high enough to reach them takes real outlines with it."""
    main([str(_shapeless_repo(tmp_path))])
    out = capsys.readouterr().out
    rendered = out.split("further absence(s)")[0]
    assert "shaped_qqq" in rendered
    # the rendered one is not more confident than the collapsed one; only
    # its evidence constrains a shape
    assert "--min-confidence" not in out


# --------------------------------------------- D: what a manifest implies

def test_a_project_with_a_manifest_is_told_its_manifest_is_short(tmp_path, capsys):
    repo = _repo(tmp_path, "svc", {
        "app.py": "import unlisted_thing_qqq\n",
        "requirements.txt": "requests>=2\n",
    })
    main([str(repo)])
    out = capsys.readouterr().out
    assert "declares dependencies and none of these is among them" in out


def test_a_project_with_no_manifest_is_not_accused_of_omitting_anything(tmp_path, capsys):
    repo = _repo(tmp_path, "svc", {"app.py": "import unlisted_thing_qqq\n"})
    main([str(repo)])
    out = capsys.readouterr().out
    assert "declares no dependencies anywhere" in out
    assert "the manifest is short" not in out


# ------------------------------------- E: reasons this absence may be false

def test_a_scan_with_no_siblings_says_so(tmp_path):
    repo = _repo(tmp_path, "svc", {"a.py": "x = 1\n"})
    hints = false_absence_hints(repo)
    assert any("no sibling checkout was supplied" in h for h in hints)


def test_supplying_a_sibling_removes_that_hint(tmp_path):
    repo = _repo(tmp_path, "svc", {"a.py": "x = 1\n"})
    other = _repo(tmp_path, "lib", {"b.py": "y = 2\n"})
    hints = false_absence_hints(repo, siblings=[other])
    assert not any("no sibling checkout" in h for h in hints)


def test_an_uninitialised_submodule_is_a_scan_level_hint(tmp_path):
    repo = _repo(tmp_path, "gsa", {
        "core.py": "x = 1\n",
        ".gitmodules": '[submodule "vendor/dep"]\n\tpath = vendor/dep\n\turl = https://example.invalid/dep\n',
    })
    (repo / "vendor" / "dep").mkdir(parents=True)
    hints = false_absence_hints(repo, siblings=[repo])
    assert any("vendor/dep` is declared but not initialised" in h for h in hints)


def test_gitignored_python_is_a_scan_level_hint(tmp_path):
    repo = _repo(tmp_path, "svc", {"a.py": "x = 1\n", ".gitignore": "secrets_local.py\n"})
    hints = false_absence_hints(repo, siblings=[repo])
    assert any("secrets_local.py" in h for h in hints)


def test_the_hints_reach_the_report(tmp_path, capsys):
    repo = _repo(tmp_path, "svc", {"b.py": "def go():\n    return shaped_qqq.render(1)\n"})
    main([str(repo)])
    out = capsys.readouterr().out
    assert "could produce an absence that is not one" in out
    assert "no sibling checkout was supplied" in out


def test_a_clean_scan_with_siblings_prints_no_hint_block(tmp_path, capsys):
    """The hints must not become boilerplate on every run, or they teach the
    reader to skip the one that matters."""
    repo = _repo(tmp_path, "svc", {"b.py": "def go():\n    return shaped_qqq.render(1)\n"})
    other = _repo(tmp_path, "lib", {"c.py": "y = 2\n"})
    main([str(repo), "--sibling", str(other)])
    out = capsys.readouterr().out
    assert "could produce an absence that is not one" not in out


# ------------------------------- specimen corpora and retired repositories

def test_a_specimen_corpus_is_not_a_system_with_holes(tmp_path, capsys):
    """TOUCHSTONE opens "A specimen corpus. Not a system." Its flattened
    files are fixtures; five of the six highest-confidence voids in a
    37-repository scan came from reading them as losses."""
    # The broken file sits at the ROOT, not under specimens/, so only the
    # README declaration can classify this. With it under a fixture
    # directory the share test also fires and the test cannot tell which
    # signal did the work -- which is how the first version of this test
    # passed with the README check disabled.
    repo = _repo(tmp_path, "touch", {
        "README.md": "# TOUCH\n\n**A specimen corpus. Not a system.**\n",
        "broken.py": "class Thing:\n    def go(self, x): ",
    })
    main([str(repo)])
    out = capsys.readouterr().out
    assert "specimen corpus" in out
    assert "broken on purpose" in out
    assert "VOID" not in out


def test_fixture_directories_classify_without_a_readme(tmp_path):
    from blackhole_extrapolator.corpus import RootKind, classify_root
    repo = _repo(tmp_path, "corp", {
        "specimens/a.py": "class A: ...\n",
        "specimens/b.py": "class B: ...\n",
        "fixtures/c.py": "class C: ...\n",
    })
    assert classify_root(repo).kind is RootKind.SPECIMEN_CORPUS


def test_a_retired_repository_names_where_its_content_went(tmp_path, capsys):
    repo = _repo(tmp_path, "old", {
        "README.md": "# OLD (archived)\n\n**Retired 2026-09-03.** Both files here have "
                     "been folded into\n[NEW-HOME](https://example.invalid/NEW-HOME), which "
                     "is now the\ncanonical home for this content:\n",
        "flat.py": "class Thing:\n    def go(self, x): ",
    })
    main([str(repo)])
    out = capsys.readouterr().out
    assert "says it is retired" in out
    assert "NEW-HOME" in out
    assert "VOID" not in out


def test_not_a_system_alone_does_not_make_a_specimen_corpus(tmp_path):
    """A disclaimer both kinds use cannot tell them apart. GSA-Master-Kernel
    says "This is not a system. It is a preserved design conversation" --
    an archive, and matching that phrase mislabelled it."""
    from blackhole_extrapolator.corpus import RootKind, classify_root
    repo = _repo(tmp_path, "arch", {
        "README.md": "# ARCH\n\nAn archived transcript.\n\nThis is not a system.\n",
        "extracted/report_1/a.py": "class A: ...\n",
        "extracted/report_2/b.py": "class B: ...\n",
    })
    assert classify_root(repo).kind is RootKind.CODE_ARCHIVE


def test_an_ordinary_readme_mentioning_specimens_late_is_still_a_source_tree(tmp_path):
    """Bounded to the opening lines: a README discussing specimens in
    paragraph nine is discussing them, not declaring itself one."""
    from blackhole_extrapolator.corpus import RootKind, classify_root
    body = "# SVC\n\nA service.\n" + "\nfiller\n" * 20 + "\nWe keep a specimen corpus elsewhere.\n"
    repo = _repo(tmp_path, "svc", {"README.md": body, "pkg/a.py": "x = 1\n"})
    assert classify_root(repo).kind is RootKind.SOURCE_TREE
