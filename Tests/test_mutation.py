"""test_mutation.py -- the mutation mode, exercised on synthetic projects.

Each test builds a tiny project under tmp_path (source module + test file),
runs the real mutation pipeline (real scratch copy, real pytest subprocess),
and checks the verdict. The projects are deliberately minimal so a failure
here points at the mode, not at the fixture.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ghost_buster.mutation import (
    Candidate, find_candidates, render_run, run_mutations,
)
from ghost_buster.schema import Category, Severity, Status

SOURCE = '''
from enum import Enum

class Colour(Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"

def threshold_ok(value, limit=3):
    return value >= limit

class Counter:
    def __init__(self):
        self.n = 0
    def bump(self):
        self.n += 1
        return self.n
'''


def _project(tmp_path: Path, tests: str) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text(SOURCE, encoding="utf-8")
    (root / "test_mod.py").write_text(tests, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    return root


def _files(root: Path):
    return sorted(root.rglob("*.py"))


def _run(root: Path, **kw):
    return run_mutations(root, _files(root), timeout=60, link_siblings=False, **kw)


# ---------------------------------------------------------------- discovery

def test_finds_each_candidate_shape(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok, Counter, Colour

def test_weak():
    result = threshold_ok(5)
    assert result is not None

def test_unused():
    c = Counter()
    n = c.bump()
    assert c is not None

def test_guarded():
    if threshold_ok(1):
        assert False

def test_restated():
    assert [c.value for c in Colour] == ["red", "green", "blue"]

def test_strong():
    assert threshold_ok(5) is True
    assert threshold_ok(1) is False
''')
    shapes = {(c.test_name, c.shape) for c in find_candidates(root, _files(root))}
    assert ("test_weak", "weak_assertion") in shapes
    assert ("test_unused", "unused_result") in shapes
    assert ("test_guarded", "guarded_assertion") in shapes
    assert ("test_restated", "restated_set") in shapes
    assert not any(name == "test_strong" for name, _ in shapes)


def test_resolves_targets_through_imports_and_instances(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok, Counter

def test_weak():
    c = Counter()
    assert threshold_ok(5) is not None
    assert c.bump() > 0
''')
    cand = next(c for c in find_candidates(root, _files(root)) if c.test_name == "test_weak")
    names = {q for _, q in cand.targets}
    assert names == {"threshold_ok", "Counter.bump"}


# ---------------------------------------------------------------- verdicts

def test_weak_assertion_survives_a_mutation_and_becomes_a_finding(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok

def test_threshold_is_checked():
    result = threshold_ok(5)
    assert result is not None
''')
    run = _run(root)
    assert len(run.survived) == 1, render_run(run, verbose=True)
    finding = run.findings[0]
    assert finding.category is Category.VACUOUS_CHECK
    assert finding.status is Status.CONFIRMED and finding.severity is Severity.MAJOR
    assert "test_threshold_is_checked" in finding.summary
    assert "threshold_ok" in finding.detail
    assert finding.evidence.line_start == 4


def test_a_test_that_does_its_job_kills_every_mutant(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok

def test_threshold_is_checked():
    assert threshold_ok(5) is True
    assert threshold_ok(1) is False
    assert threshold_ok(3) is True
''')
    # Force the strong test into the candidate list so its mutants actually run.
    files = _files(root)
    run = run_mutations(root, files, timeout=60, link_siblings=False)
    assert run.findings == []
    strong = Candidate(root / "test_mod.py", "test_threshold_is_checked", 4, "weak_assertion", "forced",
                       targets=[(root / "mod.py", "threshold_ok")])
    from ghost_buster import mutation as m
    original = m.find_candidates
    m.find_candidates = lambda r, f: [strong]
    try:
        run = run_mutations(root, files, timeout=60, link_siblings=False)
    finally:
        m.find_candidates = original
    assert run.survived == [] and len(run.killed) >= 1, render_run(run, verbose=True)


def test_guard_never_taken_is_critical(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok

def test_guarded():
    status = "never"
    if status == "APPROVED":
        assert threshold_ok(0)
''')
    run = _run(root)
    assert len(run.survived) == 1, render_run(run, verbose=True)
    assert run.findings[0].severity is Severity.CRITICAL
    assert "never runs its guarded assertions" in run.findings[0].summary


def test_if_else_that_asserts_on_both_sides_is_a_branch_not_a_guard(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok

def test_branch():
    if threshold_ok(0):
        assert False
    else:
        assert threshold_ok(5)
''')
    assert not any(c.shape == "guarded_assertion" for c in find_candidates(root, _files(root)))


def test_guard_that_hides_nothing_is_not_a_finding(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok

def test_guarded_but_true():
    if threshold_ok(5):
        assert threshold_ok(5)
''')
    run = _run(root)
    assert run.findings == [], render_run(run, verbose=True)
    assert len(run.killed) == 1


def test_restated_enum_survives_a_new_member(tmp_path):
    root = _project(tmp_path, '''
from mod import Colour

def test_colours_are_exactly_these():
    assert {"red", "green", "blue"} <= {c.value for c in Colour}
''')
    # A subset check restates the members by hand and cannot notice a new
    # one: adding an enum member does not fail it, so it guards nothing.
    run = _run(root)
    assert any(m.operator == "extend_set" and m.outcome == "survived" for m in run.mutants), render_run(run, verbose=True)


def test_restated_list_that_is_really_checked_is_killed(tmp_path):
    root = _project(tmp_path, '''
from mod import Colour

def test_colours_are_exactly_these():
    assert [c.value for c in Colour] == ["red", "green", "blue"]
''')
    run = _run(root)
    assert run.findings == [], render_run(run, verbose=True)
    assert any(m.operator == "extend_set" and m.outcome == "killed" for m in run.mutants)


# ---------------------------------------------------------------- honesty

def test_a_test_that_fails_unmutated_is_reported_unjudged_not_as_a_finding(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok

def test_broken_before_we_touch_it():
    result = threshold_ok(5)
    assert result is not None
    raise RuntimeError("broken fixture, not a vacuous check")
''')
    run = _run(root)
    assert run.findings == [] and run.mutants == []
    assert len(run.unjudged) == 1 and "does not pass unmutated" in run.unjudged[0][1]


def test_working_tree_is_never_modified(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok

def test_weak():
    assert threshold_ok(5) is not None
''')
    before = {p: p.read_text() for p in _files(root)}
    _run(root)
    after = {p: p.read_text() for p in _files(root)}
    assert before == after
    assert not any(p.name.startswith("ghost_mutate_") for p in root.iterdir())


def test_render_names_the_mutation(tmp_path):
    root = _project(tmp_path, '''
from mod import threshold_ok

def test_weak():
    assert threshold_ok(5) is not None
''')
    text = render_run(_run(root), verbose=True)
    assert "vacuous_check" in text and "test_weak" in text and "threshold_ok" in text


def test_cli_mutate_flag_emits_findings_as_json(tmp_path, capsys):
    root = _project(tmp_path, '''
from mod import threshold_ok

def test_weak():
    assert threshold_ok(5) is not None
''')
    from ghost_buster.cli import main
    rc = main([str(root), "--mutate", "--json", "--mutate-timeout", "60"])
    out = capsys.readouterr().out
    assert rc == 1                       # a MAJOR finding sets the exit status
    assert '"vacuous_check"' in out and "test_weak" in out


@pytest.mark.parametrize("operator", ["drop_body", "return_none", "flip_compare", "bump_constants"])
def test_each_operator_changes_the_function(operator):
    import ast
    from ghost_buster.mutation import _mutate_function
    tree = ast.parse("def f(x, limit=3):\n    if x >= limit:\n        return x\n    return 0\n")
    applied, description = _mutate_function(tree, "f", operator)
    assert applied, description
    assert ast.unparse(tree) != "def f(x, limit=3):\n    if x >= limit:\n        return x\n    return 0"
