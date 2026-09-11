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
        BLOCKED = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]


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
        BLOCKED = {"a", "b", "c", "d", "e", "f", "g", "h", "i", "j"}
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


def test_a_call_whose_argument_another_call_receives_is_not_invariant(tmp_path):
    """operate.py: `remedy(root, files)` then `rescan(files)`. The remedy
    edited what `files` names, so the rescan is not the same work twice.
    The first serum reported it; this is that lesson."""
    files = _tree(tmp_path, {"m.py": '''\
        def operate(root, files, remedies):
            for remedy in remedies:
                remedy(root, files)
                after = rescan(files)
                commit(root, "cut")
    '''})
    assert find_pitstops(files) == []


def test_a_method_called_on_the_argument_is_a_change(tmp_path):
    """mutation.py: `scratch.restore(original)` after `_run_test(scratch, ...)`."""
    files = _tree(tmp_path, {"m.py": '''\
        def run(scratch, cand, timeout, mutants):
            for mutant in mutants:
                outcome = run_test(scratch, cand, timeout)
                scratch.restore(mutant)
    '''})
    assert find_pitstops(files) == []


def test_assigning_into_the_argument_is_a_change(tmp_path):
    files = _tree(tmp_path, {"m.py": '''\
        def fill(table, keys):
            for k in keys:
                total = summarise(table)
                table[k] = total
    '''})
    assert find_pitstops(files) == []


def test_reads_through_cheap_builtins_and_constructors_do_not_count(tmp_path):
    """The shape the first serum got right: `_portable_path(path)` in a loop
    whose other calls only read `path` through `str(...)` and a
    constructor. Still a pitstop."""
    files = _tree(tmp_path, {"m.py": '''\
        def report(path, nodes, out):
            for node in nodes:
                out.append(Finding(file=str(path), summary=portable(path), line=node.lineno))
    '''})
    found = find_pitstops(files)
    assert [p.kind for p in found] == [INVARIANT_CALL]
    assert "portable(...)" in found[0].what


def test_membership_against_a_tiny_constant_is_not_a_pitstop(tmp_path):
    """`name in ("self", "cls")` costs what a set costs. The first serum
    reported three of these; hoisting them changed nothing measurable."""
    files = _tree(tmp_path, {"m.py": '''\
        SELF = ("self", "cls")
        BIG = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"]

        def go(names):
            out = []
            for n in names:
                if n in SELF:
                    continue
                if n in BIG:
                    out.append(n)
            return out
    '''})
    found = find_pitstops(files)
    assert [p.what for p in found] == ["`in BIG`, a module-level list"]


def test_a_memo_computed_once_behind_a_none_check_is_not_a_pitstop(tmp_path):
    """`if x is None: x = f(root)` inside a loop runs f once, not once per
    pass. The last pitstop the first serum left on ghost_tools was exactly
    this shape in detect_missing_imports."""
    files = _tree(tmp_path, {"m.py": '''\
        def scan(root, nodes):
            declares = None
            out = []
            for node in nodes:
                if declares is None:
                    declares = manifest(root)
                out.append((node, declares))
            return out
    '''})
    assert find_pitstops(files) == []


def test_a_container_built_fresh_and_filled_each_pass_is_not_a_pitstop(tmp_path):
    """cns_map.py: `all_hashes = defaultdict(set)` at the top of each pass,
    then `all_hashes[h].add(repo)`. The argument never changes; the
    contents do, every pass. Hoisting it would share one container across
    passes. The third serum reported two of these."""
    files = _tree(tmp_path, {"m.py": '''\
        def group(records, root, base):
            for name, recs in records.items():
                by_hash = defaultdict(set)
                for x in recs:
                    by_hash[x["hash"]].add(x["repo"])
                kinds = defaultdict(int)
                for x in recs:
                    kinds[x["kind"]] += 1
                bucket = make_bucket(root)
                bucket.append(recs)
                index = make_index(base)
                for x in recs:
                    index[x["id"]] = x
                yield by_hash, kinds, bucket, index
    '''})
    assert find_pitstops(files) == []


def test_a_call_whose_result_is_only_read_is_still_a_pitstop(tmp_path):
    """The accumulator rule is about filling, not binding. A result that is
    bound and then read stays the same work every pass."""
    files = _tree(tmp_path, {"m.py": '''\
        def scan(items, root):
            out = []
            for item in items:
                cfg = load(root)
                out.append(item + cfg["key"])
            return out
    '''})
    found = find_pitstops(files)
    assert [p.kind for p in found] == [INVARIANT_CALL]


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
        def cheap(items, label):
            out = []
            for item in items:
                out.append((str(label), len(label)))
            return out


        def real(items, label):
            out = []
            for item in items:
                out.append(sorted(label))
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
        BLOCKED = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]


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
        BLOCKED = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]


        def test_it():
            for i in range(3):
                assert i in BLOCKED or True
    '''})
    assert find_pitstops(files) == []


def test_the_finding_is_minor_and_says_why(tmp_path):
    files = _tree(tmp_path, {"m.py": '''\
        BLOCKED = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]


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
