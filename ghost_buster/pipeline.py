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

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Callable, Dict, Iterable, List, Optional

from . import attest
from . import __version__
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
    COULD_NOT_RUN, DECLINED, Ledger, LedgerError, NOT_APPLICABLE, NOT_RUN, RAN,
    _head_commit, render_report as render_ledger_report,
)
from .mechanical import run_all
from .mutation import run_mutations
from .project import render_report as render_project_report, scan as scan_project
from . import corpus
from .schema import Finding, disambiguate_ids, paths_from_scan_root, scanning
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
    #: Why each check in `checks` is in the state it is in, in plain words.
    #: Only checks that did not run have an entry.
    reasons: Dict[str, str] = field(default_factory=dict)
    #: (detector, "ExcType: message") for every file-level detector that
    #: raised. Its findings are absent from the run; the others still ran.
    detector_failures: List[tuple] = field(default_factory=list)
    #: .py files no structural detector could read, with the reason.
    unparsable: List[tuple] = field(default_factory=list)
    #: .py/.md files under the root that were left out (excluded directory,
    #: dot-file, egg-info, or a second name for a file already counted).
    files_skipped: int = 0
    #: Excluded directory names met under the scan root, with how many
    #: directories carried that name and how many .py/.md files sat inside.
    #: {name: {"dirs": n, "files": m}}. The scan names what it did not look at.
    skipped_dirs: Dict[str, Dict[str, int]] = field(default_factory=dict)
    #: Symlinked directories whose files were NOT scanned (their target is
    #: outside the scan root, or they point back into the tree being walked),
    #: [(relative path, files behind it)].
    symlinked_dirs: List[tuple] = field(default_factory=list)
    #: The largest file read, in bytes (--max-file-size).
    max_file_bytes: int = 0


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
    return _collect(root, extra_excludes)[0]


def _collect(root: Path, extra_excludes: Iterable[str] = ()):
    """(files, number of candidate files left out). See `_collect_detail`."""
    found = _collect_detail(root, extra_excludes)
    return found.files, found.skipped


@dataclass
class Collected:
    files: List[Path]
    skipped: int
    #: {excluded dir name: {"dirs": directories with that name, "files": candidate files inside}}
    skipped_dirs: Dict[str, Dict[str, int]]
    #: [(posix path relative to root, candidate files behind the link)] for
    #: symlinked directories that were not walked into and whose files are
    #: not scanned under any other name.
    symlinked_dirs: List[tuple]


def _is_candidate(name: str) -> bool:
    return name.endswith(".py") or name.endswith(".md")


def _count_candidates(directory: str, limit: int = 200_000) -> int:
    """Candidate files under `directory`, not following links; stops
    counting at `limit` so a pathological tree cannot stall the scan."""
    total = 0
    for _dp, _dn, names in os.walk(directory, followlinks=False):
        total += sum(1 for n in names if _is_candidate(n))
        if total >= limit:
            break
    return total


