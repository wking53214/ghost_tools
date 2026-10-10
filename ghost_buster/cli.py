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
import contextlib
import json
import os
import sys
import traceback
from pathlib import Path
from typing import List, Optional, Dict

from . import version_string
from . import attest
from .baseline import Baseline
from .trust import check as trust_check, grant as trust_grant
from .archive import marked as archive_marked
from .priors import build as build_priors, render as render_priors, to_json as priors_json
from .ledger import (
    Ledger, NOT_APPLICABLE, RAN,
)
from . import readiness
from .casefile import Casefile, Prior
from .mutation import render_run
from .schema import Finding, Severity
from .pipeline import Stop, gather, parse_size, SKIP_LIST_CAP

#: Where --json output goes. main() sets it to the real stdout before the
#: run, then points sys.stdout at stderr for the run itself, so nothing
#: printed by library code can land in the middle of the JSON document.
_OUT = {"stream": None}


def _emit(text: str) -> None:
    stream = _OUT["stream"] or sys.stdout
    print(text, file=stream)
    try:
        stream.flush()
    except (OSError, ValueError):
        pass


#: Exit codes. A caller must be able to tell "the scan ran and found
#: something" from "the scan did not happen", so they never share a number.
EXIT_CLEAN = 0      # scan ran; nothing new at MAJOR or above
EXIT_FINDINGS = 1   # scan ran; new CRITICAL or MAJOR findings (this is not a failure of the tool)
EXIT_USAGE = 2      # scan did not start: bad arguments, target missing or unreadable, unreadable baseline/ledger/casefile
EXIT_CRASH = 3      # scan started and died: an unhandled error inside ghost_buster itself
EXIT_INTERRUPTED = 130  # Ctrl-C (128 + SIGINT, the shell convention)

_BY_REQUEST = ("skipped at your request", "opt-in and not requested")


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


class _Parser(argparse.ArgumentParser):
    """argparse, except that a bad command line under --json still leaves
    valid JSON on stdout (the reason is on stderr either way)."""

    json_mode = False

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        if self.json_mode:
            _emit(_dump(_envelope("error", EXIT_USAGE, [], error=("usage", message))))
        raise SystemExit(EXIT_USAGE)


def _dump(payload) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _envelope(status, exit_code, findings, evidence=None, error=None,
              baseline=None, extra=None) -> dict:
    """What `--json` prints. `findings` is the same list of finding records
    it always printed, now under a key, beside the things a bare list cannot
    say: whether the scan finished, how much it looked at, and which checks
    did not run and why. An empty `findings` with status "incomplete" is not
    a clean result.

    `baseline` is `{"path": <str|null>, "suppressed": <int>}`: which baseline
    file was in effect and how many findings it hid from `findings`. When it
    hid some and the user did not name it with --baseline (it was found in
    the scanned folder, where whoever controls the folder controls it), that
    is an `unmeasured` row and the status is "incomplete"."""
    scan = {"files_scanned": 0, "files_skipped": 0, "files_unparsable": 0, "unparsable": [],
            "skipped_dirs": [], "skipped_dirs_more": 0, "symlinked_dirs": [],
            "symlinked_dirs_more": 0, "python_files_analysed": 0, "max_file_bytes": None}
    unmeasured = []
    if evidence is not None:
        scan = {
            "files_scanned": len(evidence.files),
            "files_skipped": evidence.files_skipped,
            "files_unparsable": len(evidence.unparsable),
            "unparsable": [{"file": f, "reason": why} for f, why in evidence.unparsable],
            **_skip_listing(evidence),
        }
        for name, state in evidence.checks.items():
            if state in (RAN, NOT_APPLICABLE):
                continue
            reason = evidence.reasons.get(name) or f"{name} did not run ({state})"
            row = {"check": name, "state": state, "reason": reason,
                   "by_request": reason.startswith(_BY_REQUEST)}
            if name == "structural" and evidence.detector_failures:
                row["detail"] = [{"detector": n, "error": w} for n, w in evidence.detector_failures]
            unmeasured.append(row)
        if evidence.unparsable:
            unmeasured.append({
                "check": "parse", "state": "unparsable", "by_request": False,
                "reason": (f"{len(evidence.unparsable)} file(s) could not be parsed, so the code "
                           "detectors skipped them"),
            })
        py_total = sum(1 for f in evidence.files if f.suffix == ".py")
        analysed = py_total - sum(1 for f, _ in evidence.unparsable if f.endswith(".py"))
        scan["python_files_analysed"] = analysed
        if analysed <= 0:
            unmeasured.append({
                "check": "python", "state": "none_analysed", "by_request": False,
                "reason": ("no Python file was analysed ("
                           + ("none were found" if py_total == 0
                              else f"{py_total} found, none could be read or parsed")
                           + "), so every code check is empty rather than clean"),
            })
    if baseline is None:
        baseline = {"path": None, "suppressed": 0}
    elif baseline.get("suppressed", 0) > 0 and not baseline.get("explicit", False):
        unmeasured.append({
            "check": "baseline", "state": "suppressing", "by_request": False,
            "reason": (f"{baseline['suppressed']} finding(s) were hidden by the baseline "
                       f"{baseline['path']}, which was found in the scanned folder and not "
                       "named with --baseline; whoever controls that folder controls what "
                       "this report omits. Pass --baseline FILE to take it on purpose."),
        })
    baseline = {"path": baseline.get("path"), "suppressed": baseline.get("suppressed", 0)}
    if status == "ok" and any(not u["by_request"] for u in unmeasured):
        status = "incomplete"
    out = {
        "status": status,
        "exit_code": exit_code,
        "error": None if error is None else {"kind": error[0], "message": error[1]},
        "findings": [f.as_dict() for f in findings],
        "scan": scan,
        "baseline": baseline,
        "unmeasured": unmeasured,
    }
    if extra:
        out.update(extra)
    return out


