"""The hammer: one read, one policy, one tree, shared read-only.

The contract that makes sharing safe is that nobody mutates what they are
handed. That is not asserted here in prose; `test_no_detector_mutates_the_tree`
runs every registered detector and then compares every cached tree against
a fresh parse. If a detector ever starts editing in place, this is the test
that says so, and it says which file.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from ghost_buster import corpus
from ghost_buster.mechanical import registered_detectors, run_all


def _tree(tmp_path: Path, files: dict) -> list:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(textwrap.dedent(body))
    return sorted(tmp_path.rglob("*.py"))


GOOD = '''\
    import time


    class Gate:
        def allows(self, reading):
            return reading < 3


    def stamp(value):
        try:
            return (time.time(), value)
        except Exception:
            pass
'''


# ------------------------------------------------------------- one policy

def test_a_bad_byte_is_one_fact_for_everyone(tmp_path):
    """Until 2026-09-11 a file with one invalid byte was analysed by three
    detectors and invisible to fifteen. Now it is a reason, held once."""
    files = _tree(tmp_path, {
        "good.py": GOOD,
        "bad.py": b'def handler(x):\n    """caf\xe9 \xff"""\n    pass\n',
    })
    corpus.reset()
    assert corpus.parse(tmp_path / "bad.py") is None
    assert corpus.text(tmp_path / "bad.py") is None
    reason = corpus.failure(tmp_path / "bad.py")
    assert reason and "UnicodeDecodeError" in reason
    listed = corpus.unparsed(files)
    assert [p.name for p, _ in listed] == ["bad.py"]


def test_a_coding_cookie_is_honoured(tmp_path):
    """PEP 263. A latin-1 file that declares itself is valid Python and must
    parse; reading it as UTF-8 would have thrown it away."""
    files = _tree(tmp_path, {
        "latin.py": b'# -*- coding: latin-1 -*-\nNAME = "caf\xe9"\n',
    })
    corpus.reset()
    tree = corpus.parse(files[0])
    assert tree is not None
    assert corpus.text(files[0]) == '# -*- coding: latin-1 -*-\nNAME = "café"\n'
    assert corpus.unparsed(files) == []


def test_a_syntax_error_names_its_line(tmp_path):
    files = _tree(tmp_path, {"broken.py": "def f(:\n    pass\n"})
    corpus.reset()
    assert corpus.parse(files[0]) is None
    assert "SyntaxError at line 1" in corpus.failure(files[0])


def test_an_unreadable_file_is_a_reason_not_a_crash(tmp_path):
    """mechanical._parse used to let OSError escape and take the run down
    while three other detectors skipped the same file silently."""
    corpus.reset()
    missing = tmp_path / "gone.py"
    assert corpus.parse(missing) is None
    assert "FileNotFoundError" in corpus.failure(missing)


# ------------------------------------------------------------- the cache

def test_a_file_is_read_once_per_scan(tmp_path):
    files = _tree(tmp_path, {"a.py": GOOD, "b.py": GOOD})
    corpus.reset()
    for _ in range(5):
        for f in files:
            corpus.parse(f)
    st = corpus.stats()
    assert st["reads"] == 10
    assert st["hits"] == 8          # first touch of each file misses
    assert st["cached"] == 2


def test_a_changed_file_is_re_read(tmp_path):
    """Validated by mtime and size, so an edit between scans is seen."""
    files = _tree(tmp_path, {"a.py": "X = 1\n"})
    corpus.reset()
    first = corpus.parse(files[0])
    import os
    import time
    files[0].write_text("X = 2\nY = 3\n")
    os.utime(files[0], (time.time() + 5, time.time() + 5))
    second = corpus.parse(files[0])
    assert ast.dump(first) != ast.dump(second)
    assert len(second.body) == 2


def test_the_same_tree_object_is_shared(tmp_path):
    """Sharing means the same object, not an equal one -- that is what
    makes the read-only contract matter."""
    files = _tree(tmp_path, {"a.py": GOOD})
    corpus.reset()
    assert corpus.parse(files[0]) is corpus.parse(files[0])


def test_fresh_is_never_the_shared_tree(tmp_path):
    """The mutation engine edits trees in place. It asks for fresh() and
    gets a copy of its own, so its edits reach nobody else."""
    files = _tree(tmp_path, {"a.py": GOOD})
    corpus.reset()
    shared = corpus.parse(files[0])
    own = corpus.fresh(files[0])
    assert own is not shared
    own.body[0].names[0].name = "mutated"
    assert corpus.parse(files[0]).body[0].names[0].name == "time"


def test_reset_empties_the_cache(tmp_path):
    files = _tree(tmp_path, {"a.py": GOOD})
    corpus.reset()
    corpus.parse(files[0])
    assert corpus.stats()["cached"] == 1
    corpus.reset()
    assert corpus.stats() == {"reads": 0, "hits": 0, "cached": 0}


# ----------------------------------------------------------- the contract

def test_no_detector_mutates_the_tree(tmp_path):
    """Run every registered detector, then compare every cached tree to a
    fresh parse of the same bytes. A detector that edits in place corrupts
    every detector after it, and this is the only thing that would notice."""
    files = _tree(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/core.py": GOOD,
        "pkg/copy.py": GOOD,
        "tests/test_core.py": "from pkg.core import stamp\n\n\ndef test_it():\n    assert stamp(1)\n",
        "broken.py": "def f(:\n",
    })
    run_all(files)
    assert len(registered_detectors()) >= 18, "the contract must cover every detector"
    for path in files:
        source = corpus.read(path)
        if source.tree is None:
            continue
        assert ast.dump(source.tree) == ast.dump(ast.parse(path.read_bytes())), path.name


def test_the_contract_holds_on_ghost_tools_itself():
    """Not a fixture: the real package, every real detector."""
    root = Path(__file__).resolve().parent.parent / "ghost_buster"
    files = sorted(root.glob("*.py"))
    run_all(files)
    for path in files:
        source = corpus.read(path)
        assert source.tree is not None, f"{path.name}: {source.failure}"
        assert ast.dump(source.tree) == ast.dump(ast.parse(path.read_bytes())), path.name


def test_run_all_parses_each_file_exactly_once(tmp_path):
    """The 9.5-parses-per-file measurement, as a test. The stale entry
    planted first proves run_all resets the cache rather than inheriting
    whatever the previous scan left -- and does so without depending on
    which test ran before this one, which under xdist is nobody's promise."""
    files = _tree(tmp_path, {"a.py": GOOD, "b.py": GOOD, "c.py": GOOD})
    stale = tmp_path / "stale.py"
    stale.write_text("X = 1\n")
    corpus.parse(stale)
    run_all(files)
    st = corpus.stats()
    assert st["cached"] == 3, "the stale entry should have been reset away"
    assert st["reads"] - st["hits"] == 3
