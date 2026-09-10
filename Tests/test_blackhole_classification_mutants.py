"""The proof that Tests/test_blackhole_classification.py is not vacuous.

Each mutant restores a version that was live on 2026-09-10, when a scan of a
37-repository library returned 248 voids and roughly half of them described
nothing missing. The report still looked authoritative -- correct format,
real file paths, honest UNDETERMINABLE sections -- which is exactly why the
tests have to be able to fail.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_blackhole_classification.py"
_D = "blackhole_extrapolator/detect.py"
_C = "blackhole_extrapolator/corpus.py"
_L = "blackhole_extrapolator/cli.py"

MUTANTS = [
    # B -- the original defect: "is it real" answered by "is it installed here".
    ("resolution answers only for what is installed on this machine", _D,
     '''    if name in _STDLIB:
        return "the standard library"''',
     '''    if False:
        return "the standard library"'''),
    ("a stdlib name used unimported goes back to being an absence to rebuild", _D,
     '''        where = resolution(name)
        if where:''',
     '''        where = resolution(name)
        if False:'''),
    ("an unaccounted import is outlined as a void again", _D,
     "            kind=EvidenceKind.UNRESOLVED_IMPORT, detail=detail,",
     "            kind=EvidenceKind.MISSING_MODULE, detail=detail,"),
    ("a group of only non-seeding marks becomes a void again", _L,
     "        if all(i.kind in NON_SEEDING_KINDS for i in items):\n            continue",
     "        if False:\n            continue"),
    # The call site appears twice, so mutating one left the other printing.
    # Break the reporting itself, which covers both paths at once.
    ("demoting an import also stops reporting it", _L,
     "    if unresolved:\n        by_module = {}",
     "    if False:\n        by_module = {}"),

    # A -- the archive classifier, including the bug my own first version had.
    # Restores the ACTUAL first version: an early return on the manifest,
    # before any share is computed. The first attempt at this mutant only
    # widened the guard, which left the two-thirds threshold in place and
    # so changed no outcome -- a mutant that breaks nothing proves nothing.
    ("a provenance manifest alone classifies a source tree as an archive", _C,
     "    if total and archived:",
     "    if present:\n"
     "        return RootClassification(RootKind.CODE_ARCHIVE, 'declares itself a record',\n"
     "                                  len(archived), total)\n"
     "    if total and archived:"),
    ("any archived file at all makes a tree an archive", _C,
     "ARCHIVE_SHARE = 2 / 3",
     "ARCHIVE_SHARE = 0.0"),
    ("an archive is scanned as a codebase again", _L,
     "    if classification.is_archive:\n        return _report_archive(classification, voids, evidence, args)",
     "    if False:\n        return _report_archive(classification, voids, evidence, args)"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_classification_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_classification_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _C, "ARCHIVE_SHARE = 2 / 3", "ARCHIVE_SHARE = 2 / 3")
    assert result.returncode == 0, result.stdout[-2000:]
