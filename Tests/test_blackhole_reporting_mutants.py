"""The proof that Tests/test_blackhole_reporting.py is not vacuous.

Each mutant restores a version of the report that was live before
2026-09-10: one that rendered a quarter of its volume as outlines with
nothing in them, said the same sentence about a manifest whether or not one
existed, and warned about exactly one of the several ways its own scope
could manufacture an absence.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_blackhole_reporting.py"
_D = "blackhole_extrapolator/detect.py"
_L = "blackhole_extrapolator/cli.py"

MUTANTS = [
    # C -- shapeless voids
    ("every void is rendered again, shape or no shape", _L,
     "    for void in (voids if args.all else shaped):",
     "    for void in voids:"),
    ("the collapsed ones stop being named at all", _L,
     "    if shapeless and not args.all:",
     "    if False:"),
    ("--all stops rendering the shapeless ones", _L,
     "    for void in (voids if args.all else shaped):",
     "    for void in shaped:"),
    # The split itself: if inferred_anything is ignored, every void looks
    # shaped and nothing is ever collapsed.
    ("shape is no longer what decides", _L,
     "    shaped = [v for v in voids if v.inferred_anything]\n"
     "    shapeless = [v for v in voids if not v.inferred_anything]",
     "    shaped = list(voids)\n"
     "    shapeless = []"),

    # D -- what a manifest implies
    ("a project without a manifest is accused of omitting things", _L,
     "        declares = bool(_declared_dependencies(root))",
     "        declares = True"),
    ("a project with a manifest is excused", _L,
     "        declares = bool(_declared_dependencies(root))",
     "        declares = False"),

    # E -- reasons an absence may be false
    ("a scan with no siblings no longer says so", _D,
     "    if not siblings:\n        hints.append(",
     "    if False:\n        hints.append("),
    ("an uninitialised submodule stops being a scan-level hint", _D,
     "        if not initialised:\n            hints.append(",
     "        if False:\n            hints.append("),
    ("gitignored python stops being a hint", _D,
     "        if ignored:\n            hints.append(",
     "        if False:\n            hints.append("),
    ("the hints are computed and never printed", _L,
     "    hints = false_absence_hints(root, siblings)\n    if not hints:\n        return",
     "    hints = false_absence_hints(root, siblings)\n    if True:\n        return"),
    # The hints must stay conditional: printed unconditionally they become
    # boilerplate, which is how a real warning gets skipped.
    ("the hint block prints even when there is nothing to warn about", _D,
     "    if not siblings:\n        hints.append(\n            \"no sibling checkout was supplied.",
     "    if True:\n        hints.append(\n            \"no sibling checkout was supplied."),

    # G -- specimen corpora and retired repositories
    ("a specimen corpus is scanned as a system again", "blackhole_extrapolator/corpus.py",
     "        if any(phrase in lowered for phrase in _SPECIMEN_PHRASES):",
     "        if False:"),
    ("a retired repository is scanned as a system again", "blackhole_extrapolator/corpus.py",
     "        if any(phrase in lowered for phrase in _RETIRED_PHRASES):",
     "        if False:"),
    ("the forwarding address stops being extracted", "blackhole_extrapolator/corpus.py",
     "            match = _FORWARDING.search(head)",
     "            match = None"),
    ("fixture directories stop classifying without a README", "blackhole_extrapolator/corpus.py",
     "    if total and _specimen_share(sources, root) >= ARCHIVE_SHARE:",
     "    if False:"),
    # The overlap bug: a disclaimer both kinds use cannot separate them.
    ("\"not a system\" is treated as a specimen declaration again", "blackhole_extrapolator/corpus.py",
     '    "specimen corpus", "specimen library", "test corpus", "fixture corpus",',
     '    "specimen corpus", "not a system", "specimen library", "test corpus",'),
    # The README window: unbounded, a passing mention becomes a declaration.
    ("the README declaration window is unbounded", "blackhole_extrapolator/corpus.py",
     "README_LINES = 12",
     "README_LINES = 10_000"),
    # Every kind must keep its own headline; collapsing them tells someone
    # their fixtures were preserved payloads.
    ("every non-source kind is described as an archive again", _L,
     "    print(f\"{headline}: {classification.reason}.\")",
     "    print(f\"This is an archive of code, not a source tree: {classification.reason}.\")"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_reporting_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_reporting_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(
        TESTS, _L, "    for void in (voids if args.all else shaped):",
        "    for void in (voids if args.all else shaped):")
    assert result.returncode == 0, result.stdout[-2000:]
