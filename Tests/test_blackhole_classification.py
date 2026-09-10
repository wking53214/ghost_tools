"""Two questions asked before an absence is outlined.

Measured on 2026-09-10, across a 37-repository library, the extrapolator
produced 248 voids. Two classes of them described nothing that was missing:

  * 21 named the standard library, typing, or a package that simply was not
    installed on the machine running the scan. `copy` was outlined as an
    absence whose "callers require attributes: read ['copy', 'deepcopy']" --
    a specification of `import copy`.
  * 124 came from four repositories whose job is to PRESERVE code rather
    than run it. A truncated paste inside a chat export is a faithful record
    of a partial thing, not a hole in a system.

These tests pin both answers by literal, because both were wrong in a way
that produced confident, well-formatted nonsense.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from blackhole_extrapolator import EvidenceKind, scan
from blackhole_extrapolator.cli import main
from blackhole_extrapolator.corpus import RootKind, classify_root
from blackhole_extrapolator.detect import resolution
from blackhole_extrapolator.schema import NON_SEEDING_KINDS


def _repo(parent: Path, name: str, files: dict) -> Path:
    root = parent / name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))
    return root


# ---------------------------------------------------------------- resolution

def test_resolution_does_not_depend_on_what_is_installed_here():
    """The check that broke was `__import__`, which asks about a container.

    `sys` and `Dict` resolve on any interpreter running this suite; a name
    nobody has ever published resolves nowhere. Neither answer may change
    because a virtualenv did.
    """
    assert resolution("sys") == "the standard library"
    assert resolution("copy") == "the standard library"
    assert resolution("Dict") == "typing"
    assert resolution("print") == "builtins"
    assert resolution("definitely_not_a_real_package_xyzzy_42") is None


def test_a_stdlib_name_used_unimported_is_an_import_not_an_absence(tmp_path):
    repo = _repo(tmp_path, "svc", {"m.py": "def f(x):\n    return copy.deepcopy(x)\n"})
    evidence = scan(repo)
    kinds = {e.kind for e in evidence}
    assert EvidenceKind.MISSING_IMPORT in kinds
    assert EvidenceKind.DANGLING_REFERENCE not in kinds
    detail = next(e.detail for e in evidence if e.kind is EvidenceKind.MISSING_IMPORT)
    assert "the standard library" in detail
    assert "The fix is an import, not a reconstruction." in detail


def test_a_typing_name_used_unimported_is_an_import_not_an_absence(tmp_path):
    repo = _repo(tmp_path, "svc", {"m.py": "def f(x: Dict[str, int]) -> Any:\n    return x\n"})
    kinds = {e.kind for e in scan(repo)}
    assert kinds == {EvidenceKind.MISSING_IMPORT}


def test_an_unaccounted_import_is_named_unresolved_and_still_reported(tmp_path):
    """Demotion is not deletion. The tool cannot tell a lost module from an
    undeclared package offline, so it says which checks it ran."""
    repo = _repo(tmp_path, "svc", {"m.py": "import some_unpublished_thing_qqq\n"})
    evidence = scan(repo)
    assert [e.kind for e in evidence] == [EvidenceKind.UNRESOLVED_IMPORT]
    detail = evidence[0].detail
    # Re-anchored when the manifest verdict landed: "not declared as a
    # dependency" said the same thing to a project with a populated
    # pyproject and to one with no manifest at all. The detail now names
    # which of those it is, so this asserts the checks that are still
    # phrased as checks, plus the verdict that replaced the fourth.
    for phrase in ("not in the search roots", "not provided by a sibling",
                   "not in the standard library"):
        assert phrase in detail, phrase
    assert ("declares no dependencies anywhere" in detail
            or "declares dependencies and this is not among them" in detail), detail


def test_an_unresolved_import_alone_does_not_make_a_void(tmp_path, capsys):
    repo = _repo(tmp_path, "svc", {"m.py": "import some_unpublished_thing_qqq\n"})
    assert main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "void" not in out.lower() or "No voids" in out
    assert "some_unpublished_thing_qqq" in out
    assert "resolve nowhere" in out


def test_an_unresolved_import_joins_a_void_that_other_evidence_establishes(tmp_path, capsys):
    """Corroboration is the whole rule: one weak mark is not an absence, and
    the same mark beside a dangling attribute use is part of one."""
    repo = _repo(tmp_path, "svc", {
        "m.py": "import lost_thing_qqq\n",
        "use.py": "def go():\n    return lost_thing_qqq.render(1)\n",
    })
    assert main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "`lost_thing_qqq` is reached for and is not there" in out
    assert "render" in out


def test_the_non_seeding_set_names_exactly_the_three_kinds():
    """Pinned by literal. A loop over the set would pass for whatever it
    holds; adding a fourth kind is a judgement that should cost an edit."""
    assert NON_SEEDING_KINDS == {
        EvidenceKind.WIRING,
        EvidenceKind.MISSING_IMPORT,
        EvidenceKind.UNRESOLVED_IMPORT,
    }


# ------------------------------------------------------------- archive vs tree

def test_a_provenance_file_alone_does_not_make_a_source_tree_an_archive(tmp_path):
    """The first version of this classifier read PROVENANCE.md as sufficient
    and called ghost_tools and GSA-815 archives -- two live codebases with
    zero Python under an export path -- which would have silenced every void
    in them. Documenting your origins is something good repositories do."""
    repo = _repo(tmp_path, "tool", {
        "pkg/core.py": "x = 1\n",
        "pkg/util.py": "y = 2\n",
        "PROVENANCE.md": "# where this came from\n",
    })
    result = classify_root(repo)
    assert result.kind is RootKind.SOURCE_TREE
    assert result.archived_files == 0


def test_python_under_export_paths_makes_an_archive(tmp_path):
    repo = _repo(tmp_path, "arch", {
        "extracted/report_1/a.py": "class A: ...\n",
        "extracted/report_2/b.py": "class B: ...\n",
        "extracted/report_3/c.py": "class C: ...\n",
    })
    assert classify_root(repo).kind is RootKind.CODE_ARCHIVE


def test_one_vendored_export_directory_does_not_make_an_archive(tmp_path):
    """A working repository that keeps one export folder stays a source
    tree: the threshold is two thirds, not a bare majority."""
    files = {f"pkg/mod_{i}.py": "x = 1\n" for i in range(6)}
    files["extracted/report_1/a.py"] = "class A: ...\n"
    repo = _repo(tmp_path, "svc", files)
    assert classify_root(repo).kind is RootKind.SOURCE_TREE


def test_an_archive_reports_extraction_fidelity_instead_of_voids(tmp_path, capsys):
    repo = _repo(tmp_path, "arch", {
        "extracted/report_1/broken.py": "class Thing:\n    def go(self, x): ",
        "extracted/report_2/also.py": "class Other:\n    def run(self): ",
        "PROVENANCE.md": "# archived conversation payloads\n",
    })
    assert main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "archive of code, not a source tree" in out
    assert "extraction fidelity" in out
    assert "did not survive extraction intact" in out
    assert "VOID" not in out


def test_a_source_tree_still_reports_its_voids(tmp_path, capsys):
    """The guard that matters: classification must never silence a codebase."""
    repo = _repo(tmp_path, "svc", {
        "pkg/a.py": "x = 1\n", "pkg/b.py": "y = 2\n", "pkg/c.py": "z = 3\n",
        "pkg/use.py": "def go():\n    return gone_module_qqq.render(1)\n",
    })
    assert main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "VOID" in out
    assert "`gone_module_qqq` is reached for and is not there" in out
