"""cli.py -- the `ghost-buster <path>` console script (`ghost_buster.cli:main`).

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
from typing import Iterable, List, Optional, Dict

from . import __version__, version_string
from .baseline import Baseline
from .boundary import (
    build_joined_model, derive_findings as derive_boundary_findings,
    render_report as render_boundary_report, render_single_repo_notice,
)
from .trust import check as trust_check, grant as trust_grant, declined_receipt
from .kernel import check_kernel, render_report as render_kernel_report
from .ledger import (
    COULD_NOT_RUN, DECLINED, Ledger, LedgerError, NOT_RUN, RAN,
    _head_commit, render_report as render_ledger_report,
)
from .trajectory import (
    derive as trajectory_derive, render_report as render_trajectory_report,
)
from .branches import scan as scan_branches
from .correlate import (
    load_prior_run,
    render_report as render_correlation_report,
    run_connectors,
)
from .testsuite import render_report as render_test_report, scan as scan_tests
from . import readiness
from .speed import Profile
from .casefile import Casefile, Prior
from .operate import Refused, operate
from .annotate import annotate
from .mechanical import run_all
from .project import render_report as render_project_report, scan as scan_project
from .structure import (
    build_model, derive_findings as derive_structure_findings,
    render_model, render_report as render_structure_report,
)
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


def _print_report(new: List[Finding], known: List[Finding],
                  priors: Optional[Dict[str, Prior]] = None) -> None:
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
        # The case file's history, beside the finding and never instead of
        # it. "3 false" is a reason to look harder at the fourth, not a
        # reason to not show it.
        if priors and f.id in priors and priors[f.id].seen:
            print(f"      {priors[f.id].render()}")
        print(f"      id: {f.id}")
        print()

    if not new_sorted:
        print("  (nothing new)\n")


def _build_parser() -> argparse.ArgumentParser:
    """Every flag in one place. Extracted from main() because ghost_buster's
    own `long_function` detector flagged main() at 194 lines against its
    threshold of 80 -- the argument table is the bulk of it and has no
    control flow, so lifting it out is the whole fix.
    """
    parser = argparse.ArgumentParser(prog="ghost_buster")
    # Consumed and exited on during parsing, so it works without the
    # required `path` positional -- which is the only way anyone would
    # ever type it.
    parser.add_argument(
        "--version", action="version", version=version_string(),
        help="print the version and exit",
    )
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
        "--operate", action="store_true",
        help="OPT-IN. The surgeon operates: on a CLEAN tree, open a branch, apply "
             "every remedy that carries a verification that can fail, re-examine "
             "after each cut, commit each cut, record the outcomes in the case "
             "file, and assess whether the patient is a candidate for enhancement. "
             "The branch the patient came in on is never written to; that is "
             "checked. Refuses on a dirty tree. See operate.py.",
    )
    parser.add_argument(
        "--operate-branch", default=None, metavar="NAME",
        help="the branch to operate on (default: ghost/operate-<timestamp>)",
    )
    parser.add_argument(
        "--operate-dry-run", action="store_true",
        help="with --operate: diagnose and assess candidacy, write nothing",
    )
    parser.add_argument(
        "--profile", action="store_true",
        help="instrument the scan and report work done more than once with the "
             "same input -- parses, reads, subprocesses -- ranked by what it "
             "cost. The static pitstop detectors run by default; this is the "
             "measured complement, and it is how the 9.5-parses-per-file "
             "redundancy in this toolkit was found. Adds a few percent to the run.",
    )
    parser.add_argument(
        "--casefile", type=Path, default=None, metavar="PATH",
        help="the surgeon's case file: history from ghost-triage decisions and "
             "past operations, shown beside each finding it applies to. Never "
             "hides a finding. Point every repository at one file and the tool "
             "learns across the library. (default: <path>/.ghost_casefile.json "
             "if it exists)",
    )
    parser.add_argument(
        "--annotate-names", action="store_true",
        help="OPT-IN, and the only thing ghost_buster does that writes to the "
             "scanned tree. Records every 1:1 name disagreement in the two "
             "places somebody looks: a regenerated table in the README, and a "
             "trailing comment on each signature and each call site. Comments "
             "only -- every edit is parsed before and after and discarded "
             "unless the syntax tree is identical, so it cannot change what a "
             "program means. Idempotent: the notes are stripped and rewritten "
             "whole on each run, so they follow a rename instead of piling up "
             "behind one, and a run that finds nothing new produces no diff.",
    )
    parser.add_argument(
        "--annotate-readme", type=Path, default=None, metavar="PATH",
        help="README to write the name-disagreement table into "
             "(default: <path>/README.md)",
    )
    parser.add_argument(
        "--mutate", action="store_true",
        help="OPT-IN, on cost -- one pytest process per mutant, so a large "
             "suite can run for hours; every other check is on by default. "
             "Proves vacuous checks by mutation: find tests shaped like they check "
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
        "--branches", action=argparse.BooleanOptionalAction, default=True,
        help="ON BY DEFAULT (--no-branches to skip). Flag local/remote-tracking branches with commits not reflected in the "
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
        "--trust", action="store_true",
        help="record consent for this repository's code to run here (its test suite, and "
             "its mutants under --mutate), in a store that belongs to you: "
             "$GHOST_TOOLS_TRUST or ~/.config/ghost_tools/trust.json. Without a record the "
             "test and mutation scans are DECLINED with a receipt; nothing else changes.")
    parser.add_argument(
        "--tests", action=argparse.BooleanOptionalAction, default=True,
        help="ON BY DEFAULT (--no-tests to skip). Runs the project's pytest suite and report every test that did not pass: "
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
        "--secrets", action=argparse.BooleanOptionalAction, default=True,
        help="ON BY DEFAULT (--no-secrets to skip). Scans the checked-out branch's git history for committed secrets with "
             "gitleaks (must be installed separately; never installed by this tool). "
             "Read-only: never rewrites history, rotates a credential, or writes into "
             "the target repository. The secret value itself never appears in a finding.",
    )
    parser.add_argument("--secrets-binary", default=None, metavar="PATH",
                        help="path to the gitleaks executable (default: gitleaks on PATH)")
    parser.add_argument("--secrets-timeout", type=float, default=300.0, metavar="SECONDS",
                        help="timeout for the gitleaks run (default 300)")
    parser.add_argument(
        "--correlate-with", action="append", default=[], metavar="[LABEL=]FILE",
        help="another repository's --json output, optionally named "
             "(`sentinel_os=/path/to/findings.json`); repeatable. Lets the "
             "cross-repository connectors fire: the same leaked credential "
             "present in a vendored or forked copy is one credential, not two "
             "unrelated findings. Correlation over this run's own findings "
             "always runs and needs no flag.",
    )
    parser.add_argument(
        "--project", action=argparse.BooleanOptionalAction, default=True,
        help="ON BY DEFAULT (--no-project to skip). Repository-shaped facts no "
             "single file can show: a deploy artifact with no CI configuration in "
             "front of it (MAJOR), and test files that no CI configuration runs "
             "(MINOR). Pure filesystem inspection, instant, reads no file content. "
             "Says nothing about a repository that has CI, and nothing about one "
             "with neither tests nor a deploy artifact.",
    )
    parser.add_argument(
        "--kernel", type=Path, action="append", default=[], metavar="PATH",
        help="a shared kernel (repeatable): a package whose classes this repository should import "
             "rather than carry. A class here that is structurally identical to a kernel class is "
             "kernel_shadow; one that shares its name and most of its methods but differs is "
             "drifted_contract. Opt-in because it needs a path.")
    parser.add_argument(
        "--join", type=Path, action="append", default=[], metavar="PATH",
        help="another repository to join to this one, repeatable. A cross-repo "
             "boundary is the one place both sides are blind: the importing "
             "repository guards the import and skips its tests when the other is "
             "absent, and the providing repository has never heard of the "
             "importer. Given two or more, this resolves each cross-repo import "
             "against what the other side actually exports, and reports symbols "
             "that cross a boundary with no test anywhere exercising them.",
    )
    parser.add_argument(
        "--single-repo", action="store_true",
        help="skip the joined-repository question and scan this repository alone",
    )
    parser.add_argument(
        "--structure", action=argparse.BooleanOptionalAction, default=True,
        help="ON BY DEFAULT (--no-structure to skip). Build a structural model "
             "from evidence only: packaging boundary, importable modules, "
             "execution entry points, import topology, which external boundaries "
             "each module actually crosses, module-level mutable state, declared "
             "public surface, data representations, and an explicit list of what "
             "could NOT be resolved statically. Reports contradictions between "
             "two observed facts (a console script pointing at a symbol that does "
             "not exist; a package imported and never declared). Says nothing "
             "about architectural responsibility, layering or quality -- those "
             "are interpretations, and the only mechanical route to them is the "
             "directory name.",
    )
    parser.add_argument(
        "--structure-out", type=Path, default=None, metavar="FILE",
        help="also write the full structural model to FILE as JSON",
    )
    parser.add_argument(
        "--structure-report", action="store_true",
        help="also print the full structural model in readable form",
    )
    parser.add_argument(
        "--ledger", action=argparse.BooleanOptionalAction, default=True,
        help="ON BY DEFAULT (--no-ledger to skip). Remember this run in "
             "<path>/.ghost_ledger.json and report what only history can say: a "
             "finding that was fixed and came back, one open for many runs with no "
             "decision recorded, one that keeps appearing and vanishing, and a check "
             "that has not actually run here in several runs. Strictly additive -- "
             "the ledger never suppresses a finding and never tunes a threshold.",
    )
    parser.add_argument(
        "--ledger-path", type=Path, default=None, metavar="FILE",
        help="where the ledger lives (default: <path>/.ghost_ledger.json)",
    )
    parser.add_argument(
        "--no-correlate", action="store_true",
        help="skip the correlation pass entirely (it reads findings already "
             "computed, runs no new scan, and is normally free)",
    )
    return parser


def _resolve_join_mode(args, files) -> List[Path]:
    """Joined or single, and never by silently assuming.

    --join says so outright. --single-repo says so outright. With neither,
    ASK -- but only when stdin is a terminal. A prompt in CI hangs the
    build forever, and a tool that hangs a build gets removed from the
    build, so a non-interactive run scans one repository and says on the
    receipt line that it did. Nobody should mistake a single-repo scan for
    a joined one.
    """
    if args.join:
        return list(args.join)
    if args.single_repo or not sys.stdin.isatty():
        return []
    notice = render_single_repo_notice(args.path, files)
    if notice is None:
        return []      # nothing reaches across a boundary; no question to ask
    print(notice, file=sys.stderr)
    print("ghost_buster: scan this repository alone, or join another? "
          "Enter path(s) to join, separated by spaces, or press Enter for "
          "single-repo: ", end="", file=sys.stderr, flush=True)
    try:
        answer = input().strip()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return []
    return [Path(p) for p in answer.split() if p]


def _skipped(name: str, flag: str) -> None:
    """An opt-out leaves a receipt.

    WHY THIS FUNCTION EXISTS (v0.11.0)

    Every repository check used to be off unless asked for, and a run that
    did not perform one said nothing at all about it. Measured on a real
    repository: a scan with --branches --secrets reported 34 findings and
    exit 1, looked complete, and never mentioned that test status had not
    been examined. The suite it did not run was hiding five clinical
    missed detections behind skips.

    So the checks are on by default now, and -- the half that matters more
    -- a skipped check announces itself on the same channel as a performed
    one. Whoever reads the output learns what was NOT looked at without
    having to reconstruct the command line.
    """
    print(f"ghost_buster: {name} SKIPPED at your request ({flag})", file=sys.stderr)


def _state(report) -> str:
    """A check that ran is the only state meaning the question was asked.
    `report.ran` False means it could not -- no git, no tests, no gitleaks."""
    return RAN if getattr(report, "ran", False) else COULD_NOT_RUN


def _run_repository_checks(args, findings: List[Finding], checks: dict):
    """The three checks that take a repository rather than a file list:
    --branches, --tests, --secrets. All three are ON by default; each
    appends to `findings` and prints its own one-line report to stderr,
    and each announces itself when turned off. Returns the
    TestStatusReport when --tests ran (the correlation layer needs the
    measured counts), else None.

    Extracted from main() for the same reason as _build_parser: these are
    one cohesive stage, and main() was over the long_function threshold."""
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
        checks["branches"] = _state(branch_report)
    else:
        _skipped("branch scan", "--no-branches")
        checks["branches"] = DECLINED

    test_report = None
    if args.tests and not args.trusted.trusted:
        print(declined_receipt("test status scan", args.trusted), file=sys.stderr)
        checks["tests"] = DECLINED
    elif args.tests:
        test_findings, test_report = scan_tests(
            args.path, python=args.tests_python, reruns=args.tests_reruns,
            timeout=args.tests_timeout,
        )
        print(render_test_report(test_report), file=sys.stderr)
        findings.extend(test_findings)
        checks["tests"] = _state(test_report)
    else:
        _skipped("test status scan", "--no-tests")
        checks["tests"] = DECLINED

    if args.project:
        project_findings, project_report = scan_project(args.path)
        print(render_project_report(project_report), file=sys.stderr)
        findings.extend(project_findings)
        checks["project"] = _state(project_report)
    else:
        _skipped("project scan", "--no-project")
        checks["project"] = DECLINED

    if args.secrets:
        secrets_findings, secrets_report = scan_secrets(
            args.path, gitleaks_path=args.secrets_binary, timeout=args.secrets_timeout,
        )
        print(render_secrets_report(secrets_report), file=sys.stderr)
        findings.extend(secrets_findings)
        checks["secrets"] = _state(secrets_report)
    else:
        _skipped("secrets scan", "--no-secrets")
        checks["secrets"] = DECLINED

    return test_report


def main(argv: List[str] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    # Consent to run this repository's code, resolved once and carried on
    # args so every check that executes code asks the same answer.
    args.trusted = trust_grant(args.path) if args.trust else trust_check(args.path)
    if args.trust:
        print(f"ghost_buster: trust: {args.trusted.identity}: {args.trusted.reason}", file=sys.stderr)
    elif args.trusted.store is None:
        print(f"ghost_buster: trust: {args.trusted.reason}", file=sys.stderr)

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
    # Every check's state, recorded whatever it is. This dict is the reason
    # the ledger can notice a blind spot: "declined" and "could not run" are
    # facts worth remembering, not the absence of one.
    checks = {"structural": RAN}
    profile = None
    if args.profile:
        import time
        started = time.perf_counter()
        with Profile() as profile:
            findings = run_all(files)
        profile_seconds = time.perf_counter() - started
    else:
        findings = run_all(files)

    if args.annotate_names:
        readme = args.annotate_readme or (args.path / "README.md")
        disagreements, changed, wrote_readme = annotate(files, readme, root=args.path)
        print(f"ghost_buster: {len(disagreements)} name disagreement(s); "
              f"annotated {len(changed)} file(s); "
              f"{'updated' if wrote_readme else 'no change to'} {readme}",
              file=sys.stderr)

    mutation_run = None
    if args.mutate and not args.trusted.trusted:
        print(declined_receipt("mutation analysis", args.trusted), file=sys.stderr)
        checks["mutate"] = DECLINED
    elif args.mutate:
        mutation_run = run_mutations(
            args.path, files, max_mutants_per_candidate=args.mutate_max,
            timeout=args.mutate_timeout, only=args.mutate_only,
        )
        findings.extend(mutation_run.findings)
        checks["mutate"] = RAN
    else:
        checks["mutate"] = NOT_RUN
        # Opt-in on cost (one pytest process per mutant), not because it
        # matters less -- so it is named on every run rather than simply
        # being absent.
        print("ghost_buster: mutation analysis NOT RUN (opt-in: --mutate)", file=sys.stderr)

    if args.kernel:
        kernel_findings, kernel_report = check_kernel(files, args.kernel)
        print(render_kernel_report(kernel_report), file=sys.stderr)
        findings.extend(kernel_findings)
        checks["kernel"] = RAN if kernel_report.ran else COULD_NOT_RUN
    else:
        checks["kernel"] = NOT_RUN
        print("ghost_buster: kernel check NOT RUN (opt-in: --kernel PATH)", file=sys.stderr)

    join_paths = _resolve_join_mode(args, files)
    if join_paths:
        roots = [args.path] + list(join_paths)
        files_by_root = {
            str(Path(r).resolve()): _collect_files(Path(r), args.exclude)
            for r in roots if Path(r).is_dir()
        }
        joined = build_joined_model(roots, files_by_root)
        boundary_findings = derive_boundary_findings(joined, files_by_root)
        print(render_boundary_report(joined, boundary_findings), file=sys.stderr)
        findings.extend(boundary_findings)
        checks["boundary"] = RAN if joined.ran else COULD_NOT_RUN
    else:
        checks["boundary"] = NOT_RUN
        notice = render_single_repo_notice(args.path, files)
        if notice:
            print(notice, file=sys.stderr)
        else:
            print("ghost_buster: boundary scan NOT RUN (single repository; "
                  "no unprovided packages reached for)", file=sys.stderr)

    if args.structure:
        model = build_model(args.path, files)
        structure_findings = derive_structure_findings(model)
        print(render_structure_report(model, structure_findings), file=sys.stderr)
        findings.extend(structure_findings)
        checks["structure"] = RAN if model.ran else COULD_NOT_RUN
        if args.structure_out:
            try:
                args.structure_out.write_text(model.to_json(), encoding="utf-8")
            except OSError as e:
                print(f"error: --structure-out {args.structure_out}: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
                return 2
        if args.structure_report:
            print(render_model(model), file=sys.stderr)
    else:
        _skipped("structure scan", "--no-structure")
        checks["structure"] = DECLINED

    test_report = _run_repository_checks(args, findings, checks)

    if args.no_correlate:
        _skipped("correlation", "--no-correlate")
        checks["correlate"] = DECLINED
    else:
        prior_runs = []
        for prior_path in args.correlate_with:
            try:
                prior_runs.append(load_prior_run(prior_path))
            except ValueError as e:
                # A typo'd --correlate-with is a usage error, not a silently
                # empty correlation: failing quiet here would mean reporting
                # "nothing to connect" for a cross-repo leak that is real.
                print(f"error: --correlate-with {e}", file=sys.stderr)
                return 2
        correlations = run_connectors(
            findings, prior_runs=prior_runs, test_report=test_report,
        )
        print(render_correlation_report(correlations), file=sys.stderr)
        findings.extend(correlations)
        checks["correlate"] = RAN

    # THE LEDGER RUNS BEFORE THE BASELINE DIFF, DELIBERATELY.
    # It records what was FOUND, not what was reported. If it ran after
    # the diff, `--accept` would quietly erase history: a finding you
    # agreed to stop hearing about would also stop being remembered, and
    # a regression years later would read as a first sighting.
    if args.ledger:
        ledger_path = args.ledger_path or (args.path / ".ghost_ledger.json")
        try:
            ledger = Ledger(ledger_path)
        except LedgerError as e:
            # Same posture as a corrupt baseline: a usage error, never a
            # silent fresh start. Starting over would report an empty
            # history as though it were a clean one.
            print(f"error: ledger {e}", file=sys.stderr)
            return 2
        checks["ledger"] = RAN
        ledger.record(
            findings, checks=checks, commit=_head_commit(args.path),
            tool_version=__version__, scanned=len(files),
        )
        history = ledger.derive(findings)
        print(render_ledger_report(ledger, history), file=sys.stderr)
        findings.extend(history)

        # Direction and surprise across runs. Emitted after the ledger has
        # folded this run in, so the current measurement is part of the
        # series it is judged against, and reported on the same channel as
        # every other check -- including when it declines to judge.
        trend = trajectory_derive(ledger.runs, root_label=str(args.path))
        print(render_trajectory_report(ledger.runs), file=sys.stderr)
        findings.extend(trend)
        try:
            ledger.save()
        except OSError as e:
            print(f"error: ledger {ledger_path} could not be written: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            return 2
    else:
        _skipped("ledger", "--no-ledger")

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

    casefile_path = args.casefile or (args.path / ".ghost_casefile.json")
    priors = None
    if casefile_path.is_file():
        priors = Casefile(casefile_path).annotate(new)

    if args.operate:
        try:
            op = operate(args.path, files, findings, checks,
                         casefile=Casefile(casefile_path), branch=args.operate_branch,
                         dry_run=args.operate_dry_run)
        except Refused as e:
            print(f"refused: {e}", file=sys.stderr)
            return 2
        print(op.render())
        if not op.came_in_untouched:
            print("error: the branch the patient came in on was modified; "
                  "this should be impossible and is a bug", file=sys.stderr)
            return 2
        return 0

    if args.json:
        print(FindingSet(new).to_json())
    else:
        _print_report(new, known, priors)
        # Candidacy is read off this run's own findings and the record of
        # which checks ran. Unknown counts against the patient.
        print(readiness.assess(findings, checks).render())
        print()
        if profile is not None:
            print(profile.render(profile_seconds))
            print()
        if mutation_run is not None:
            print(render_run(mutation_run, verbose=args.mutate_verbose))  # ghost_buster: name-disagreement -- `mutation_run` is `run` in the signature

    return 1 if any(f.severity in (Severity.CRITICAL, Severity.MAJOR) for f in new) else 0


if __name__ == "__main__":
    sys.exit(main())
