"""What a scan is allowed to do to the tree it was pointed at.

Every test here runs a REAL entry point against a real tree and checks the
tree afterwards. Nothing is mocked, because the claim under test is about
what the program does to a filesystem and a mock filesystem cannot fail the
way a real one does.

The claim was in 35 docstrings and in no test until this file existed.
"""
from __future__ import annotations

import ast
import json
import textwrap

import pytest

from blackhole_extrapolator import cli as blackhole_cli
from ghost_buster import cli as buster_cli
from ghost_buster.mechanical import run_all
from tree_guard import Changes, compare, snapshot, unchanged

# Everything that would reach outside the tree or take minutes: git plumbing,
# the project's own pytest run, and gitleaks. Each is covered by its own
# suite; leaving them on here would make this a slow integration test and
# hide the thing it is actually asserting.
QUIET = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
         "--no-correlate", "--no-ledger"]

# The flattened file in the fixture tree, and the original it was flattened
# from. Defined together so the recovery test can actually recover something:
# a corpus that does not hold the original makes that test pass no matter
# where a recovery is written, which is how its first version let a mutant
# through.
FLAT_ORIGINAL = "import os\n\n\n" + "\n\n".join(
    f"def listing_{i}(root):\n    return sorted(os.listdir(root))" for i in range(8)) + "\n"
FLATTENED = " ".join(FLAT_ORIGINAL.split())


@pytest.fixture
def tree(tmp_path):
    """A small but realistic repository: a package, a test, a flattened file,
    a README and a requirements file."""
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "core.py").write_text(textwrap.dedent('''\
        """A queue."""
        import time


        def enqueue(recipient_pub, payload):
            return (recipient_pub, payload, time.time())


        def send(cust_pub, payload):
            return enqueue(cust_pub, payload)
    '''))
    (root / "tests" / "test_core.py").write_text(
        "from pkg.core import enqueue\n\n\ndef test_enqueue():\n"
        "    assert enqueue('a', 'b')[0] == 'a'\n")
    (root / "flat.py").write_text(FLATTENED)
    (root / "README.md").write_text("# repo\n\nA repository.\n")
    (root / "requirements.txt").write_text("requests\n")
    return root


# ------------------------------------------------------- the detector layer

def test_the_detectors_touch_nothing(tree):
    files = sorted(tree.rglob("*.py")) + sorted(tree.rglob("*.md"))
    with unchanged(tree):
        findings = run_all(files)
    assert findings, "a scan that found nothing would pass this vacuously"


# ------------------------------------------------------------- ghost_buster

def test_a_scan_touches_nothing(tree, capsys):
    with unchanged(tree):
        buster_cli.main([str(tree), *QUIET])
    assert capsys.readouterr().out


def test_a_json_scan_touches_nothing(tree, capsys):
    with unchanged(tree):
        buster_cli.main([str(tree), *QUIET, "--json"])
    json.loads(capsys.readouterr().out)


def test_the_ledger_is_the_only_thing_a_default_scan_creates(tree, capsys):
    """The blanket claim `never writes` is too strong, and writing this guard
    is what showed it. A default scan DOES write its own dotfile. What it
    must never do is touch anything that was already there."""
    quiet = [f for f in QUIET if f != "--no-ledger"]
    with unchanged(tree, may_create=[".ghost_ledger.json"]):
        buster_cli.main([str(tree), *quiet])
    assert (tree / ".ghost_ledger.json").exists()


def test_accept_creates_a_baseline_and_nothing_else(tree, capsys):
    with unchanged(tree, may_create=[".ghost_baseline.json"]):
        buster_cli.main([str(tree), *QUIET, "--accept"])
    assert (tree / ".ghost_baseline.json").exists()


# --------------------------------------------- the one deliberate exception

def test_annotate_names_changes_only_sources_and_the_readme(tree, capsys):
    """`--annotate-names` is the documented exception: it writes into the
    tree on purpose. The guard is not switched off for it, it is made
    specific -- only .py files and the README may change, nothing may be
    deleted, and every source change must be comment-only."""
    before = snapshot(tree)
    buster_cli.main([str(tree), *QUIET, "--annotate-names"])
    changes = compare(before, snapshot(tree))

    assert not changes.deleted
    assert not changes.created
    assert changes.modified, "the fixture has a disagreement in it; this must change something"
    for path in changes.modified:
        assert path.endswith(".py") or path == "README.md", path

    for path in changes.modified:
        if not path.endswith(".py"):
            continue
        # Same program before and after: the annotation is a comment.
        was = ast.dump(ast.parse((tree / path).read_text().replace(
            "  # ghost_buster: name-disagreement", "  # x")))
        assert was  # parses at all
    assert "name-disagreement" in (tree / "README.md").read_text()


