"""A proposal for a flattened file, and the four things it must never do.

Measured across the 34 flattened files in a 37-repository library on
2026-09-10:

    indentation pass only (deterministic)   2 of 34 parse
    plus a keyword-splitting heuristic      0 of 34 parse
    median lines recovered                  1 -> 135

Those two numbers are the whole design. The deterministic pass sometimes
recovers a program. The heuristic pass never does, and makes the file
editable by a human, which is a different and still useful deliverable. A
tool that conflated them would hand somebody 135 lines of plausible
nonsense and call it a recovery.
"""
from __future__ import annotations

import textwrap

import pytest

from blackhole_extrapolator.reconstruct import (
    HEADER, reconstruct, write_proposal,
)

# A newline became one space; the indentation after it survived.
FLAT_RECOVERABLE = (
    'def outer(x):     """doc"""     if x:         return 1     return 0'
)
# No indentation survived at all: nothing here says where a line ended.
FLAT_UNRECOVERABLE = "import os import sys x = 1 y = 2 print(x + y)"


def test_the_deterministic_pass_can_recover_a_program():
    r = reconstruct(FLAT_RECOVERABLE)
    assert r.parses
    assert r.is_program
    assert r.passes == ["indent-runs"]
    assert r.lines > 1


def test_a_recovered_program_is_never_touched_by_the_heuristic():
    """Trading a program for a draft is strictly a loss. Measured: the
    keyword split broke both files the deterministic pass got right."""
    r = reconstruct(FLAT_RECOVERABLE)
    assert "heuristic-split" not in r.passes


def test_the_heuristic_runs_only_when_the_first_pass_failed():
    r = reconstruct(FLAT_UNRECOVERABLE)
    assert "heuristic-split" in r.passes
    assert r.lines > 1                      # it did recover line breaks
    assert not r.is_program                 # ...and claims nothing about them


# The heuristic CAN produce valid Python. `x = 1 import os` has no surviving
# indentation, so the deterministic pass leaves it alone and fails; splitting
# before `import` yields two statements that parse perfectly. It is still a
# guess, and this is the case that proves the distinction is real rather than
# theoretical.
FLAT_SPLIT_PARSES = "x = 1 import os"


def test_parsing_is_never_reported_as_correctness():
    """A guess that compiles is still a guess.

    The first version of this test wrapped its assertion in `if r.parses:`
    against a fixture that never parses, so the assertion never ran and the
    mutant that deleted the distinction survived.
    """
    r = reconstruct(FLAT_SPLIT_PARSES)
    assert "heuristic-split" in r.passes
    assert r.parses                          # it really is valid Python
    assert not r.is_program                  # ...and is still not a recovery
    assert "does NOT parse, and is not meant to" in r.render()


def test_the_rendered_header_says_which_it_is():
    prog = reconstruct(FLAT_RECOVERABLE).render()
    draft = reconstruct(FLAT_UNRECOVERABLE).render()
    assert HEADER in prog and HEADER in draft
    assert "NOT THE ORIGINAL" in prog
    assert "This parses." in prog
    assert "does NOT parse, and is not meant to" in draft
    for text in (prog, draft):
        assert "Nothing here was analysed" in text


# ------------------------------------------------- what it must never do

def test_it_writes_only_where_it_was_told(tmp_path):
    """ghost_buster has never modified a scanned repository, and that is
    what lets someone point it at thirty-seven of them overnight."""
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "flat.py"
    src.write_text(FLAT_RECOVERABLE)
    into = tmp_path / "proposals"

    before = sorted(p.name for p in repo.iterdir())
    target = write_proposal(src, into)

    assert target.parent == into
    assert sorted(p.name for p in repo.iterdir()) == before   # repo untouched
    assert src.read_text() == FLAT_RECOVERABLE                # original intact


def test_it_refuses_to_overwrite_an_existing_proposal(tmp_path):
    """An existing proposal may already be somebody's afternoon of edits."""
    src = tmp_path / "flat.py"
    src.write_text(FLAT_RECOVERABLE)
    into = tmp_path / "out"
    first = write_proposal(src, into)
    first.write_text("# edited by hand\n")

    with pytest.raises(FileExistsError):
        write_proposal(src, into)
    assert first.read_text() == "# edited by hand\n"


def test_a_proposal_is_not_valid_input_to_a_scan(tmp_path):
    """The header is a comment, so a proposal that parses would be scanned
    like source if it were written into the tree. It is not written into
    the tree, and this pins the reason it must not be."""
    src = tmp_path / "flat.py"
    src.write_text(FLAT_RECOVERABLE)
    target = write_proposal(src, tmp_path / "out")
    assert target.name.endswith(".reconstructed.py")
    assert HEADER in target.read_text()


def test_a_normal_file_is_left_entirely_alone():
    ordinary = textwrap.dedent('''
        def f(x):
            return x + 1
    ''')
    r = reconstruct(ordinary)
    assert r.text == ordinary
    assert r.parses


def test_a_file_that_is_one_giant_comment_is_not_a_recovered_program():
    """The SILENT flattening case. Its single line starts with `#`, so
    Python reads the whole file as a comment: it parses, raises nothing, and
    defines nothing.

    Measured 2026-09-10: the only two files in a 37-repository library that
    this reported as fully recovered were exactly these, at one line each.
    "Parses" was the wrong test; "parses and declares something" is right.
    """
    silent = "# governance_os_full.py # Gates class BaseGate: def __init__(self): pass"
    r = reconstruct(silent)
    assert not r.is_program
    assert not r.parses