def _skip_listing(evidence) -> dict:
    """What the scan left out, by name. Lists are capped; counts are not."""
    rows = sorted(evidence.skipped_dirs.items(), key=lambda kv: (-kv[1]["files"], kv[0]))
    links = list(evidence.symlinked_dirs)
    return {
        "skipped_dirs": [{"name": n, "dirs": v["dirs"], "files": v["files"]}
                         for n, v in rows[:SKIP_LIST_CAP]],
        "skipped_dirs_more": max(0, len(rows) - SKIP_LIST_CAP),
        "symlinked_dirs": [{"path": n, "files": c} for n, c in links[:SKIP_LIST_CAP]],
        "symlinked_dirs_more": max(0, len(links) - SKIP_LIST_CAP),
        "max_file_bytes": evidence.max_file_bytes or None,
    }


def _build_parser() -> argparse.ArgumentParser:
    """Every flag in one place. Extracted from main() because ghost_buster's
    own `long_function` detector flagged main() at 194 lines against its
    threshold of 80 -- the argument table is the bulk of it and has no
    control flow, so lifting it out is the whole fix.
    """
    parser = _Parser(prog="ghost_buster")
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
        "--max-file-size", type=parse_size, default=None, metavar="SIZE",
        help="largest file to read, e.g. 5M or 262144 (default 5M, or $GHOST_MAX_FILE_BYTES). "
             "A bigger file is not read; it is listed as unassessable with the reason.",
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
        "--ledger", action=argparse.BooleanOptionalAction, default=None,
        help="OPT-IN (a default scan writes nothing into the folder it scans). Remember "
             "this run in <path>/.ghost_ledger.json -- or in --ledger-path FILE, which "
             "also turns this on -- and report what only history can say: a "
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


def _chain_result(args, code, status, message, extra=None) -> int:
    """--verify-chain's answer: text on stdout, or under --json the same
    envelope every other mode uses, with the chain verdict under `chain`."""
    if getattr(args, "json", False):
        err = None if status != "error" else ("usage", message)
        _emit(_dump(_envelope(status, code, [], error=err, extra={"chain": extra or {"report": message}})))
    elif status != "error":
        print(message)
    return code


def _verify_chain(args) -> int:
    """--verify-chain: read the ledger's own digest chain and report where
    it breaks. An alternate mode, not part of a scan -- it looks at the
    record rather than at the tree, so it returns before anything is
    scanned. See attest.verify for what a chain does and does not prove."""
    path = args.ledger_path or (args.path / ".ghost_ledger.json")
    if not path.is_file():
        msg = f"ghost_buster: chain: no ledger at {path}"
        print(msg, file=sys.stderr)
        return _chain_result(args, 2, "error", msg)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        msg = f"error: ledger {path}: {e}"
        print(msg, file=sys.stderr)
        return _chain_result(args, 2, "error", msg)
    runs = raw.get("runs") or []
    breaks = attest.verify(runs)
    broken = any("no link recorded" not in b.what for b in breaks)
    report = attest.render(breaks, len(runs))
    return _chain_result(args, 1 if broken else 0, "ok", report,
                         {"runs": len(runs), "broken": broken, "report": report,
                          "breaks": [b.what for b in breaks]})


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
        # A decision recorded under an older spelling of the id still applies.
        retired |= {f.id for f in evidence.findings if any(i in retired for i in f.previous_ids)}
        print(readiness.assess(evidence.findings, evidence.checks, retired).render())
    print()
    if evidence.profile is not None:
        print(evidence.profile.render(evidence.profile_seconds))
        print()
    if evidence.mutation_run is not None:
        print(render_run(evidence.mutation_run, verbose=args.mutate_verbose))


