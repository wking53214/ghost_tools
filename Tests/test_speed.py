"""Pitstops: work done more often than it needs to be.

Two kinds of evidence, tested separately. The static detectors read a
shape off the tree and say so at MINOR. The profiler counts what a run
actually did, which is the only way the 9.5-parses-per-file finding could
ever have been found.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from ghost_buster import corpus
from ghost_buster.schema import Category, Layer, Severity, Status
from ghost_buster.speed import (
    INVARIANT_CALL,
    LIST_IN_LOOP,
    Profile,
    detect_pitstops,
    find_pitstops,
)


def _tree(tmp_path: Path, files: dict) -> list:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    corpus.reset()
    return sorted(tmp_path.rglob("*.py"))


# ------------------------------------------------------------- static

def test_a_list_membership_inside_a_loop_is_a_pitstop(tmp_path):
    files = _tree(tmp_path, {"m.py": '''\
        BLOCKED = ["a", "b", "c"]


        def scan(items):
            hits = 0
            for item in items:
                if item in BLOCKED:
                    hits += 1
            return hits
    '''})
    found = find_pitstops(files)
    assert [p.kind for p in found] == [LIST_IN_LOOP]
    assert found[0].line == 7


def test_membership_against_a_set_is_not(tmp_path):
    """The tree KNOWS the container is a list only when it saw the literal.
    A set, or a name it cannot see bound, is left alone."""
    files = _tree(tmp_path, {"m.py": '''\
        BLOCKED = {"a", "b"}
        OTHER = load()


        def scan(items):
            return sum(1 for i in items if i in BLOCKED or i in OTHER)
    '''})
    assert find_pitstops(files) == []


def test_a_call_whose_arguments_never_change_is_a_pitstop(tmp_path):
    files = _tree(tmp_path, {"m.py": '''\
        def scan(items, root):
            out = []
            for item in items:
                cfg = load(root)
                out.append(item + cfg)
            return out
    '''})
    found = find_pitstops(files)
    assert [p.kind for p in found] == [INVARIANT_CALL]
    assert "load(...)" in found[0].what


def test_a_name_bound_inside_the_loop_varies(tmp_path):
    """The first version checked only the loop target and reported 295
    invariant calls against ghost_tools, the first of them
    `_identifiers(tree)` inside `for path in paths: tree = _parse(path)`.
    `tree` is stored in the body, so it changes every pass."""
    files = _tree(tmp_path, {"m.py": '''\
        def scan(paths):
            out = []
            for path in paths:
                tree = parse(path)
                out.extend(identifiers(tree))
            return out
    '''})
    assert find_pitstops(files) == []


def test_a_constant_time_builtin_is_not_worth_hoisting(tmp_path):
    """55 of 67 survivors on ghost_tools were str/len/type. Invariant, and
    not worth a line in anyone's report."""
    files = _tree(tmp_path, {"m.py": '''\
        def scan(items, label):
            out = []
            for item in items:
                out.append((str(label), len(label), sorted(label)))
            return out
    '''})
    found = find_pitstops(files)
    assert [p.what for p in found] == ["`sorted(...)` with arguments the loop never changes"]


def test_a_call_that_uses_the_loop_variable_is_not(tmp_path):
    files = _tree(tmp_path, {"m.py": '''\
        def scan(items, root):
            return [load(root, item) for item in items]
    '''})
    assert find_pitstops(files) == []


def test_the_same_shape_outside_a_loop_is_not_a_pitstop(tmp_path):
    files = _tree(tmp_path, {"m.py": '''\
        BLOCKED = ["a"]


        def check(item, root):
            cfg = load(root)
            return item in BLOCKED and cfg
    '''})
    assert find_pitstops(files) == []


def test_a_nested_loop_reports_what_it_contains_once(tmp_path):
    """The first run against ghost_tools reported one line three times: an
    inner loop's body is also the outer loop's body."""
    files = _tree(tmp_path, {"m.py": '''\
        BLOCKED = ["a"]


        def scan(rows, root):
            for row in rows:
                for cell in row:
                    if cell in BLOCKED:
                        return load(root)
    '''})
    found = find_pitstops(files)
    assert len(found) == len(set(found)) == 2


def test_tests_are_left_alone(tmp_path):
    files = _tree(tmp_path, {"tests/test_m.py": '''\
        BLOCKED = ["a"]


        def test_it():
            for i in range(3):
                assert i in BLOCKED or True
    '''})
    assert find_pitstops(files) == []


def test_the_finding_is_minor_and_says_why(tmp_path):
    files = _tree(tmp_path, {"m.py": '''\
        BLOCKED = ["a"]


        def scan(items):
            for item in items:
                if item in BLOCKED:
                    return item
    '''})
    f = detect_pitstops(files)[0]
    assert f.detector == LIST_IN_LOOP
    assert f.category is Category.COMPLEXITY
    assert f.layer is Layer.MECHANICAL
    assert f.status is Status.CONFIRMED
    assert f.severity is Severity.MINOR
    assert "four million" in f.detail
    assert "--profile" in f.detail


# ----------------------------------------------------------- measured

def test_the_profiler_counts_repeated_identical_work(tmp_path):
    src = "x = 1\n"
    with Profile() as prof:
        for _ in range(4):
            ast.parse(src)
        ast.parse("y = 2\n")
    parse = next(r for r in prof.redundancies() if r.what == "ast.parse")
    assert parse.calls == 5
    assert parse.distinct == 2
    assert parse.repeated == 3
    assert parse.share == 0.6
    assert "3 repeated" in prof.render()
    assert "nothing was done twice" not in prof.render()


def test_the_profiler_restores_what_it_wrapped():
    real = ast.parse
    with Profile():
        assert ast.parse is not real
    assert ast.parse is real


def test_the_profiler_sees_repeated_reads(tmp_path):
    p = tmp_path / "f.py"
    p.write_text("x = 1\n")
    with Profile() as prof:
        p.read_text()
        p.read_text()
        p.read_bytes()
    read = next(r for r in prof.redundancies() if r.what == "read")
    assert read.calls == 3 and read.distinct == 1


def test_nothing_repeated_says_so(tmp_path):
    with Profile() as prof:
        ast.parse("a = 1\n")
        ast.parse("b = 2\n")
    assert "nothing was done twice" in prof.render()


def test_run_all_now_parses_once_under_the_profiler(tmp_path):
    """The 9.5x finding, as a regression test: the corpus means a full run
    never parses the same file twice."""
    from ghost_buster.mechanical import run_all
    files = _tree(tmp_path, {"a.py": "def f():\n    return 1\n", "b.py": "def g():\n    return 2\n"})
    with Profile() as prof:
        run_all(files)
    parse = next(r for r in prof.redundancies() if r.what == "ast.parse")
    assert parse.repeated == 0, prof.render()
