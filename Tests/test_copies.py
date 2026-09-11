"""The same file in several places, no longer saying the same thing.

`duplicate_file` goes quiet at exactly the moment this starts mattering: it
groups by content hash, so the group disappears the instant somebody fixes
one copy and not the others. These tests are about the window that opens
then.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from ghost_buster.copies import (
    DETECTOR,
    MINIMUM_DEFINITIONS,
    detect_drifted_copies,
    find_copies,
)
from ghost_buster.schema import Category, Layer, Severity, Status

ORIGINAL = textwrap.dedent('''\
    import time


    class Gate:
        def __init__(self, limit):
            self.limit = limit

        def allows(self, reading):
            return reading < self.limit


    def stamp(value):
        return (time.time(), value)


    def audit(entries):
        return len(entries)
''')
# Dedented HERE, at definition. Concatenating an unindented string onto an
# indented literal destroys the common prefix, so a later textwrap.dedent
# silently does nothing and the fixture file does not parse -- which made
# two of these tests fail and a third pass against nothing at all.


def _tree(tmp_path: Path, files: dict) -> list:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return sorted(tmp_path.rglob("*.py"))


# ------------------------------------------- the window duplicate_file misses

def test_byte_identical_copies_are_left_to_duplicate_file(tmp_path):
    """Two detectors reporting one fact is how a report doubles its noise."""
    files = _tree(tmp_path, {"a/m.py": ORIGINAL, "b/m.py": ORIGINAL})
    assert find_copies(files) == []


def test_a_copy_that_drifted_is_reported(tmp_path):
    files = _tree(tmp_path, {
        "a/m.py": ORIGINAL,
        "b/m.py": ORIGINAL.replace("return reading < self.limit",
                                   "return reading <= self.limit"),
    })
    findings = detect_drifted_copies(files)
    assert len(findings) == 1
    f = findings[0]
    assert f.detector == DETECTOR
    assert f.layer is Layer.MECHANICAL
    assert f.status is Status.CONFIRMED
    assert f.severity is Severity.MAJOR
    assert f.category is Category.PARALLEL_IMPLEMENTATION
    assert "`Gate`" in f.detail
    assert {Path(p).parent.name for p in f.evidence.related_files} == {"a", "b"}


def test_the_finding_names_which_definitions_stopped_matching(tmp_path):
    files = _tree(tmp_path, {
        "a/m.py": ORIGINAL,
        "b/m.py": ORIGINAL.replace("return len(entries)", "return len(entries) - 1"),
    })
    group = find_copies(files)[0]
    assert group.differing == ("audit",)
    assert set(group.agreed) == {"Gate", "stamp"}


def test_a_difference_of_formatting_alone_is_only_MINOR(tmp_path):
    """Comments, blank lines and line numbers are excluded from the
    comparison, so what is left is a tidiness problem rather than a
    behavioural one."""
    files = _tree(tmp_path, {
        "a/m.py": ORIGINAL,
        "b/m.py": "# a note the other copy does not have\n" + ORIGINAL + "\n\n",
    })
    f = detect_drifted_copies(files)[0]
    assert f.severity is Severity.MINOR
    assert f.category is Category.DUPLICATION
    assert find_copies(files)[0].differing == ()


def test_reformatting_is_not_drift(tmp_path):
    """include_attributes=False is what makes this true. With attributes in
    the hash every copy differs, because line numbers always do."""
    reformatted = ORIGINAL.replace(
        "def stamp(value):\n    return (time.time(), value)",
        "def stamp(\n    value,\n):\n    return (\n        time.time(),\n        value,\n    )")
    # Without this the fixture can silently stop reformatting anything and the
    # test passes against two identical files, which is how it failed first.
    assert reformatted != ORIGINAL
    files = _tree(tmp_path, {"a/m.py": ORIGINAL, "b/m.py": reformatted})
    assert find_copies(files)[0].differing == ()


# --------------------------------------------------------- what is a group

def test_three_copies_form_one_group(tmp_path):
    files = _tree(tmp_path, {
        "a/m.py": ORIGINAL,
        "b/m.py": ORIGINAL.replace("self.limit = limit", "self.limit = int(limit)"),
        "c/m.py": ORIGINAL + "\n# third\n",
    })
    groups = find_copies(files)
    assert len(groups) == 1
    assert len(groups[0].paths) == 3


def test_a_shared_name_set_must_be_complete(tmp_path):
    """Overlap is a coincidence; equality is a copy. `b` has an extra
    definition, so it is not the same file."""
    files = _tree(tmp_path, {
        "a/m.py": ORIGINAL,
        "b/m.py": ORIGINAL + "\n\ndef extra():\n    return 1\n",
    })
    assert find_copies(files) == []


def test_too_few_definitions_to_be_a_copy(tmp_path):
    """Two scripts sharing `main` and `run` are not copies of each other."""
    small = "def main():\n    return 1\n\n\ndef run():\n    return 2\n"
    files = _tree(tmp_path, {"a/m.py": small, "b/m.py": small + "# note\n"})
    assert MINIMUM_DEFINITIONS == 3
    assert find_copies(files) == []


def test_a_file_that_does_not_parse_is_skipped(tmp_path):
    files = _tree(tmp_path, {"a/m.py": ORIGINAL, "b/m.py": "def broken(:\n"})
    assert find_copies(files) == []


def test_a_lone_file_is_not_a_group(tmp_path):
    assert find_copies(_tree(tmp_path, {"a/m.py": ORIGINAL})) == []
