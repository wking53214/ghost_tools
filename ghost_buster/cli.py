"""cli.py -- `python -m ghost_buster <path>`.

v0.1 scope: wires up Layer 1 (mechanical) end to end, always. Layer 2
(semantic) is available as a library (see semantic.py) but is NOT wired
into this CLI by default yet -- it needs a real API key, costs real
money per run, and (per this whole project's own "discovery before fix,
no silent scope creep" discipline) a tool that costs money should never
run by default without the caller explicitly asking for it. --semantic
opts in.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

from .baseline import Baseline
from .branches import scan as scan_branches
from .testsuite import render_report as render_test_report, scan as scan_tests
from .mechanical import run_all
from .mutation import render_run, run_mutations
from .schema import Finding, FindingSet, Severity
from .secrets import render_report as render_secrets_report, scan as scan_secrets


# Directory names never descended into. `site-packages` is the load-bearing
# one: it catches an installed-package tree regardless of what the enclosing
# virtualenv is called (.venv / venv / env / <anything>), which is the noise
# source that actually swamps a blind run -- a repo with a venv in its
# working tree was reporting thousands of findings from pytest's own source.
# The rest are VCS internals and tool caches. Matched against any component
# of a path, so a nested occurrence is still excluded.
_EXCLUDED_DIRS = frozenset({
    "__pycache__",
    "site-packages",
    ".venv", "venv",
    "node_modules",
    ".git", ".hg", ".svn",
    ".tox", ".nox", ".eggs",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis",
    ".ipynb_checkpoints",
    # Build output. Measured on ghost_tools itself: a stray `build/` from a
    # wheel build made every module in the package byte-identical to a copy
    # of itself, 16 duplicate_file groups of pure noise.
    "build", "dist",
})


def _collect_files(root: Path, extra_excludes: Iterable[str] = ()) -> List[Path]:
    """.py for every code detector, plus .md so doc_test_count_drift (v0.3)
    has something to read -- every other detector calls _parse() on
    whatever it's handed, which fails closed (returns None, gets skipped)
    on non-Python text, so widening the *type* list is safe.

    Skips any path with a directory component in _EXCLUDED_DIRS (virtualenvs
    / vendored site-packages / VCS dirs / tool caches) or in `extra_excludes`
    -- the latter for a repo-specific vendored tree, e.g. a checked-in copy
    of a sibling repo -- and any dot-prefixed file. Exclusion is by directory
    NAME anywhere in the path, so pointing the scan directly at, say, a
    `venv/` would also come back empty; scan the project root.
    """
    excluded = _EXCLUDED_DIRS | set(extra_excludes)
    # Each real path once: a symlinked file is otherwise listed under both
    # names, and every function in it becomes its own near-duplicate.
    # Measured on OBSERVE, which keeps genuine symlinks.
    seen_real = set()
    out = []
    for p in sorted(list(root.rglob("*.py")) + list(root.rglob("*.md"))):
        if not excluded.isdisjoint(p.parts) or p.name.startswith("."):
            continue
        if any(part.endswith(".egg-info") for part in p.parts[:-1]):
            continue
        real = p.resolve()
        if real in seen_real:
            continue
        seen_real.add(real)
        out.append(p)
    return out


def _print_report(new: List[Finding], known: List[Finding]) -> None:
    order = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2, Severity.INFORMATIONAL: 3}
    new_sorted = sorted(new, key=lambda f: order[f.severity])

    print(f"\nghost_buster: {len(new_sorted)} new finding(s), {len(known)} already in baseline\n")
    for f in new_sorted:
        loc = f.evidence.file
        if f.evidence.line_start:
            loc += f":{f.evidence.line_start}"
        print(f"  [{f.severity.value.upper():13s}] {f.detector:25s} {loc}")
        print(f"      {f.summary}")
        if f.detail:
            print(f"      {f.detail}")
        print(f"      id: {f.id}")
        print()

    if not new_sorted:
        print("  (nothing new)\n")


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="ghost_buster")
    parser.add_argument("path", type=Path, help="directory to scan")
    parser.add_argument(
        "--baseline", type=Path, default=None,
        help="baseline file for delta reporting (default: <path>/.ghost_baseline.json)",
    )
    parser.add_argument(
        "--accept", action="store_true",
        help="accept all current findings into the baseline (suppress them going forward)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit the full finding set as JSON instead of the human report",
    )
    parser.add_argument(
        "--exclude", action="append", default=[], metavar="DIRNAME",
        help="an extra directory name to skip (repeatable) -- for a "
             "repo-specific vendored tree, e.g. a checked-in copy of "
             "another repo. Virtualenvs, site-packages, VCS dirs and tool "
             "caches are always skipped.",
    )
    parser.add_argument(
        "--mutate", action="store_true",
        help="prove vacuous checks by mutation: find tests shaped like they check "
             "nothing, break the code they call in a scratch copy, and report only "
             "the tests that still pass. Runs one pytest process per mutant; the "
             "working tree is never modified.",
    )
    parser.add_argument("--mutate-max", type=int, default=6, metavar="N",
                        help="mutants to try per candidate test (default 6)")
    parser.add_argument("--mutate-timeout", type=float, default=120.0, metavar="SECONDS",
                        help="per-test timeout for each mutant run (default 120)")
    parser.add_argument("--mutate-only", default=None, metavar="SUBSTRING",
                        help="restrict mutation to test files whose path contains this")
    parser.add_argument("--mutate-verbose", action="store_true",
                        help="also list killed mutants and candidates that could not be judged")
    parser.add_argument(
        "--branches", action="store_true",
        help="flag local/remote-tracking branches with commits not reflected in the "
             "base branch (fast-forward, ordinary merge, or squash all recognized). "
             "Read-only git plumbing against the checkout as it sits: never fetches, "
             "never pushes, never queries GitHub, so it cannot see a branch's "
             "pull-request state, and a remote-tracking ref already deleted upstream "
             "still reads as unmerged until this checkout re-fetches with --prune.",
    )
    parser.add_argument(
        "--branches-base", default=None, metavar="REF",
        help="base branch to compare against (default: first of origin/main, "
             "origin/master, main, master that resolves)",
    )
    parser.add_argument(
        "--tests", action="store_true",
        help="run the project's pytest suite and report every test that did not pass: "
             "failing (MAJOR), flaky (fails in the suite, passes rerun alone; MAJOR), "
             "blocked by a missing service/module/variable (MINOR, says what), skipped "
             "without a reason naming a dependency (MAJOR), skipped for a dependency "
             "that is actually present (MAJOR), skipped for an absent one "
             "(INFORMATIONAL). Executes the project's tests; never installs or starts "
             "anything.",
    )
    parser.add_argument("--tests-reruns", type=int, default=3, metavar="N",
                        help="isolated reruns per failing test before it is called failing "
                             "rather than flaky (default 3)")
    parser.add_argument("--tests-python", default=None, metavar="PATH",
                        help="interpreter to run the suite with (default: this one); point it "
                             "at the project's own virtualenv to run with its dependencies")
    parser.add_argument("--tests-timeout", type=float, default=900.0, metavar="SECONDS",
                        help="timeout for each pytest invocation, the full run included (default 900)")
    parser.add_argument(
        "--secrets", action="store_true",
        help="scan the checked-out branch's git history for committed secrets with "
             "gitleaks (must be installed separately; never installed by this tool). "
             "Read-only: never rewrites history, rotates a credential, or writes into "
             "the target repository. The secret value itself never appears in a finding.",
    )
    parser.add_argument("--secrets-binary", default=None, metavar="PATH",
                        help="path to the gitleaks executable (default: gitleaks on PATH)")
    parser.add_argument("--secrets-timeout", type=float, default=300.0, metavar="SECONDS",
                        help="timeout for the gitleaks run (default 300)")
    args = parser.parse_args(argv)

    if not args.path.is_dir():
        print(f"error: {args.path} is not a directory", file=sys.stderr)
        return 2

    baseline_path = args.baseline or (args.path / ".ghost_baseline.json")
    files = _collect_files(args.path, args.exclude)
    if not files:
        # A scan of nothing is not a clean scan. A checkout under a directory
        # named venv, node_modules or .tox, an empty directory, or a wrong
        # path all used to print "0 new finding(s)" and exit 0 (measured
        # 2026-09-08).
        print(f"error: no .py or .md files to scan under {args.path} "
              f"(excluded directory names: {', '.join(sorted(_EXCLUDED_DIRS | set(args.exclude)))})",
              file=sys.stderr)
        return 2
    print(f"ghost_buster: scanning {len(files)} file(s) under {args.path}", file=sys.stderr)
    findings = run_all(files)
    mutation_run = None
    if args.mutate:
        mutation_run = run_mutations(
            args.path, files, max_mutants_per_candidate=args.mutate_max,
            timeout=args.mutate_timeout, only=args.mutate_only,
        )
        findings.extend(mutation_run.findings)

    if args.branches:
        branch_findings, branch_report = scan_branches(args.path, args.branches_base)
        if branch_report.ran:
            print(
                f"ghost_buster: branch scan compared {branch_report.branches_scanned} "
                f"branch(es) against '{branch_report.base_branch}'", file=sys.stderr,
            )
        else:
            print(f"ghost_buster: branch scan did not run: {branch_report.reason}", file=sys.stderr)
        findings.extend(branch_findings)

    if args.tests:
        test_findings, test_report = scan_tests(
            args.path, python=args.tests_python, reruns=args.tests_reruns,
            timeout=args.tests_timeout,
        )
        print(render_test_report(test_report), file=sys.stderr)
        findings.extend(test_findings)

    if args.secrets:
        secrets_findings, secrets_report = scan_secrets(
            args.path, gitleaks_path=args.secrets_binary, timeout=args.secrets_timeout,
        )
        print(render_secrets_report(secrets_report), file=sys.stderr)
        findings.extend(secrets_findings)

    try:
        baseline = Baseline(baseline_path)
    except (ValueError, OSError) as e:
        # A corrupt or unreadable baseline used to escape as a traceback with
        # exit 1, the same status as "MAJOR finding". It is a usage error.
        print(f"error: baseline {baseline_path} could not be read: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if args.accept:
        baseline.accept(findings)
        print(f"accepted {len(findings)} finding(s) into {baseline_path}", file=sys.stderr)
        if args.json:
            print(FindingSet(findings).to_json())
        return 0

    new, known = baseline.diff(findings)
    stale = baseline.stale(findings)
    if stale:
        print(f"ghost_buster: {len(stale)} of {baseline.size} baseline entries matched nothing scanned "
              f"(fixed, renamed detector, or a baseline written from another checkout); "
              f"first: {stale[0].id} {stale[0].evidence.file}", file=sys.stderr)

    if args.json:
        print(FindingSet(new).to_json())
    else:
        _print_report(new, known)
        if mutation_run is not None:
            print(render_run(mutation_run, verbose=args.mutate_verbose))

    return 1 if any(f.severity in (Severity.CRITICAL, Severity.MAJOR) for f in new) else 0


if __name__ == "__main__":
    sys.exit(main())
