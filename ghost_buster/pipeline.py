"""Gathering the evidence, which is a different job from presenting it.

WHY THIS MODULE EXISTS

`cli.py` grew into the application: it parsed arguments, ordered nine
checks, decided what each one's failure meant, assembled the findings,
recorded the ledger, and then printed a report. The tool's own detector
said so on every run -- `main` is one of the two findings in its own
baseline -- and an external reviewer put the consequence plainly: the
ordering of the evidence pipeline, which is the part that has to be
provably right, lived inside the part that reads arguments.

So the pipeline moved here, unchanged. The order is the same order,
because that order is load-bearing and is documented where it matters:
correlation before identity, identity before the ledger, the ledger
before the baseline diff.

WHAT THIS MODULE DOES NOT DO

Decide anything about presentation. It takes a `say` channel and writes
its receipts to it, so the caller owns where they go; and it raises
`Stop` for a usage error rather than choosing an exit code, because an
exit code is an interface decision. `cli.py` still owns both, and is now
about arguments, the baseline diff, the report and the exit status.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from . import attest
from . import __version__
from .annotate import annotate
from .boundary import (
    build_joined_model, derive_findings as derive_boundary_findings,
    render_report as render_boundary_report, render_single_repo_notice,
)
from .branches import scan as scan_branches
from .correlate import (
    load_prior_run, render_report as render_correlation_report, run_connectors,
)
from .kernel import check_kernel, render_report as render_kernel_report
from .ledger import (
    COULD_NOT_RUN, DECLINED, Ledger, LedgerError, NOT_RUN, RAN,
    _head_commit, render_report as render_ledger_report,
)
from .mechanical import run_all
from .mutation import run_mutations
from .project import render_report as render_project_report, scan as scan_project
from .schema import Finding, disambiguate_ids
from .secrets import render_report as render_secrets_report, scan as scan_secrets
from .speed import Profile
from .structure import (
    build_model, render_model, derive_findings as derive_structure_findings,
    render_report as render_structure_report,
)
from .testsuite import render_report as render_test_report, scan as scan_tests
from .trajectory import (
    derive as trajectory_derive, render_report as render_trajectory_report,
)
from .trust import declined_receipt


class Stop(Exception):
    """A usage error the caller should report and exit on.

    Carries the message and nothing else: what exit code it deserves is
    the interface's decision, and every one of these is a 2.
    """


def to_stderr(message: str) -> None:
    print(message, file=sys.stderr)


@dataclass
class Evidence:
    """Everything the scan established, and the record of what it ran."""
    files: List[Path] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    checks: Dict[str, str] = field(default_factory=dict)
    baseline_path: Optional[Path] = None
    test_report: object = None
    mutation_run: object = None
    profile: object = None
    profile_seconds: float = 0.0


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



def _resolve_join_mode(args, files, say=to_stderr) -> List[Path]:
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
    # A prompt is not a receipt: it needs no newline and has to reach a
    # terminal whatever the caller does with the receipt channel.
    print("ghost_buster: scan this repository alone, or join another? "
          "Enter path(s) to join, separated by spaces, or press Enter for "
          "single-repo: ", end="", file=sys.stderr, flush=True)
    try:
        answer = input().strip()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return []
    return [Path(p) for p in answer.split() if p]



def _skipped(name: str, flag: str, say) -> None:
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
    say(f"ghost_buster: {name} SKIPPED at your request ({flag})")



def _state(report) -> str:
    """A check that ran is the only state meaning the question was asked.
    `report.ran` False means it could not -- no git, no tests, no gitleaks."""
    return RAN if getattr(report, "ran", False) else COULD_NOT_RUN



def _run_repository_checks(args, findings: List[Finding], checks: dict, say):
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
            say(
                f"ghost_buster: branch scan compared {branch_report.branches_scanned} "
                f"branch(es) against '{branch_report.base_branch}'"
            )
        else:
            say(f"ghost_buster: branch scan did not run: {branch_report.reason}")
        findings.extend(branch_findings)
        checks["branches"] = _state(branch_report)
    else:
        _skipped("branch scan", "--no-branches", say)
        checks["branches"] = DECLINED

    test_report = None
    if args.tests and not args.trusted.trusted:
        say(declined_receipt("test status scan", args.trusted))
        checks["tests"] = DECLINED
    elif args.tests:
        test_findings, test_report = scan_tests(
            args.path, python=args.tests_python, reruns=args.tests_reruns,
            timeout=args.tests_timeout,
        )
        say(render_test_report(test_report))
        findings.extend(test_findings)
        checks["tests"] = _state(test_report)
    else:
        _skipped("test status scan", "--no-tests", say)
        checks["tests"] = DECLINED

    if args.project:
        project_findings, project_report = scan_project(args.path)
        say(render_project_report(project_report))
        findings.extend(project_findings)
        checks["project"] = _state(project_report)
    else:
        _skipped("project scan", "--no-project", say)
        checks["project"] = DECLINED

    if args.secrets:
        secrets_findings, secrets_report = scan_secrets(
            args.path, gitleaks_path=args.secrets_binary, timeout=args.secrets_timeout,
        )
        say(render_secrets_report(secrets_report))
        findings.extend(secrets_findings)
        checks["secrets"] = _state(secrets_report)
    else:
        _skipped("secrets scan", "--no-secrets", say)
        checks["secrets"] = DECLINED

    return test_report




def _run_opt_in_analyses(args, files, findings, checks, say):
    """--mutate and --kernel: the two checks that are off unless asked for.
    Both cost something a default run should not spend -- mutation runs one
    pytest process per mutant, and a kernel check needs a second tree to
    compare against -- and both announce themselves when not run, because
    an absent check is a fact about the scan. Returns the MutationRun when
    one happened, which the report renders."""
    mutation_run = None
    if args.mutate and not args.trusted.trusted:
        say(declined_receipt("mutation analysis", args.trusted))
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
        say("ghost_buster: mutation analysis NOT RUN (opt-in: --mutate)")

    if args.kernel:
        kernel_findings, kernel_report = check_kernel(files, args.kernel)
        say(render_kernel_report(kernel_report))
        findings.extend(kernel_findings)
        checks["kernel"] = RAN if kernel_report.ran else COULD_NOT_RUN
    else:
        checks["kernel"] = NOT_RUN
        say("ghost_buster: kernel check NOT RUN (opt-in: --kernel PATH)")
    return mutation_run


def _run_model_checks(args, files, findings, checks, say) -> None:
    """The two checks that build a model of the code before deriving
    anything from it: the cross-repository boundary (--join) and this
    repository's own structure (--structure). Both append to `findings`
    and leave their state in `checks`."""
    join_paths = _resolve_join_mode(args, files)
    if join_paths:
        roots = [args.path] + list(join_paths)
        files_by_root = {
            str(Path(r).resolve()): _collect_files(Path(r), args.exclude)
            for r in roots if Path(r).is_dir()
        }
        joined = build_joined_model(roots, files_by_root)
        boundary_findings = derive_boundary_findings(joined, files_by_root)
        say(render_boundary_report(joined, boundary_findings))
        findings.extend(boundary_findings)
        checks["boundary"] = RAN if joined.ran else COULD_NOT_RUN
    else:
        checks["boundary"] = NOT_RUN
        notice = render_single_repo_notice(args.path, files)
        if notice:
            say(notice)
        else:
            say("ghost_buster: boundary scan NOT RUN (single repository; "
                "no unprovided packages reached for)")

    if args.structure:
        model = build_model(args.path, files)
        structure_findings = derive_structure_findings(model)
        say(render_structure_report(model, structure_findings))
        findings.extend(structure_findings)
        checks["structure"] = RAN if model.ran else COULD_NOT_RUN
        if args.structure_out:
            try:
                args.structure_out.write_text(model.to_json(), encoding="utf-8")
            except OSError as e:
                raise Stop(f"error: --structure-out {args.structure_out}: "
                           f"{type(e).__name__}: {e}") from e
        if args.structure_report:
            say(render_model(model))
    else:
        _skipped("structure scan", "--no-structure", say)
        checks["structure"] = DECLINED


def _correlate(args, findings, checks, test_report, say) -> None:
    """Connect findings to each other and to prior runs. This reads
    findings already computed and runs no new scan, which is why it is
    normally free and on by default."""
    if args.no_correlate:
        _skipped("correlation", "--no-correlate", say)
        checks["correlate"] = DECLINED
        return
    prior_runs = []
    for prior_path in args.correlate_with:
        try:
            prior_runs.append(load_prior_run(prior_path))
        except ValueError as e:
            # A typo'd --correlate-with is a usage error, not a silently
            # empty correlation: failing quiet here would mean reporting
            # "nothing to connect" for a cross-repo leak that is real.
            raise Stop(f"error: --correlate-with {e}") from e
    correlations = run_connectors(
        findings, prior_runs=prior_runs, test_report=test_report,
    )
    say(render_correlation_report(correlations))
    findings.extend(correlations)
    checks["correlate"] = RAN


def _record_in_ledger(args, files, findings, checks, baseline_path, say) -> None:
    """Fold this run into the repository's history, then derive what the
    history says: which findings are old, and which way the series is
    going. Both are appended to `findings` as derived findings -- see
    schema.DERIVED_DETECTORS, which keeps them out of the measurement
    they are a statement about."""
    if not args.ledger:
        _skipped("ledger", "--no-ledger", say)
        return
    ledger_path = args.ledger_path or (args.path / ".ghost_ledger.json")
    try:
        ledger = Ledger(ledger_path)
    except LedgerError as e:
        # Same posture as a corrupt baseline: a usage error, never a
        # silent fresh start. Starting over would report an empty
        # history as though it were a clean one.
        raise Stop(f"error: ledger {e}") from e
    checks["ledger"] = RAN
    ledger.record(
        findings, checks=checks, commit=_head_commit(args.path),
        tool_version=__version__, scanned=len(files),
        # The records this run READ, as it read them. A later edit to
        # either is then visible as a disagreement with this run.
        records={"baseline": attest.digest_file(baseline_path),
                 "casefile": attest.digest_file(
                     args.casefile or (args.path / ".ghost_casefile.json"))},
    )
    history = ledger.derive(findings)
    say(render_ledger_report(ledger, history))
    findings.extend(history)

    # Direction and surprise across runs. Emitted after the ledger has
    # folded this run in, so the current measurement is part of the
    # series it is judged against, and reported on the same channel as
    # every other check -- including when it declines to judge.
    trend = trajectory_derive(ledger.runs, root_label=str(args.path))
    say(render_trajectory_report(ledger.runs))
    findings.extend(trend)
    try:
        ledger.save()
    except OSError as e:
        raise Stop(f"error: ledger {ledger_path} could not be written: "
                   f"{type(e).__name__}: {e}") from e


def gather(args, say: Callable[[str], None] = to_stderr) -> Evidence:
    """Run every check the arguments ask for, in the order that matters.

    Raises `Stop` on a usage error. Everything else is a finding.
    """
    baseline_path = args.baseline or (args.path / ".ghost_baseline.json")
    files = _collect_files(args.path, args.exclude)
    if not files:
        # A scan of nothing is not a clean scan. A checkout under a directory
        # named venv, node_modules or .tox, an empty directory, or a wrong
        # path all used to print "0 new finding(s)" and exit 0 (measured
        # 2026-09-08).
        raise Stop(f"error: no .py or .md files to scan under {args.path} "
                   f"(excluded directory names: "
                   f"{', '.join(sorted(_EXCLUDED_DIRS | set(args.exclude)))})")
    say(f"ghost_buster: scanning {len(files)} file(s) under {args.path}")
    # Every check's state, recorded whatever it is. This dict is the reason
    # the ledger can notice a blind spot: "declined" and "could not run" are
    # facts worth remembering, not the absence of one.
    checks = {"structural": RAN}
    profile = None
    profile_seconds = 0.0
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
        say(f"ghost_buster: {len(disagreements)} name disagreement(s); "
              f"annotated {len(changed)} file(s); "
              f"{'updated' if wrote_readme else 'no change to'} {readme}")

    mutation_run = _run_opt_in_analyses(args, files, findings, checks, say)

    _run_model_checks(args, files, findings, checks, say)

    test_report = _run_repository_checks(args, findings, checks, say)

    _correlate(args, findings, checks, test_report, say)

    # Every finding now has its own id, including the ones whose detector,
    # path and summary happen to match another's. This runs before the
    # ledger and the baseline because both key on the id: a collision that
    # survived to here would be remembered as one finding and suppressed by
    # one decision. See schema.disambiguate_ids.
    collided = disambiguate_ids(findings)
    if collided:
        say(f"ghost_buster: {collided} finding(s) shared an id with an earlier "
              "finding and were given their own; see the suffix in the report")

    # THE LEDGER RUNS BEFORE THE BASELINE DIFF, DELIBERATELY.
    # It records what was FOUND, not what was reported. If it ran after
    # the diff, `--accept` would quietly erase history: a finding you
    # agreed to stop hearing about would also stop being remembered, and
    # a regression years later would read as a first sighting.
    _record_in_ledger(args, files, findings, checks, baseline_path, say)

    return Evidence(files=files, findings=findings, checks=checks,
                    baseline_path=baseline_path, test_report=test_report,
                    mutation_run=mutation_run, profile=profile,
                    profile_seconds=profile_seconds)