def _note_stale_baseline(baseline, findings) -> List[Finding]:
    """The receipt line and the finding, for baseline entries that matched
    nothing. Both, because they reach different readers: the line is on the
    same channel as every other check's receipt, and the finding is what a
    caller reading --json actually gets. Until 1.8.0 there was only the
    line. See Baseline.derive_findings for why the rot is worth reporting.

    What it returns belongs in the run's NEW list and never in the set the
    baseline diffs: the baseline does not get to suppress the report of its
    own rot.
    """
    stale = baseline.stale(findings)
    if stale:
        print(f"ghost_buster: {len(stale)} of {baseline.size} baseline entries matched nothing scanned "
              f"(fixed, renamed detector, or a baseline written from another checkout); "
              f"first: {stale[0].id} {stale[0].evidence.file}", file=sys.stderr)
    return baseline.derive_findings(findings)


def _setup_trust(args) -> None:
    """Handle trust resolution and logging."""
    args.trusted = trust_grant(args.path) if args.trust else trust_check(args.path)
    if args.trust:
        print(f"ghost_buster: trust: {args.trusted.identity}: {args.trusted.reason}", file=sys.stderr)
    elif args.trusted.store is None:
        print(f"ghost_buster: trust: {args.trusted.reason}", file=sys.stderr)


def _handle_priors_mode(args) -> int:
    """Handle --priors mode and exit early if active."""
    if not args.priors:
        return None

    casefile_path = args.casefile or (args.path / ".ghost_casefile.json")
    ledger_path = args.ledger_path or (args.path / ".ghost_ledger.json")
    ledger = Ledger(ledger_path) if ledger_path.is_file() else None
    rows = build_priors(Casefile(casefile_path), ledger)
    # Under --json this is a bare list of per-detector rows, NOT the scan
    # envelope: it is data about the case file, not a scan. See the README.
    text = priors_json(rows) if args.json else render_priors(rows, casefile_path, ledger_path if ledger else None)
    if args.json:
        _emit(text)
    else:
        print(text)
    return 0


def _fail(args, code: int, kind: str, message: str) -> int:
    """Say why the scan did not happen: a plain reason on stderr and, under
    --json, valid JSON on stdout with status "error". Returns the code."""
    print(message, file=sys.stderr)
    if getattr(args, "json", False):
        _emit(_dump(_envelope("error", code, [], error=(kind, message))))
    return code


def _validate_path(args) -> int:
    """Validate and gather arrival state from path."""
    if not args.path.is_dir():
        return _fail(args, EXIT_USAGE, "usage", f"error: {args.path} is not a directory")
    if not os.access(args.path, os.R_OK | os.X_OK):
        return _fail(args, EXIT_USAGE, "usage", f"error: {args.path} cannot be read (permission denied)")
    return None


def _load_baseline(baseline_path) -> Baseline:
    """Load baseline, with proper error handling."""
    try:
        return Baseline(baseline_path)
    except (ValueError, OSError) as e:
        raise Stop(f"error: baseline {baseline_path} could not be read: {type(e).__name__}: {e}") from e


def _gather_evidence_safe(args):
    """Gather evidence with error handling."""
    try:
        return gather(args)
    except Stop:
        raise


def _handle_accept_mode(args, baseline, findings, baseline_path, evidence=None) -> int:
    """Handle --accept mode and exit early if active."""
    if not args.accept:
        return None

    baseline.accept(findings)
    print(f"accepted {len(findings)} finding(s) into {baseline_path}", file=sys.stderr)
    if args.json:
        _emit(_dump(_envelope("ok", EXIT_CLEAN, findings, evidence,
                              baseline={"path": str(baseline_path), "suppressed": 0, "explicit": True})))
    return 0


