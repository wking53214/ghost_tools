"""serum.py -- the enhancement pass, and the proof it could be checked.

WHAT WAS WRONG WITH THE FIRST SERUM

A candidate got this, and only this: a rescan under `speed.Profile`, whose
counters wrap `ast.parse`, `Path.read_*` and `subprocess.run`. Every one of
those is a call GHOST_BUSTER makes. So the serum a patient received was a
profile of the scanner reading the patient, printed under the patient's
name. Measured 2026-09-17 on fortress-kernel, a healthy candidate:

    serum (measured, not applied):
      measured redundancy (same input, done again):
        read        17 calls, 4 distinct, 13 repeated  0.00s (0% of the run)
        ast.parse    4 calls, 4 distinct,  0 repeated  0.01s (6% of the run)
        subprocess   1 calls, 1 distinct,  0 repeated  0.00s (2% of the run)

Thirteen repeated reads, none of them by fortress-kernel, costing 0.00s,
presented as the reward for passing six health criteria. Those numbers were
worth having exactly once, when this toolkit was the patient and the run
showed 9.5 parses per file; on anybody else they describe the surgeon.

The static half was better aimed and barely present: a count of pitstop
findings, appended ONLY when there were some. A sweep that ran and found
nothing printed nothing, in the flagship feature of a project whose first
principle is that silence is the defect.

WHAT THE SERUM IS NOW

Three parts, each labelled with whose facts it reports.

  the surface     every enhancement site in the patient, always reported,
                  with a count when it is zero. This is about the patient.
  the dose        per site, whether the patient's own test suite could
                  catch a mistake made there. This is about the patient's
                  suite, and it is what makes a dose safe to give.
  the scan's work the old profiler numbers, kept, named for what they are,
                  and shown only when they are material. This is about
                  ghost_buster.

WHY VERIFIABILITY IS THE DOSE LADDER

"No ceiling: a candidate gets every dose the evidence supports, so long as
nothing breaks -- and the breaking is what the checks are for." The check
for an enhancement is the patient's test suite. Candidacy already
established that the suite passes, and then nothing used that fact.

A passing suite is not the same as a suite that would notice. So each site
is graded by the toolkit's own standard for whether a test means anything:
empty the function that holds the site, run the suite, and see whether
anything fails.

  covered    the suite failed with that function emptied. A mistake made
             here would be caught, so this is a site where an enhancement
             can be applied against a check that can fail.
  blind      the suite passed with that function emptied. The tests cannot
             see this code at all, so "the tests still pass" after an
             enhancement would prove nothing. No dose.
  unknown    the mutation would not apply, the run errored, or the budget
             ran out. Counts against the patient, like every other
             criterion this toolkit cannot assess.

That is the ladder the README promised: health buys doses only where the
suite can catch a mistake, and a candidate with a suite that sees nothing
is told so per site instead of being handed a number about the scanner.

WHY NOTHING IS REWRITTEN, INCLUDING THE ONE THAT LOOKS SAFE

`x in [1, 2, 3]` inside a loop is O(n) per pass where `x in {1, 2, 3}` is
O(1), every element is a hashable constant, and the rewrite looks like the
obvious first automatic dose. It is not safe, and the reason is worth
writing down because it is invisible until it bites:

    >>> [1] in [1, 2, 3]
    False
    >>> [1] in {1, 2, 3}
    TypeError: unhashable type: 'list'

List membership compares; set membership hashes the LEFT operand first. A
list-of-constants rewritten to a set-of-constants changes a `False` into a
TypeError for every unhashable value that ever reaches it. Nothing in the
tree says what reaches it, and a test suite that never passes an unhashable
value cannot tell you either -- it goes green, and the crash is somebody
else's afternoon.

So this is the same answer the invariant-call hoist gets: reported, ranked,
never rewritten. A remedy joins the list the day it carries a verification
that can fail, and "the suite is green" is not that verification for a
rewrite whose failure mode the suite does not exercise. What the serum can
do honestly is tell you, per site, whether your suite would have caught it.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import speed
from .mutation import _Scratch, _mutate_function, _safe_parse, _write_tree

#: Emptying the function is the strongest signal available and the cheapest
#: to explain: a suite that passes with the body replaced by `pass` cannot
#: see that function at all. A weaker operator (a flipped comparison, a
#: bumped constant) can leave a function that IS covered looking blind
#: because that particular mutation happened not to matter.
OPERATOR = "drop_body"

#: Whole seconds the verification may spend, baseline run included. It runs
#: the patient's entire suite once per site, so an unbounded version is a
#: surgeon who never closes. Over budget is reported per site, never
#: silently dropped.
DEFAULT_BUDGET = 120.0

COVERED = "covered"
BLIND = "blind"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Site:
    """One enhancement site in the patient, and the function holding it."""
    path: Path
    line: int
    kind: str
    what: str
    function: str = ""          # qualname, or "" when not inside one

    @property
    def where(self) -> str:
        return f"{self.path.name}:{self.line}"


@dataclass
class Dose:
    site: Site
    verdict: str = UNKNOWN
    reason: str = ""
    seconds: float = 0.0


@dataclass
class SerumReport:
    """What the enhancement pass established. `assessed` is load-bearing:
    a report with no doses because verification never ran reads exactly
    like a report with no doses because there was nothing to enhance, and
    only one of those is good news."""
    ran: bool = False
    reason: str = ""
    files_swept: int = 0
    sites: List[Site] = field(default_factory=list)
    doses: List[Dose] = field(default_factory=list)
    assessed: bool = False
    verification_reason: str = ""
    scan_work: List[str] = field(default_factory=list)
    scan_work_material: bool = False
    seconds: float = 0.0

    @property
    def covered(self) -> List[Dose]:
        return [d for d in self.doses if d.verdict == COVERED]

    @property
    def blind(self) -> List[Dose]:
        return [d for d in self.doses if d.verdict == BLIND]

    @property
    def unknown(self) -> List[Dose]:
        return [d for d in self.doses if d.verdict == UNKNOWN]


# ------------------------------------------------------------ the surface

def enclosing_function(tree: ast.Module, line: int) -> str:
    """The dotted qualname of the innermost function containing `line`.

    Empty when the line is at module scope, which is a real answer: there
    is no function to empty, so there is nothing to verify by emptying it.
    """
    best: Tuple[int, str] = (-1, "")

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = f"{prefix}.{child.name}" if prefix else child.name
            start = getattr(child, "lineno", None)
            end = getattr(child, "end_lineno", None)
            if start is not None and end is not None and start <= line <= end:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Innermost wins: a nested def inside a method is the
                    # thing whose body actually holds the site.
                    nonlocal best
                    if start > best[0]:
                        best = (start, name)
                walk(child, name)

    walk(tree, "")
    return best[1]


def find_sites(files: Sequence[Path]) -> List[Site]:
    """Every enhancement site, with the function that holds it."""
    from . import corpus

    out: List[Site] = []
    trees: Dict[Path, Optional[ast.Module]] = {}
    for stop in speed.find_pitstops(files):
        path = Path(stop.path)
        if path not in trees:
            trees[path] = corpus.parse(path)
        tree = trees[path]
        function = enclosing_function(tree, stop.line) if tree is not None else ""
        out.append(Site(path, stop.line, stop.kind, stop.what, function))
    return out


# --------------------------------------------------------------- the dose

def over_budget(spent: float, baseline_seconds: float, budget: float) -> bool:
    """Whether there is room for one more whole-suite run.

    `baseline_seconds` is what the unmutated run cost, which is the best estimate
    available of what the next one will cost. Asking whether `spent` alone
    is under budget would start a run that cannot finish inside it and
    then kill it, turning a site that could have been graded into an
    unknown -- and unknown counts against the patient.
    """
    return spent + baseline_seconds > budget


def verdict_for(code: int, function: str, tail: str = "") -> Tuple[str, str]:
    """What one mutated suite run establishes, and how it is said.

    The mapping is the whole argument of this module, so it is a function
    with a name rather than three branches inside a loop: a suite that
    fails with the function emptied can see it, a suite that passes cannot,
    and a run that did not finish establishes nothing.
    """
    if code == 0:
        return BLIND, (f"the suite passes with {function}() emptied, so it cannot "
                       f"tell whether an enhancement here changed anything")
    if code > 0:
        return COVERED, (f"the suite fails with {function}() emptied, so a mistake "
                         f"made here would be caught")
    return UNKNOWN, f"not assessed: the run did not complete ({tail[-120:]})"


def _run_suite(cwd: Path, timeout: float, python: Optional[str] = None) -> Tuple[int, str]:
    """The patient's whole suite, stopping at the first failure. Returns
    (returncode, tail). A non-zero code is all this needs: the question is
    whether ANYTHING notices, not which test did."""
    cmd = [python or sys.executable, "-m", "pytest", "-q", "-x",
           "-p", "no:cacheprovider"]
    env = dict(os.environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, env=env)
    except (subprocess.TimeoutExpired, OSError) as e:
        return -1, f"{type(e).__name__}: {e}"
    text = (proc.stdout or "").strip()
    return proc.returncode, "\n".join(text.splitlines()[-2:])


def assess_doses(root: Path, sites: Sequence[Site], *, budget: float = DEFAULT_BUDGET,
                 python: Optional[str] = None,
                 link_siblings: bool = True) -> Tuple[List[Dose], bool, str]:
    """Grade each site by whether the patient's suite could catch a mistake
    there. Returns (doses, assessed, reason).

    `assessed` is False when the baseline run did not establish a green
    suite in the scratch copy, in which case every verdict would be
    meaningless rather than merely unknown, and saying so once is the
    honest report.
    """
    doses = [Dose(site) for site in sites]
    if not sites:
        return doses, False, "no site to verify"

    started = time.perf_counter()
    scratch = _Scratch(Path(root).resolve(), link_siblings=link_siblings)
    try:
        code, tail = _run_suite(scratch.copy, timeout=budget, python=python)
        baseline_seconds = time.perf_counter() - started
        if code < 0:
            # The suite did not finish. Usually the budget: the baseline run
            # alone has to fit inside it, and a suite slower than that
            # cannot be the check for anything here. Said as its own reason
            # because "your suite is red" and "you gave me four seconds"
            # are different problems with different fixes.
            for dose in doses:
                dose.reason = (f"not assessed: the suite did not finish inside the "
                               f"{budget:.0f}s budget; raise it with --serum-budget")
            return (doses, False,
                    f"the suite did not finish inside the {budget:.0f}s verification "
                    f"budget ({tail[-120:]}); raise it with --serum-budget")
        if code != 0:
            # The suite passed during the workup and does not pass in the
            # copy: a path outside the tree, an editable install, a fixture
            # keyed to the original location. Whatever it is, no verdict
            # below would mean anything, so none is offered.
            return (doses, False,
                    f"the suite does not pass in a scratch copy of the patient "
                    f"(exit {code}): {tail[-160:]}")
        for dose in doses:
            spent = time.perf_counter() - started
            if over_budget(spent, baseline_seconds, budget):
                dose.reason = (
                    f"not assessed: the verification budget ({budget:.0f}s) ran "
                    f"out after {spent:.0f}s; raise it with --serum-budget")
                continue
            if not dose.site.function:
                dose.reason = ("not assessed: the site is at module scope, so "
                               "there is no function body to empty")
                continue
            target = scratch.path_for(dose.site.path)
            tree = _safe_parse(target)
            if tree is None:
                dose.reason = "not assessed: the file would not parse in the copy"
                continue
            applied, description = _mutate_function(tree, dose.site.function, OPERATOR)
            if not applied:
                dose.reason = f"not assessed: {description}"
                continue
            _write_tree(target, tree)
            at = time.perf_counter()
            code, tail = _run_suite(scratch.copy, timeout=max(1.0, budget - spent),
                                    python=python)
            dose.seconds = time.perf_counter() - at
            scratch.restore(dose.site.path)
            dose.verdict, dose.reason = verdict_for(code, dose.site.function, tail)
        return doses, True, ""
    finally:
        scratch.close()


# ------------------------------------------------------------------ report

def _material(lines: Sequence[str]) -> bool:
    """Whether the scan's own redundancy numbers are worth printing.

    They are the surgeon's, not the patient's, so they have to earn the
    space: something was actually repeated, and it cost a share of the run
    a reader could act on. On a four-file patient, 13 repeated reads
    costing 0.00s is not a finding about anything.
    """
    for line in lines:
        if "repeated" not in line:
            continue
        share = line.rsplit("(", 1)[-1].split("%")[0].strip()
        try:
            if int(share) >= 10:
                return True
        except ValueError:
            continue
    return False


def assess(root: Path, files: Sequence[Path], *, scan_work: Sequence[str] = (),
           budget: float = DEFAULT_BUDGET, python: Optional[str] = None,
           link_siblings: bool = True) -> SerumReport:
    started = time.perf_counter()
    report = SerumReport(ran=True, files_swept=len(files))
    report.scan_work = list(scan_work)
    report.scan_work_material = _material(report.scan_work)
    report.sites = find_sites(files)
    if report.sites:
        report.doses, report.assessed, report.verification_reason = assess_doses(
            root, report.sites, budget=budget, python=python,
            link_siblings=link_siblings)
    else:
        report.verification_reason = "no site to verify"
    report.seconds = time.perf_counter() - started
    return report


def render(report: SerumReport) -> List[str]:
    """The serum, as the operative report prints it."""
    if not report.ran:
        return [f"serum: not run ({report.reason or 'no reason given'})"]

    lines = ["serum (measured, not applied):"]

    # The surface. Printed whether or not anything was found, because a
    # sweep that found nothing and a sweep that never ran are the same two
    # lines of silence otherwise.
    if not report.sites:
        lines.append(
            f"  enhancement surface: none. {report.files_swept} file(s) swept for "
            f"loop pitstops, no site found.")
    else:
        lines.append(
            f"  enhancement surface: {len(report.sites)} site(s) in "
            f"{report.files_swept} file(s) swept")
        for site in report.sites:
            where = f"{site.where} {site.function}()" if site.function else site.where
            lines.append(f"    {site.kind:<26} {where}  {site.what}")

    # The dose.
    if report.sites and not report.assessed:
        lines.append(f"  dose: NOT ASSESSED -- {report.verification_reason}")
    elif report.sites:
        lines.append(
            f"  dose: {len(report.covered)} verifiable, {len(report.blind)} "
            f"unverifiable, {len(report.unknown)} not assessed "
            f"(the check is this patient's own suite)")
        for dose in report.doses:
            mark = {COVERED: "can verify ", BLIND: "cannot    ", UNKNOWN: "unknown   "}[dose.verdict]
            lines.append(f"    {mark} {dose.site.where}  {dose.reason}")

    # The scan's own work, named for whose it is.
    if report.scan_work_material:
        lines.append("  the scan's own work over this patient (ghost_buster's, "
                     "not the patient's):")
        lines.extend("  " + line for line in report.scan_work)
    elif report.scan_work:
        lines.append("  the scan's own work over this patient: nothing repeated "
                     "enough to act on (ghost_buster's numbers, not the patient's)")
    return lines
