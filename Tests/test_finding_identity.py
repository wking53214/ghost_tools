"""Two defects are never one finding.

A finding's id hashes detector, project-relative path and summary -- and
nothing else, deliberately, so that a finding which moves down a file when
an import is added is still the same finding. The cost of that choice is
that two findings agreeing on all three share an id.

That cost was measured, not imagined. On a 38-repository library: 3,292
findings, 8 colliding pairs, the sharpest being two separate committed
secrets four lines apart in one test fixture, sharing one identity. The
baseline keys on the id, so accepting one suppressed the other.

These tests hold both halves: the id still survives code motion, and two
distinct findings never share one.
"""
from __future__ import annotations


from ghost_buster.baseline import Baseline
from ghost_buster.mechanical import run_all
from ghost_buster.schema import (
    Category, Evidence, Finding, Layer, Severity, Status, disambiguate_ids,
)


def _finding(summary, file="src/mod.py", line=1, detail=""):
    return Finding(
        detector="long_function", category=Category.COMPLEXITY, layer=Layer.MECHANICAL,
        severity=Severity.MAJOR, status=Status.CONFIRMED, summary=summary, detail=detail,
        evidence=Evidence(file=file, line_start=line, line_end=line + 10),
    )


def _twin_methods(tmp_path):
    """Two classes, each with a 91-line method of the same name: one file,
    two genuinely distinct long functions, one summary between them."""
    body = "\n".join(f"        x{i} = {i}" for i in range(90))
    src = (f"class Alpha:\n    def run(self):\n{body}\n        return x0\n\n\n"
           f"class Beta:\n    def run(self):\n{body}\n        return x0\n")
    path = tmp_path / "two.py"
    path.write_text(src)
    return path


# ------------------------------------------------- the property being kept

def test_an_id_still_survives_the_finding_moving_down_its_file():
    """The reason the line number is not in the id. If this fails, every
    baseline in the library churns on the next unrelated edit."""
    early = _finding("'wide' spans 91 lines (threshold 80)", line=4)
    late = _finding("'wide' spans 91 lines (threshold 80)", line=204)
    assert early.id == late.id


def test_two_findings_that_are_the_same_finding_twice_keep_one_id():
    """Same place, same detail: one finding reported twice, which is a
    different defect from two findings sharing an identity. Splitting these
    would invent a second finding out of a duplicate emission."""
    twice = [_finding("'wide' spans 91 lines", line=4), _finding("'wide' spans 91 lines", line=4)]
    assert disambiguate_ids(twice) == 0
    assert twice[0].id == twice[1].id


# -------------------------------------------------- the property being added

def test_two_distinct_findings_in_one_file_get_distinct_ids(tmp_path):
    """The measured case, from a real detector run rather than hand-built
    Finding objects: two 91-line methods both named `run`."""
    longs = [f for f in run_all([_twin_methods(tmp_path)]) if f.detector == "long_function"]
    assert len(longs) == 2, "the fixture is meant to hold two long functions"
    assert longs[0].summary == longs[1].summary, "and to give them one summary"

    assert disambiguate_ids(longs) == 2, "both members of the pair are given their own id"
    assert longs[0].id != longs[1].id


def test_each_member_of_a_colliding_group_is_suffixed_from_its_own_place(tmp_path):
    """1.3.0 numbered them by position, so inserting one renumbered the
    rest. The suffix now comes from the finding's own line range and
    detail, which depend on nothing but itself."""
    longs = [f for f in run_all([_twin_methods(tmp_path)]) if f.detector == "long_function"]
    base = longs[0].id
    disambiguate_ids(longs)
    for f in longs:
        assert f.id.startswith(base + "-")
        assert len(f.id.rsplit("-", 1)[1]) == 6


def test_a_new_sibling_does_not_renumber_the_others():
    """The defect an external reviewer named in the 1.3.0 scheme: insert a
    fourth occurrence above the others and every id below it shifted."""
    a, b = _finding("'run' spans 91 lines", line=100), _finding("'run' spans 91 lines", line=300)
    disambiguate_ids([a, b])
    was = (a.id, b.id)

    a2 = _finding("'run' spans 91 lines", line=100)
    b2 = _finding("'run' spans 91 lines", line=300)
    inserted = _finding("'run' spans 91 lines", line=10)
    disambiguate_ids([a2, b2, inserted])

    assert (a2.id, b2.id) == was, "a finding's identity moved because a sibling appeared"
    assert inserted.id not in was


def test_removing_a_sibling_does_not_renumber_the_others():
    a, b, c = (_finding("'run' spans 91 lines", line=n) for n in (10, 100, 300))
    disambiguate_ids([a, b, c])
    was = (b.id, c.id)

    b2, c2 = (_finding("'run' spans 91 lines", line=n) for n in (100, 300))
    disambiguate_ids([b2, c2])
    assert (b2.id, c2.id) == was, "fixing one finding renamed the ones left behind"


def test_the_suffix_does_not_depend_on_the_order_they_were_scanned():
    a, b = _finding("'run' spans 91 lines", line=100), _finding("'run' spans 91 lines", line=300)
    disambiguate_ids([a, b])
    a2, b2 = _finding("'run' spans 91 lines", line=100), _finding("'run' spans 91 lines", line=300)
    disambiguate_ids([b2, a2])
    assert (a2.id, b2.id) == (a.id, b.id)


def test_accepting_one_of_two_no_longer_suppresses_the_other(tmp_path):
    """The defect, end to end. Before this, a human accepted one finding
    and the scan stopped reporting two."""
    longs = [f for f in run_all([_twin_methods(tmp_path)]) if f.detector == "long_function"]
    disambiguate_ids(longs)
    first, second = sorted(longs, key=lambda f: f.evidence.line_start)

    path = tmp_path / "baseline.json"
    Baseline(path).accept([first])
    new, known = Baseline(path).diff([first, second])

    assert [f.id for f in known] == [first.id], "the accepted one is suppressed"
    assert [f.id for f in new] == [second.id], "the one nobody read is still reported"


def test_a_distinct_detail_is_enough_to_split_a_shared_id():
    """The library's real case: two correlation findings at different lines
    of one file, same summary, different detail."""
    pair = [_finding("the 'generic-api-key' secret is also in 1 copy", line=829, detail="first"),
            _finding("the 'generic-api-key' secret is also in 1 copy", line=833, detail="second")]
    assert disambiguate_ids(pair) == 2
    assert len({f.id for f in pair}) == 2


def test_two_findings_at_one_line_are_split_by_their_detail_alone():
    """The correlation case reduced to its essence: same detector, same
    file, same summary, same line, different account of what was found."""
    pair = [_finding("the secret is also in 1 copy", line=829, detail="copy in twin_a.py"),
            _finding("the secret is also in 1 copy", line=829, detail="copy in twin_b.py")]
    assert disambiguate_ids(pair) == 2
    assert len({f.id for f in pair}) == 2


def test_three_in_one_file_all_separate():
    group = [_finding("'run' spans 91 lines", line=n) for n in (10, 200, 400)]
    assert disambiguate_ids(group) == 3
    assert len({f.id for f in group}) == 3


def test_findings_that_do_not_collide_are_left_alone():
    untouched = [_finding("'a' spans 91 lines"), _finding("'b' spans 91 lines"),
                 _finding("'a' spans 91 lines", file="src/other.py")]
    before = [f.id for f in untouched]
    assert disambiguate_ids(untouched) == 0
    assert [f.id for f in untouched] == before
