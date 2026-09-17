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
import json
import sys
from pathlib import Path
from typing import List, Optional, Dict

from . import version_string
from . import attest
from .baseline import Baseline
from .trust import check as trust_check, grant as trust_grant
from .archive import marked as archive_marked
from .priors import build as build_priors, render as render_priors, to_json as priors_json
from .ledger import (
    Ledger,
)
from . import readiness
from . import serum
from .casefile import Casefile, Prior
from .operate import Refused, notes_on_arrival, operate
from .mutation import render_run
from .schema import Finding, FindingSet, Severity
from .pipeline import Stop, gather


# Directory names never descended into. `site-packages` is the load-bearing
# one: it catches an installed-package tree regardless of what the enclosing
# virtualenv is called (.venv / venv / env / <anything>), which is the noise
# source that actually swamps a blind run -- a repo with a venv in its
# working tree was reporting thousands of findings from pytest's own source.
# The rest are VCS internals and tool caches. Matched against any component
# of a path, so a nested occurrence is still excluded.


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
        "--serum-budget", type=float, default=serum.DEFAULT_BUDGET, metavar="SECONDS",
        help="with --operate: whole seconds the serum may spend establishing, per "
             "enhancement site, whether this patient's own test suite would catch a "
             "mistake made there. It runs the suite once per site, so this is a real "
             "cost; a site the budget did not reach is reported as not assessed, never "
             "dropped. (default: %(default)ss)",
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
        "--priors", action="store_true",
        help="print what the case file knows, per detector: how many decisions, how often false, "
             "how often the decision held against the ledger, and the latest reasons. Scans nothing. "
             "With --json, as data.")
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
        "--verify-chain", action="store_true",
        help="read the ledger's digest chain and report the first break, then exit. "
             "Each run records a digest of the baseline and case file it read and a "
             "link to the run before it, so an edit to a past record is visible. This "
             "detects edits, not adversaries: there is no key, so whoever can write "
             "the ledger can recompute the chain. See ghost_buster/attest.py.",
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


def _verify_chain(args) -> int:
    """--verify-chain: read the ledger's own digest chain and report where
    it breaks. An alternate mode, not part of a scan -- it looks at the
    record rather than at the tree, so it returns before anything is
    scanned. See attest.verify for what a chain does and does not prove."""
    path = args.ledger_path or (args.path / ".ghost_ledger.json")
    if not path.is_file():
        print(f"ghost_buster: chain: no ledger at {path}", file=sys.stderr)
        return 2
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: ledger {path}: {e}", file=sys.stderr)
        return 2
    runs = raw.get("runs") or []
    breaks = attest.verify(runs)
    print(attest.render(breaks, len(runs)))
    return 1 if any("no link recorded" not in b.what for b in breaks) else 0


def _operate(args, evidence, casefile_path, archive, arrival=None) -> int:
    """--operate: the only mode that writes to the target. Everything it
    needs was already established by the scan; this decides whether to
    let it run and what to say about the result."""
    if archive is not None:
        print("refused: an archive is not a patient; remove .ghost_archive to operate",
              file=sys.stderr)
        return 2
    try:
        op = operate(args.path, evidence.files, evidence.findings, evidence.checks,
                     casefile=Casefile(casefile_path), branch=args.operate_branch,
                     dry_run=args.operate_dry_run, arrival=arrival,
                     serum_budget=args.serum_budget)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(op.render())
    if not op.came_in_untouched:
        print("error: the branch the patient came in on was modified; "
              "this should be impossible and is a bug", file=sys.stderr)
        return 2
    return 0


def _present(args, evidence, new, known, priors, archive, casefile_path) -> None:
    """The human report: the findings themselves, then what the run says
    about the repository as a whole. Writes to stdout and decides nothing
    -- main() owns the exit code."""
    _print_report(new, known, priors)
    # Candidacy is read off this run's own findings and the record of
    # which checks ran. Unknown counts against the patient.
    if archive is not None:
        print(f"serum candidacy: not assessed (archive: {archive.reason or 'no reason given'})")
    else:
        retired = Casefile(casefile_path).retired() if casefile_path.is_file() else set()
        print(readiness.assess(evidence.findings, evidence.checks, retired).render())
    print()
    if evidence.profile is not None:
        print(evidence.profile.render(evidence.profile_seconds))
        print()
    if evidence.mutation_run is not None:
        print(render_run(evidence.mutation_run, verbose=args.mutate_verbose))


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

    if args.priors:
        casefile_path = args.casefile or (args.path / ".ghost_casefile.json")
        ledger_path = args.ledger_path or (args.path / ".ghost_ledger.json")
        ledger = Ledger(ledger_path) if ledger_path.is_file() else None
        rows = build_priors(Casefile(casefile_path), ledger)
        print(priors_json(rows) if args.json else render_priors(rows, casefile_path, ledger_path if ledger else None))
        return 0

    if not args.path.is_dir():
        print(f"error: {args.path} is not a directory", file=sys.stderr)
        return 2

    arrival = notes_on_arrival(args.path) if args.path.is_dir() else {}

    # The evidence, gathered by pipeline.py. Everything from here down is
    # interface: the baseline diff, what to print, and what to exit with.
    try:
        evidence = gather(args)
    except Stop as e:
        print(e, file=sys.stderr)
        return 2
    # The two the baseline diff and the exit code are computed from. The
    # rest of the Evidence goes to whichever helper needs it.
    findings = evidence.findings
    baseline_path = evidence.baseline_path

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

    archive = archive_marked(args.path)
    if archive is not None:
        print(archive.receipt(), file=sys.stderr)

    if args.verify_chain:
        return _verify_chain(args)

    if args.operate:
        return _operate(args, evidence, casefile_path, archive, arrival)

    if args.json:
        print(FindingSet(new).to_json())
    else:
        _present(args, evidence, new, known, priors, archive, casefile_path)

    return 1 if any(f.severity in (Severity.CRITICAL, Severity.MAJOR) for f in new) else 0


if __name__ == "__main__":
    sys.exit(main())
