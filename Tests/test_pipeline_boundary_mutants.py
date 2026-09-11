"""The proof that the seam test is not vacuous.

Both of the first two mutants below reproduce a defect the extraction
actually had, caught by diffing the old binary against the new one on the
same tree rather than by the suite. The test file exists so the next such
slip is caught by the suite instead.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

_PIPE = "ghost_buster/pipeline.py"
_CLI = "ghost_buster/cli.py"

SEAM = "Tests/test_pipeline_boundary.py"

MUTANTS = [
    # (label, file, exact text to replace, replacement)
    ("a skip receipt goes to stdout instead of the receipt channel", _PIPE,
     '    say(f"ghost_buster: {name} SKIPPED at your request ({flag})")',
     '    print(f"ghost_buster: {name} SKIPPED at your request ({flag})")'),
    ("profile_seconds is bound only under --profile", _PIPE,
     "    profile_seconds = 0.0\n    if args.profile:",
     "    if args.profile:"),
    ("the scanning receipt is dropped", _PIPE,
     '    say(f"ghost_buster: scanning {len(files)} file(s) under {args.path}")',
     "    pass"),
    ("gather stops reporting which files it read", _PIPE,
     "    return Evidence(files=files,",
     "    return Evidence(files=[],"),
    ("a stage stops being a stage and is inlined away", _PIPE,
     "    _correlate(args, findings, checks, test_report, say)",
     "    pass"),
    ("the ledger stage loses its receipt channel", _PIPE,
     "def _record_in_ledger(args, files, findings, checks, baseline_path, say) -> None:",
     "def _record_in_ledger(args, files, findings, checks, baseline_path) -> None:"),
    ("main takes the presentation back", _CLI,
     "        _present(args, evidence, new, known, priors, archive, casefile_path)",
     "        _print_report(new, known, priors)\n"
     "        print()\n"
     "        if evidence.profile is not None:\n"
     "            print(evidence.profile.render(evidence.profile_seconds))\n"
     "        if evidence.mutation_run is not None:\n"
     "            print(render_run(evidence.mutation_run, verbose=args.mutate_verbose))\n"
     "        retired = set()\n"
     "        print(readiness.assess(evidence.findings, evidence.checks, retired).render())\n"
     "        print(archive)\n"
     "        print(casefile_path)"),
    ("the walk is copied back into the CLI", _CLI,
     "from .pipeline import Stop, gather",
     "from .pipeline import Stop, gather, _collect_files, _run_repository_checks\n"
     "def _collect_files(root, extra_excludes=()):  # a second copy\n"
     "    return []\n"
     "def _run_repository_checks(args, findings, checks, say):\n"
     "    return None"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_is_killed(label, rel, old, new):
    assert_killed(label, SEAM, run_tests_with_mutation(SEAM, rel, old, new))


def test_the_suite_passes_unmutated():
    anchor = "def gather("
    result = run_tests_with_mutation(SEAM, _PIPE, anchor, anchor)
    assert result.returncode == 0, result.stdout[-1500:]
