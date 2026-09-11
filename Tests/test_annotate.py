"""The only part of ghost_buster that writes to the tree it was pointed at.

Every test here is about the same promise: a note is a comment and a table,
and neither can change what a program means. The promise is not kept by
being careful -- it is kept by parsing before and after and refusing the
edit if the syntax tree moved. These tests are what prove the refusal
actually happens.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from ghost_buster.annotate import (
    BEGIN,
    END,
    MARKER,
    annotate,
    annotate_source,
    notes_for,
    render_section,
    strip_notes,
    update_readme,
)
from ghost_buster.naming import find_name_disagreements


def _tree(tmp_path: Path, files: dict) -> list:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return sorted(tmp_path.glob("*.py"))


PAIR = {
    "queue.py":
        "def enqueue(recipient_pub, payload):\n"
        "    return (recipient_pub, payload)\n",
    "caller.py":
        "def send(cust_pub, payload):\n"
        "    return enqueue(cust_pub, payload)\n",
}


# ------------------------------------------------------------ the invariant

def test_an_annotated_file_is_the_same_program(tmp_path):
    files = _tree(tmp_path, PAIR)
    annotate(files, tmp_path / "README.md", root=tmp_path)
    for path in files:
        text = path.read_text()
        assert MARKER in text, path.name
        assert ast.dump(ast.parse(text)) == ast.dump(ast.parse(strip_notes(text)))


def test_a_note_lands_on_the_signature_and_on_the_call(tmp_path):
    files = _tree(tmp_path, PAIR)
    annotate(files, tmp_path / "README.md", root=tmp_path)
    queue = (tmp_path / "queue.py").read_text().splitlines()
    caller = (tmp_path / "caller.py").read_text().splitlines()
    # The signature is told what its callers write...
    assert "`recipient_pub` is `cust_pub` at every call site" in queue[0]
    # ...and the call is told what the signature calls it.
    assert "`cust_pub` is `recipient_pub` in the signature" in caller[1]


def test_running_twice_is_the_same_as_running_once(tmp_path):
    """Trailing comments, stripped and rewritten whole, so a re-run follows a
    rename instead of piling up behind one."""
    files = _tree(tmp_path, PAIR)
    readme = tmp_path / "README.md"
    annotate(files, readme, root=tmp_path)
    once = {p.name: p.read_text() for p in files} | {"README.md": readme.read_text()}
    annotate(files, readme, root=tmp_path)
    twice = {p.name: p.read_text() for p in files} | {"README.md": readme.read_text()}
    assert once == twice
    for text in once.values():
        assert text.count(MARKER) <= 2


def test_a_note_that_no_longer_applies_is_removed(tmp_path):
    """The interesting file is the one that USED to have something to say.
    A rename settles the disagreement, it vanishes from the results, and a
    sweep driven by the results alone would never look at that file again --
    leaving a note behind describing a disagreement that no longer exists."""
    files = _tree(tmp_path, PAIR)
    readme = tmp_path / "README.md"
    annotate(files, readme, root=tmp_path)
    assert MARKER in (tmp_path / "caller.py").read_text()

    # The caller adopts the parameter's name, and the pair is gone.
    (tmp_path / "caller.py").write_text(
        "def send(recipient_pub, payload):  # " + MARKER + " -- stale\n"
        "    return enqueue(recipient_pub, payload)\n")
    disagreements, _, _ = annotate(files, readme, root=tmp_path)
    assert disagreements == []
    assert MARKER not in (tmp_path / "caller.py").read_text()
    assert MARKER not in (tmp_path / "queue.py").read_text()


def test_a_line_number_never_moves(tmp_path):
    """The reason the notes are trailing and not lines of their own: a run
    that inserted lines would invalidate every line number below it."""
    files = _tree(tmp_path, PAIR)
    before = {p: len(p.read_text().splitlines()) for p in files}
    annotate(files, tmp_path / "README.md", root=tmp_path)
    assert {p: len(p.read_text().splitlines()) for p in files} == before


# --------------------------------------------------- lines that cannot take one

def test_a_marker_inside_a_string_is_not_a_note(tmp_path):
    """Found the first time this ran against a fixture containing one. The
    strip is per-line and verified, so a string that merely looks like a note
    survives -- and the real notes elsewhere in the file are still written."""
    source = (
        "def send(cust_pub):\n"
        '    banner = "# ' + MARKER + ' -- not a comment"\n'
        "    return (enqueue(cust_pub), banner)\n"
    )
    out = annotate_source(source, {3: ["`cust_pub` is `recipient_pub` in the signature"]})
    assert "not a comment" in out
    assert out.splitlines()[2].endswith("in the signature")
    assert ast.dump(ast.parse(out)) == ast.dump(ast.parse(source))


def test_a_backslash_continuation_is_left_alone(tmp_path):
    """A comment cannot follow a backslash, and the line below still can."""
    source = "def send(a, b):\n    return a \\\n        + b\n"
    out = annotate_source(source, {2: ["note"], 3: ["note"]})
    assert out.splitlines()[1].endswith("\\")
    assert MARKER in out.splitlines()[2]


def test_a_blank_line_is_never_annotated(tmp_path):
    """A comment on a blank line is valid Python, so the syntax-tree check
    does not refuse it. It is refused because a note with nothing above it
    is noise, which is a judgement and therefore needs its own guard."""
    source = "def send(\n\n    cust_pub):\n    return cust_pub\n"
    assert annotate_source(source, {2: ["note"]}) == source


def test_a_line_inside_a_triple_quoted_string_is_refused(tmp_path):
    source = 'DOC = """\nline two\n"""\n'
    assert annotate_source(source, {2: ["note"]}) == source


def test_a_file_that_does_not_parse_is_never_touched(tmp_path):
    source = "def broken(:\n"
    assert annotate_source(source, {1: ["note"]}) == source


def test_crlf_survives(tmp_path):
    source = "def enqueue(recipient_pub):\r\n    return recipient_pub\r\n"
    out = annotate_source(source, {1: ["note"]})
    assert out.splitlines(keepends=True)[0].endswith("\r\n")
    assert out.splitlines()[0].endswith("-- note")


def test_a_last_line_without_a_newline_stays_that_way(tmp_path):
    source = "x = 1"
    out = annotate_source(source, {1: ["note"]})
    assert MARKER in out and not out.endswith("\n")


def test_two_notes_share_one_line(tmp_path):
    source = "def send(a, b):\n    return f(a, b)\n"
    out = annotate_source(source, {2: ["second", "first"]})
    assert out.splitlines()[1].endswith("-- first; second")


# ----------------------------------------------------------------- the README

def test_the_readme_block_is_replaced_not_appended(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n\nIntro.\n\n" + BEGIN + "\nstale\n" + END + "\n\nOutro.\n")
    files = _tree(tmp_path, PAIR)
    update_readme(readme, find_name_disagreements(files), root=tmp_path)
    text = readme.read_text()
    assert text.count(BEGIN) == 1
    assert "stale" not in text
    assert text.startswith("# Project") and text.rstrip().endswith("Outro.")
    assert "`recipient_pub`" in text and "`cust_pub`" in text


def test_a_readme_that_documents_the_markers_is_not_eaten(tmp_path):
    """The README that explains this feature necessarily contains the marker
    as prose, and the first run against one wrote the generated block over
    the documentation. A marker counts only on a line of its own."""
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Project\n\nThe table sits between `" + BEGIN + "` markers.\n\n"
        + BEGIN + "\nstale\n" + END + "\n")
    files = _tree(tmp_path, PAIR)
    update_readme(readme, find_name_disagreements(files), root=tmp_path)
    text = readme.read_text()
    assert "The table sits between" in text
    assert "stale" not in text
    assert text.count(BEGIN) == 2  # the prose mention, and the real one


def test_a_readme_without_markers_gains_a_block(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n")
    files = _tree(tmp_path, PAIR)
    assert update_readme(readme, find_name_disagreements(files), root=tmp_path)
    text = readme.read_text()
    assert text.startswith("# Project") and BEGIN in text and END in text


def test_a_clean_run_still_records_that_it_ran(tmp_path):
    """An empty table is a fact. A missing block is an absence of one."""
    section = render_section([], root=tmp_path)
    assert "No disagreements" in section and BEGIN in section
    # The table itself survives too, so the block reads as an empty list
    # rather than as a heading somebody forgot to fill in.
    assert "| parameter | variable | call sites | files |" in section
    assert "| _none_ |" in section


def test_the_block_carries_no_timestamp(tmp_path):
    """A run that changes nothing must produce no diff, or the table becomes
    something people stop reading."""
    readme = tmp_path / "README.md"
    files = _tree(tmp_path, PAIR)
    d = find_name_disagreements(files)
    assert update_readme(readme, d, root=tmp_path) is True
    assert update_readme(readme, d, root=tmp_path) is False


def test_paths_in_the_table_are_relative_to_the_scan(tmp_path):
    files = _tree(tmp_path, PAIR)
    section = render_section(find_name_disagreements(files), root=tmp_path)
    assert "`queue.py`" in section
    assert str(tmp_path) not in section


# ----------------------------------------------------------------- the mapping

def test_every_disagreement_reaches_both_records(tmp_path):
    files = _tree(tmp_path, PAIR)
    d = find_name_disagreements(files)
    notes = notes_for(d)
    assert {Path(p).name for p in notes} == {"queue.py", "caller.py"}
    assert len(d) == 1
    assert "| `recipient_pub` | `cust_pub` |" in render_section(d, root=tmp_path)