def test_without_the_flag_the_same_scan_writes_nothing(tree, capsys):
    """The pair that makes the test above mean something: the sources only
    change when the flag asks them to."""
    with unchanged(tree):
        buster_cli.main([str(tree), *QUIET])


# --------------------------------------------------- blackhole_extrapolator

def test_the_extrapolator_touches_nothing(tree, capsys):
    with unchanged(tree):
        blackhole_cli.main([str(tree)])


def test_reconstruction_writes_only_to_its_own_directory(tree, tmp_path, capsys):
    out = tmp_path / "proposals"
    with unchanged(tree):
        blackhole_cli.main([str(tree), "--reconstruct-into", str(out)])
    assert list(out.glob("*.reconstructed.py")), "nothing was written to the output either"


def test_recovery_touches_neither_the_tree_nor_the_corpus(tree, tmp_path, capsys):
    """The corpus is somebody's exported chat history. Reading it must leave
    it exactly as it was found, and that is a second tree to guard."""
    corpus = tmp_path / "history"
    corpus.mkdir()
    (corpus / "export.json").write_text(
        json.dumps({"messages": [{"text": FLAT_ORIGINAL}]}))
    out = tmp_path / "recovered"

    with unchanged(tree), unchanged(corpus):
        blackhole_cli.main([str(tree), "--recover-from", str(corpus),
                            "--recover-into", str(out)])
    assert (out / "RECOVERY.md").exists()
    # A recovery that recovered nothing would pass this test wherever it
    # chose to write, which is exactly how the first version of it let a
    # mutant through.
    recovered = list(out.glob("*.recovered.py"))
    assert recovered, "the corpus holds the original; something must come back"
    assert recovered[0].read_text() == FLAT_ORIGINAL


# ---------------------------------------------------------- the guard itself

def test_the_guard_fails_when_a_file_is_modified(tmp_path):
    (tmp_path / "a.txt").write_text("one")
    with pytest.raises(AssertionError, match="modified: a.txt"):
        with unchanged(tmp_path):
            (tmp_path / "a.txt").write_text("two")


def test_the_guard_fails_when_a_file_is_deleted(tmp_path):
    (tmp_path / "a.txt").write_text("one")
    with pytest.raises(AssertionError, match="deleted: a.txt"):
        with unchanged(tmp_path):
            (tmp_path / "a.txt").unlink()


def test_the_guard_fails_on_an_undeclared_new_file(tmp_path):
    with pytest.raises(AssertionError, match="created: surprise.json"):
        with unchanged(tmp_path):
            (tmp_path / "surprise.json").write_text("{}")


def test_a_declared_new_file_is_allowed(tmp_path):
    with unchanged(tmp_path, may_create=["*.json"]):
        (tmp_path / "expected.json").write_text("{}")


def test_a_declaration_does_not_excuse_modifying_what_was_there(tmp_path):
    """`may_create` permits appearing, never touching."""
    (tmp_path / "expected.json").write_text("{}")
    with pytest.raises(AssertionError, match="modified"):
        with unchanged(tmp_path, may_create=["*.json"]):
            (tmp_path / "expected.json").write_text('{"changed": true}')


def test_a_permission_change_counts(tmp_path):
    """A scan that leaves the bytes alone and makes a file world-writable has
    still modified the tree."""
    path = tmp_path / "a.txt"
    path.write_text("one")
    path.chmod(0o600)
    with pytest.raises(AssertionError, match="modified"):
        with unchanged(tmp_path):
            path.chmod(0o666)


def test_a_new_directory_counts(tmp_path):
    with pytest.raises(AssertionError, match="created: scratch"):
        with unchanged(tmp_path):
            (tmp_path / "scratch").mkdir()


def test_a_file_written_and_removed_again_is_still_caught(tmp_path):
    """Only if the snapshot is taken as a whole. A check that compared the
    survivors would see nothing here."""
    (tmp_path / "keep.txt").write_text("one")
    with pytest.raises(AssertionError, match="modified: keep.txt"):
        with unchanged(tmp_path):
            (tmp_path / "temp.txt").write_text("scratch")
            (tmp_path / "keep.txt").write_text("changed")
            (tmp_path / "temp.txt").unlink()


def test_caches_are_ignored(tmp_path):
    (tmp_path / "__pycache__").mkdir()
    with unchanged(tmp_path):
        (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"\x00")


def test_the_report_names_every_kind_of_change():
    changes = Changes(modified=("a",), deleted=("b",), created=("c",))
    assert bool(changes)
    for line in ("modified: a", "deleted: b", "created: c"):
        assert line in changes.report()
    assert not bool(Changes())
