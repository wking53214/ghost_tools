"""A finding that only moved is the same finding.

Five detectors put a line number or a line count in their summary, so adding a line above a
finding, or a line inside a long function, gave it a new id. A baseline then read the old entry
as fixed and the finding as new. Measured between two real releases of the same repository:
about half of the findings that looked fixed had reappeared in the same file with a new id.

Each case below scans real code, moves it, scans again, and compares ids.
"""
from __future__ import annotations

import textwrap

from ghost_buster import mechanical

LONG = "\n".join(f"    x{i} = {i}" for i in range(12))


def _write(tmp_path, body, name="m.py"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _ids(findings):
    return sorted(f.id for f in findings)


def test_a_long_function_keeps_its_id_when_it_grows_or_moves(tmp_path):
    base = f"def run():\n{LONG}\n"
    one = mechanical.detect_long_functions([_write(tmp_path, base)], threshold=5)
    grown = mechanical.detect_long_functions(
        [_write(tmp_path, "import os\n\n" + base + "    y = 1\n")], threshold=5)
    assert len(one) == len(grown) == 1
    assert one[0].summary != grown[0].summary
    assert one[0].id == grown[0].id


def test_two_long_functions_with_different_names_stay_two_findings(tmp_path):
    body = f"def a():\n{LONG}\n\ndef b():\n{LONG}\n"
    found = mechanical.detect_long_functions([_write(tmp_path, body)], threshold=5)
    assert len(found) == 2 and len(set(_ids(found))) == 2


def test_the_old_summary_id_is_still_matched(tmp_path):
    from ghost_buster.schema import _stable_id
    found = mechanical.detect_long_functions([_write(tmp_path, f"def run():\n{LONG}\n")], threshold=5)[0]
    old = _stable_id("long_function", found.evidence.file, found.summary)
    assert old in found.previous_ids


DUP = """\
def one(a):
    t = a + 1
    u = t * 2
    v = u - 3
    w = v / 4
    z = w + t
    q = z * u
    r = q - v
    s = r / w
    m = s * q
    n = m + z
    return n + 1

def two(b):
    t = b + 1
    u = t * 2
    v = u - 3
    w = v / 4
    z = w + t
    q = z * u
    r = q - v
    s = r / w
    m = s * q
    n = m + z
    return n + 1
"""


def test_near_duplicate_functions_keep_their_id_when_moved(tmp_path):
    here = mechanical.detect_near_duplicate_functions([_write(tmp_path, DUP)])
    moved = mechanical.detect_near_duplicate_functions([_write(tmp_path, "import os\nimport sys\n\n" + DUP)])
    assert len(here) == len(moved) == 1
    assert here[0].summary != moved[0].summary
    assert here[0].id == moved[0].id


def test_a_different_pair_of_names_is_a_different_finding(tmp_path):
    other = DUP.replace("def one", "def uno").replace("def two", "def dos")
    a = mechanical.detect_near_duplicate_functions([_write(tmp_path, DUP)])
    b = mechanical.detect_near_duplicate_functions([_write(tmp_path, other)])
    assert a[0].id != b[0].id


INTRA = """\
def build(kind):
    if kind == 1:
        a = make(1)
        a.tag = 1
        a.ok = True
        a.save()
    elif kind == 2:
        a = make(2)
        a.tag = 2
        a.ok = True
        a.save()
    elif kind == 3:
        a = make(3)
        a.tag = 3
        a.ok = True
        a.save()
    return a
"""


def test_a_repeated_block_keeps_its_id_when_the_function_moves(tmp_path):
    here = mechanical.detect_intra_function_duplicate_blocks([_write(tmp_path, INTRA)])
    moved = mechanical.detect_intra_function_duplicate_blocks([_write(tmp_path, "import os\n\n\n" + INTRA)])
    assert here and len(here) == len(moved)
    assert here[0].summary != moved[0].summary
    assert _ids(here) == _ids(moved)