def _prepare_output_data(args, evidence, baseline, findings) -> tuple:
    """Prepare new/known findings and associated data."""
    new, known = baseline.diff(findings)
    new.extend(_note_stale_baseline(baseline, findings))

    casefile_path = args.casefile or (args.path / ".ghost_casefile.json")
    priors = None
    if casefile_path.is_file():
        priors = Casefile(casefile_path).annotate(new)

    archive = archive_marked(args.path)
    if archive is not None:
        print(archive.receipt(), file=sys.stderr)

    return new, known, priors, archive, casefile_path


def _handle_dispatch_modes(args) -> int:
    """Handle verify-chain mode."""
    if args.verify_chain:
        return _verify_chain(args)
    return None


def main(argv: List[str] = None) -> int:
    """Run one scan and return its exit code (see EXIT_* above).

    Anything the code below does not handle itself is a crash: it is
    reported on stderr in one plain line, under --json it still leaves valid
    JSON on stdout with status "error", and the exit code is EXIT_CRASH --
    never the code that means "findings were found". Ctrl-C is EXIT_INTERRUPTED
    (130), also with an error envelope under --json.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    want_json = "--json" in argv
    _OUT["stream"] = sys.stdout
    try:
        return _main_json_quiet(argv)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        message = "ghost_buster: interrupted, the scan did not complete"
        return _fail(argparse.Namespace(json=want_json), EXIT_INTERRUPTED, "interrupted", message)
    except Exception as e:  # noqa: BLE001 -- this is the crash boundary
        message = f"ghost_buster: internal error, the scan did not complete: {type(e).__name__}: {e}"
        traceback.print_exc()
        return _fail(argparse.Namespace(json=want_json), EXIT_CRASH, "crash", message)
    finally:
        _OUT["stream"] = None


def _baseline_info(args, baseline, baseline_path, known) -> dict:
    """What `--json` reports about the baseline, and what the human report
    says when it hid findings the user never asked it to hide."""
    present = Path(baseline_path).is_file()
    info = {"path": str(baseline_path) if present else None,
            "suppressed": len(known), "explicit": args.baseline is not None}
    if info["suppressed"] and not info["explicit"] and not args.json:
        print(f"ghost_buster: WARNING: {info['suppressed']} finding(s) hidden by {baseline_path}, "
              "a baseline found in the scanned folder and not named with --baseline. "
              "Pass --baseline FILE to use it on purpose.", file=sys.stderr)
    return info


def _main_json_quiet(argv: List[str]) -> int:
    """Parse, then run. Under --json stdout carries one JSON document and
    nothing else: anything printed while the scan runs goes to stderr
    instead (_emit writes the document to the real stdout). Parsing happens
    first so `--help` and `--version` still print where they always did."""
    parser = _build_parser()
    parser.json_mode = "--json" in argv
    args = parser.parse_args(argv)
    if args.json:
        with contextlib.redirect_stdout(sys.stderr):
            return _main(args)
    return _main(args)


def _main(args) -> int:
    # Setup phase
    _setup_trust(args)

    # Early exit modes
    result = _handle_priors_mode(args)
    if result is not None:
        return result

    result = _validate_path(args)
    if result is not None:
        return result

    # --verify-chain reads the ledger, not the tree: it answers before
    # anything is scanned.
    result = _handle_dispatch_modes(args)
    if result is not None:
        return result

    # Gather evidence
    try:
        evidence = _gather_evidence_safe(args)
    except Stop as e:
        return _fail(args, EXIT_USAGE, "usage", str(e))

    findings = evidence.findings
    baseline_path = evidence.baseline_path

    # Load and validate baseline
    try:
        baseline = _load_baseline(baseline_path)
    except Stop as e:
        return _fail(args, EXIT_USAGE, "usage", str(e))

    # Accept mode
    result = _handle_accept_mode(args, baseline, findings, baseline_path, evidence)
    if result is not None:
        return result

    # Prepare output
    new, known, priors, archive, casefile_path = _prepare_output_data(args, evidence, baseline, findings)
    info = _baseline_info(args, baseline, baseline_path, known)

    code = EXIT_FINDINGS if any(f.severity in (Severity.CRITICAL, Severity.MAJOR) for f in new) else EXIT_CLEAN

    # Present results
    if args.json:
        _emit(_dump(_envelope("ok", code, new, evidence, baseline=info)))
    else:
        _present(args, evidence, new, known, priors, archive, casefile_path)

    return code


if __name__ == "__main__":
    sys.exit(main())