def _collect_detail(root: Path, extra_excludes: Iterable[str] = ()) -> Collected:
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

    What was skipped is NAMED (unreleased): every excluded directory name met
    under the root is counted, with the files inside it, and a symlinked
    directory is never walked into (a link could point outside the tree or
    back into it) but is recorded with the files behind it, unless its
    target is inside the root and so is scanned under its real name anyway.
    """
    excluded = _EXCLUDED_DIRS | set(extra_excludes)
    root = Path(root)
    # Each real path once: a symlinked file is otherwise listed under both
    # names, and every function in it becomes its own near-duplicate.
    # Measured on OBSERVE, which keeps genuine symlinks.
    #
    # WHICH OF THE TWO NAMES SURVIVES (v1.7.1)
    #
    # The file, never the link to it. De-duplicating kept whichever name
    # sorted first, which is arbitrary, and when the link sorted first every
    # finding in that file named the link -- so a reader who followed the
    # reported path and looked at its history saw a symlink that had never
    # changed, and concluded nothing had happened. The bytes were in the
    # other file, which no finding mentioned.
    #
    # A finding has to name the path whose history will show the change.
    # Nothing else here moves for a repository with no symlinks in it.
    # A root that itself sits under an excluded name excludes everything.
    root_excluded = [part for part in root.parts if part in excluded]
    candidates, skipped_dirs, symlinked = _walk_candidates(root, excluded, bool(root_excluded))
    if root_excluded:
        # Everything is under an excluded name; say which one.
        skipped_dirs.setdefault(root_excluded[0], {"dirs": 0, "files": 0})["files"] += len(candidates)
        return Collected([], len(candidates), skipped_dirs, symlinked)
    out = _one_per_real_file(candidates)
    total_candidates = len(candidates) + sum(r["files"] for r in skipped_dirs.values())
    return Collected(out, total_candidates - len(out), skipped_dirs, symlinked)


def _one_per_real_file(candidates: List[Path]) -> List[Path]:
    """Each real path once, never a dot-file (see the notes in `_collect_detail`)."""
    seen_real: Dict[Path, int] = {}
    out: List[Path] = []
    for p in candidates:
        if p.name.startswith("."):
            continue
        real = p.resolve()
        already = seen_real.get(real)
        if already is not None:
            if out[already].is_symlink() and not p.is_symlink():
                out[already] = p
            continue
        seen_real[real] = len(out)
        out.append(p)
    return out


def _walk_candidates(root: Path, excluded, root_excluded: bool):
    """(sorted candidate files, skipped dirs by name, symlinked dirs not followed)."""
    skipped_dirs: Dict[str, Dict[str, int]] = {}
    symlinked: List[tuple] = []
    candidates: List[Path] = []
    real_root = os.path.realpath(str(root))

    def note_skipped(name: str, dirs: int, files: int) -> None:
        row = skipped_dirs.setdefault(name, {"dirs": 0, "files": 0})
        row["dirs"] += dirs
        row["files"] += files

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for d in list(dirnames):
            full = here / d
            if full.is_symlink():
                dirnames.remove(d)           # os.walk would not descend anyway
                if d in excluded:
                    note_skipped(d, 1, 0)
                    continue
                target = os.path.realpath(str(full))
                loops = target == real_root or real_root.startswith(target + os.sep)
                if target.startswith(real_root + os.sep) and not loops:
                    continue                 # its files are scanned under their real names
                behind = 0 if loops or not os.path.isdir(target) else _count_candidates(target)
                symlinked.append((PurePath(os.path.relpath(full, root)).as_posix(), behind))
            elif d in excluded and not root_excluded:
                dirnames.remove(d)
                note_skipped(d, 1, _count_candidates(str(full)))
            elif d.endswith(".egg-info"):
                dirnames.remove(d)
                note_skipped("*.egg-info", 1, _count_candidates(str(full)))
        for n in filenames:
            if _is_candidate(n):
                candidates.append(here / n)
    candidates.sort()
    return candidates, skipped_dirs, symlinked


#: How many names a scan lists for skipped or symlinked directories before
#: it says "and N more". The counts stay exact; only the list is capped.
SKIP_LIST_CAP = 20


def render_skipped_dirs(skipped: Dict[str, Dict[str, int]]) -> str:
    rows = sorted(skipped.items(), key=lambda kv: (-kv[1]["files"], kv[0]))
    shown = ", ".join(f"{name} ({v['dirs']} dir(s), {v['files']} file(s))"
                      for name, v in rows[:SKIP_LIST_CAP])
    return shown + (f", and {len(rows) - SKIP_LIST_CAP} more" if len(rows) > SKIP_LIST_CAP else "")


def _max_file_bytes(args) -> int:
    """--max-file-size, else $GHOST_MAX_FILE_BYTES, else the default."""
    value = getattr(args, "max_file_size", None)
    if value is None:
        env = os.environ.get("GHOST_MAX_FILE_BYTES", "").strip()
        if env:
            try:
                return parse_size(env)
            except ValueError:
                pass
        return corpus.DEFAULT_MAX_FILE_BYTES
    return int(value)


def parse_size(text: str) -> int:
    """'5242880', '512K', '5M', '1G' -> bytes."""
    t = str(text).strip().upper().rstrip("B")
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}.get(t[-1:], 1)
    n = int(float(t[:-1] if mult != 1 else t) * mult)
    if n < 1:
        raise ValueError("size must be positive")
    return n


def _run_detectors(args, files, detector_failures):
    """(findings, Profile or None, seconds) from every file-level detector."""
    if not args.profile:
        return run_all(files, detector_failures), None, 0.0
    import time
    started = time.perf_counter()
    with Profile() as profile:
        findings = run_all(files, detector_failures)
    return findings, profile, time.perf_counter() - started


def _withhold_oversize(files: List[Path], limit: int):
    """(files every check may read, [(file, size)] over `limit`)."""
    oversize = []
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size > limit:
            oversize.append((f, size))
    drop = {f for f, _ in oversize}
    return [f for f in files if f not in drop], oversize


def _unassessable(root: Path, files: List[Path], oversize, limit: int) -> List[tuple]:
    """(relative path, reason) for each file no check could assess."""
    out = [(PurePath(os.path.relpath(p, root)).as_posix(), why)
           for p, why in corpus.unparsed([f for f in files if f.suffix == ".py"])]
    out += [(PurePath(os.path.relpath(f, root)).as_posix(),
             f"too large: {size} bytes is over the {limit}-byte limit "
             "(--max-file-size), so it was not read")
            for f, size in oversize]
    return out


def _say_what_was_skipped(found: "Collected", say) -> None:
    if found.skipped_dirs:
        say("ghost_buster: skipped directories (not scanned): "
            + render_skipped_dirs(found.skipped_dirs))
    links = found.symlinked_dirs
    if links:
        say("ghost_buster: symlinked directories (not followed): "
            + ", ".join(f"{n} ({c} file(s))" for n, c in links[:SKIP_LIST_CAP])
            + (f", and {len(links) - SKIP_LIST_CAP} more" if len(links) > SKIP_LIST_CAP else ""))


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



def _run_repository_checks(args, findings: List[Finding], checks: dict, say, reasons=None):
    """The three checks that take a repository rather than a file list:
    --branches, --tests, --secrets. All three are ON by default; each
    appends to `findings` and prints its own one-line report to stderr,
    and each announces itself when turned off. Returns the
    TestStatusReport when --tests ran (the correlation layer needs the
    measured counts), else None.

    `reasons` collects, per check that did not run, why, for --json.

    Extracted from main() for the same reason as _build_parser: these are
    one cohesive stage, and main() was over the long_function threshold."""
    reasons = {} if reasons is None else reasons
    if args.branches:
        branch_findings, branch_report = scan_branches(args.path, args.branches_base)
        if branch_report.ran:
            say(
                f"ghost_buster: branch scan compared {branch_report.branches_scanned} "
                f"branch(es) against '{branch_report.base_branch}'"
            )
        else:
            say(f"ghost_buster: branch scan did not run: {branch_report.reason}")
            reasons["branches"] = branch_report.reason or "branch scan did not run"
        findings.extend(branch_findings)
        checks["branches"] = _state(branch_report)
    else:
        _skipped("branch scan", "--no-branches", say)
        checks["branches"] = DECLINED
        reasons["branches"] = "skipped at your request (--no-branches)"

    test_report = None
    if args.tests and not args.trusted.trusted:
        say(declined_receipt("test status scan", args.trusted))
        checks["tests"] = DECLINED
        reasons["tests"] = f"declined: {args.trusted.reason}"
    elif args.tests:
        test_findings, test_report = scan_tests(
            args.path, python=args.tests_python, reruns=args.tests_reruns,
            timeout=args.tests_timeout,
        )
        say(render_test_report(test_report))
        findings.extend(test_findings)
        checks["tests"] = _state(test_report)
        if checks["tests"] != RAN:
            reasons["tests"] = getattr(test_report, "reason", "") or "test scan did not run"
    else:
        _skipped("test status scan", "--no-tests", say)
        checks["tests"] = DECLINED
        reasons["tests"] = "skipped at your request (--no-tests)"

    if args.project:
        project_findings, project_report = scan_project(args.path)
        say(render_project_report(project_report))
        findings.extend(project_findings)
        checks["project"] = _state(project_report)
        if checks["project"] != RAN:
            reasons["project"] = getattr(project_report, "reason", "") or "project scan did not run"
    else:
        _skipped("project scan", "--no-project", say)
        checks["project"] = DECLINED
        reasons["project"] = "skipped at your request (--no-project)"

    if args.secrets:
        secrets_findings, secrets_report = scan_secrets(
            args.path, gitleaks_path=args.secrets_binary, timeout=args.secrets_timeout,
        )
        say(render_secrets_report(secrets_report))
        findings.extend(secrets_findings)
        checks["secrets"] = _state(secrets_report)
        if checks["secrets"] != RAN:
            reasons["secrets"] = getattr(secrets_report, "reason", "") or "secrets scan did not run"
    else:
        _skipped("secrets scan", "--no-secrets", say)
        checks["secrets"] = DECLINED
        reasons["secrets"] = "skipped at your request (--no-secrets)"

    return test_report




def _run_opt_in_analyses(args, files, findings, checks, say, reasons=None):
    """--mutate and --kernel: the two checks that are off unless asked for.
    Both cost something a default run should not spend -- mutation runs one
    pytest process per mutant, and a kernel check needs a second tree to
    compare against -- and both announce themselves when not run, because
    an absent check is a fact about the scan. Returns the MutationRun when
    one happened, which the report renders."""
    reasons = {} if reasons is None else reasons
    mutation_run = None
    if args.mutate and not args.trusted.trusted:
        say(declined_receipt("mutation analysis", args.trusted))
        checks["mutate"] = DECLINED
        reasons["mutate"] = f"declined: {args.trusted.reason}"
    elif args.mutate:
        mutation_run = run_mutations(
            args.path, files, max_mutants_per_candidate=args.mutate_max,
            timeout=args.mutate_timeout, only=args.mutate_only,
        )
        findings.extend(mutation_run.findings)
        checks["mutate"] = RAN
    else:
        checks["mutate"] = NOT_RUN
        reasons["mutate"] = "opt-in and not requested (--mutate)"
        # Opt-in on cost (one pytest process per mutant), not because it
        # matters less -- so it is named on every run rather than simply
        # being absent.
        say("ghost_buster: mutation analysis NOT RUN (opt-in: --mutate)")

    if args.kernel:
        kernel_findings, kernel_report = check_kernel(files, args.kernel)
        say(render_kernel_report(kernel_report))
        findings.extend(kernel_findings)
        checks["kernel"] = RAN if kernel_report.ran else COULD_NOT_RUN
        if not kernel_report.ran:
            reasons["kernel"] = getattr(kernel_report, "reason", "") or "kernel check did not run"
    else:
        checks["kernel"] = NOT_RUN
        reasons["kernel"] = "opt-in and not requested (--kernel PATH)"
        say("ghost_buster: kernel check NOT RUN (opt-in: --kernel PATH)")
    return mutation_run


def _run_model_checks(args, files, findings, checks, say, reasons=None) -> None:
    """The two checks that build a model of the code before deriving
    anything from it: the cross-repository boundary (--join) and this
    repository's own structure (--structure). Both append to `findings`
    and leave their state in `checks`."""
    reasons = {} if reasons is None else reasons
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
        if not joined.ran:
            reasons["boundary"] = getattr(joined, "reason", "") or "boundary scan did not run"
    else:
        # Which of the two it is, the notice already decides: it is written
        # when this repository reaches for a package it does not provide or
        # holds a dormant test, and withheld when it does neither. That is
        # exactly the difference between a seam left unchecked and no seam
        # at all, so the state follows the notice rather than assuming the
        # worse of the two. Before 1.8.0 both were NOT_RUN and every
        # single-repository scan grew a blind-spot streak nothing could
        # clear.
        notice = render_single_repo_notice(args.path, files)
        if notice:
            checks["boundary"] = NOT_RUN
            reasons["boundary"] = ("single-repository scan; this repository reaches across a "
                                   "boundary and no other repository was joined (--join)")
            say(notice)
        else:
            checks["boundary"] = NOT_APPLICABLE
            say("ghost_buster: boundary scan NOT APPLICABLE (single repository; "
                "no unprovided packages reached for, no dormant tests)")

    if args.structure:
        model = build_model(args.path, files)
        structure_findings = derive_structure_findings(model)
        say(render_structure_report(model, structure_findings))
        findings.extend(structure_findings)
        checks["structure"] = RAN if model.ran else COULD_NOT_RUN
        if not model.ran:
            reasons["structure"] = getattr(model, "reason", "") or "structure scan did not run"
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
        reasons["structure"] = "skipped at your request (--no-structure)"


def _correlate(args, findings, checks, test_report, say, reasons=None) -> None:
    """Connect findings to each other and to prior runs. This reads
    findings already computed and runs no new scan, which is why it is
    normally free and on by default."""
    if args.no_correlate:
        _skipped("correlation", "--no-correlate", say)
        checks["correlate"] = DECLINED
        if reasons is not None:
            reasons["correlate"] = "skipped at your request (--no-correlate)"
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
    ledger_path = args.ledger_path or (args.path / ".ghost_ledger.json")
    # Opt-in: a default scan writes nothing into the folder it scans. An
    # explicit --ledger, or an explicit --ledger-path, is the request.
    wanted = args.ledger if args.ledger is not None else args.ledger_path is not None
    if not wanted:
        if args.ledger is False:
            _skipped("ledger", "--no-ledger", say)
        else:
            say("ghost_buster: ledger NOT UPDATED (opt-in: --ledger or --ledger-path FILE)"
                + (f"; the existing {ledger_path} was left untouched" if ledger_path.is_file() else ""))
        return
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
        # So the ledger can ask git what moved since the run it remembers.
        # A file that moved is not a defect that was fixed.
        root=args.path,
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
    # The scan folder, fully resolved, once. Ids are relative to it (see
    # schema.scanning), so how it was typed -- ./x, x/, a relative path, a
    # symlink to it -- cannot change them.
    args.path = Path(os.path.realpath(args.path))
    with scanning(args.path):
        return _gather(args, say)


def _gather(args, say) -> Evidence:
    baseline_path = args.baseline or (args.path / ".ghost_baseline.json")
    corpus.set_max_file_bytes(_max_file_bytes(args))
    found = _collect_detail(args.path, args.exclude)
    files, files_skipped = found.files, found.skipped
    # A file over the size limit is never read, by any detector: it stays in
    # the scan's file list (so it is counted and named) but is withheld from
    # every check and reported as unassessable with the reason.
    all_files = files
    limit = corpus.max_file_bytes()
    files, oversize = _withhold_oversize(all_files, limit)
    if not all_files:
        # A scan of nothing is not a clean scan. A checkout under a directory
        # named venv, node_modules or .tox, an empty directory, or a wrong
        # path all used to print "0 new finding(s)" and exit 0 (measured
        # 2026-09-08).
        raise Stop(f"error: no .py or .md files to scan under {args.path} "
                   f"(excluded directory names: "
                   f"{', '.join(sorted(_EXCLUDED_DIRS | set(args.exclude)))})")
    say(f"ghost_buster: scanning {len(all_files)} file(s) under {args.path}")
    # Every check's state, recorded whatever it is. This dict is the reason
    # the ledger can notice a blind spot: "declined" and "could not run" are
    # facts worth remembering, not the absence of one.
    checks = {"structural": RAN}
    reasons: Dict[str, str] = {}
    detector_failures: List[tuple] = []
    findings, profile, profile_seconds = _run_detectors(args, files, detector_failures)

    for name, why in detector_failures:
        say(f"ghost_buster: detector {name} FAILED and its findings are missing: {why}")
    unparsable = _unassessable(args.path, files, oversize, limit)
    _say_what_was_skipped(found, say)
    if unparsable:
        say(f"ghost_buster: {len(unparsable)} file(s) could not be parsed and were not analysed by the code detectors")
    if detector_failures:
        checks["structural"] = COULD_NOT_RUN
        reasons["structural"] = "; ".join(f"{n}: {w}" for n, w in detector_failures)

    mutation_run = _run_opt_in_analyses(args, files, findings, checks, say, reasons)

    _run_model_checks(args, files, findings, checks, say, reasons)

    test_report = _run_repository_checks(args, findings, checks, say, reasons)

    _correlate(args, findings, checks, test_report, say, reasons)

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

    paths_from_scan_root(findings, files, args.path)

    return Evidence(files=all_files, findings=findings, checks=checks,
                    baseline_path=baseline_path, test_report=test_report,
                    mutation_run=mutation_run, profile=profile,
                    profile_seconds=profile_seconds, reasons=reasons,
                    detector_failures=detector_failures, unparsable=unparsable,
                    files_skipped=files_skipped, skipped_dirs=found.skipped_dirs,
                    symlinked_dirs=found.symlinked_dirs, max_file_bytes=limit)
