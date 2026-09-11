"""The surgeon operates.

THE FIVE PHASES, AND WHERE EACH LIVES

  workup        the caller's scan: run_all plus whatever checks ran. Handed
                in as findings and the record of what ran. This module does
                not re-examine; it operates on the examination it was given.
  diagnosis     readiness.assess -- is this patient healthy enough to
                enhance, and if not, why.
  operate       this module. Every remedy with a verification that can fail
                is applied, the patient is re-examined, and the difference
                is recorded as a Cut. Cuts are commits on a branch; the
                operative chain IS the git log.
  re-examine    after every cut, run_all again. What closed is healed. What
                appeared was exposed by the cut -- the spread -- and is the
                next thing on the table. Only what the re-examination can
                see is eligible to close: a finding from a layer it does
                not run (a committed secret, a failing test) is carried
                forward unchanged, never counted as healed because the
                second look did not include it. The first patient taught
                that one -- eight secrets "healed" by writing comments.
  follow-up     the case file. Every cut records its outcome, so the next
                operation starts from what this one learned.

THE SAFETY MODEL IS SURGERY'S OWN

  consent       --operate is opt-in. Nothing here runs by default.
  the table     a branch, created here, from a clean tree. The branch the
                patient came in on is never written to; that is checked at
                the end by comparing its HEAD before and after.
  the time-out  no cut without a verification that can fail. A remedy that
                cannot prove it left the program the same, or the tests
                green, does not run. In v1 that is one remedy, annotate,
                whose every edit is parsed before and after.
  refuse        a dirty tree, a tree that is not a repository, and a
                patient that cannot be re-examined are all refusals, not
                best efforts.

WHAT V1 CAN AND CANNOT CUT

One remedy qualifies today: `annotate` writes comments and a README table,
and every edit is verified by syntax-tree identity. Everything else the
toolkit finds -- a drifted copy, a swallowed exception, a hollow contract --
needs a judgement the tree does not contain, and is left on the table for
the human with the evidence beside it. A remedy joins this list the day it
carries a verification, not before.

THE SERUM

After the cuts, readiness is assessed again. A candidate gets the
enhancement pass: the profiler, which counts work the scan did more than
once, and the pitstop findings already in the report. In v1 the serum is
EVIDENCE, measured and ranked; it does not rewrite. Applying an enhancement
mechanically earns its place the same way a remedy does, with a check that
can fail -- and the check for an enhancement is the test suite, which is
why an untested patient is not a candidate.

No ceiling: a candidate gets every dose the evidence supports, so long as
nothing breaks. The breaking is what the checks are for.
"""

from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set

from . import corpus, readiness
from .annotate import annotate as annotate_names
from .casefile import EXPOSED, HEALED, Casefile
from .mechanical import registered_detectors, run_all
from .schema import Finding
from .speed import Profile


def _retired(casefile) -> set:
    """The finding ids the case file has dismissed as false, or nothing."""
    return casefile.retired() if casefile is not None else set()



class Refused(Exception):
    """The surgeon will not operate, and says why."""


class LeftOnTheTable(Exception):
    """An operation failed AND the repository could not be put back.

    Raised only when restoration itself fails, so the message can name the
    branch the tree was left on. The original failure is the __cause__.
    """


@contextmanager
def _on_the_table(root: Path, return_to: str):
    """Everything between opening the table and closing it.

    THE PROPERTY THIS ENFORCES

    The tree goes back to the branch it came in on, whatever happens in
    between: a remedy that raises, a detector that raises during the
    re-examination, a commit a hook rejects, a disk that fills, a keyboard
    interrupt. Before this existed the return was the last statement of a
    linear function, so any exception left the repository checked out on
    the operation branch -- twice with uncommitted edits, measured on four
    forced failures including one through the CLI. The branch the patient
    came in on was never written to, which was the property the module
    claimed and kept; being left switched was the property nobody checked.

    WHY THE RESET IS SAFE

    An operation refuses a dirty tree at the door, so every uncommitted
    change at this point is one the tool made. Discarding them restores
    what the caller had; keeping them would hand back a tree with edits
    nobody asked for. Committed cuts are not discarded: the branch stays,
    holding whatever cuts completed, because those are evidence.
    """
    try:
        yield
    finally:
        try:
            _git(root, "reset", "-q", "--hard", "HEAD")
            _git(root, "checkout", "-q", return_to)
        except Exception as restore_failed:            # noqa: BLE001
            raise LeftOnTheTable(
                f"the operation failed and the tree could not be returned to "
                f"{return_to}: {restore_failed}"
            ) from restore_failed


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise Refused(f"git {' '.join(args)}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


@dataclass(frozen=True)
class Cut:
    """One remedy, applied, re-examined, recorded."""

    step: int
    remedy: str
    changed_files: int
    closed: List[str]
    exposed: List[str]
    commit: str
    note: str = ""

    @property
    def healed(self) -> int:
        return len(self.closed)


@dataclass
class Operation:
    root: Path
    branch: str
    came_in_on: str
    head_before: str
    readiness_before: readiness.Readiness
    readiness_after: Optional[readiness.Readiness] = None
    cuts: List[Cut] = field(default_factory=list)
    on_the_table: List[Finding] = field(default_factory=list)
    serum: List[str] = field(default_factory=list)
    head_after: Optional[str] = None
    dry_run: bool = False

    @property
    def came_in_untouched(self) -> bool:
        """The branch the patient came in on has the HEAD it had.

        Not named after the patient: this tool's own identifiers are the
        vestigial-domain detector's reference corpus, and `patient` is a
        domain word in half the library. The metaphor lives in the prose."""
        return self.head_after == self.head_before

    def render(self) -> str:
        lines = [f"OPERATIVE REPORT  {self.root}",
                 f"  table      : {self.branch}" + ("  (dry run: nothing written)" if self.dry_run else ""),
                 f"  came in on : {self.came_in_on} @ {self.head_before[:10]}"
                 + ("  untouched" if self.came_in_untouched else "  *** MODIFIED ***"),
                 "", "before", *("  " + ln for ln in self.readiness_before.render().splitlines()), ""]
        if not self.cuts:
            lines.append("cuts: none. No remedy with a verification that can fail applied here.")
        for c in self.cuts:
            lines.append(f"cut {c.step}: {c.remedy}  ->  {c.commit[:10]}")
            lines.append(f"  {c.changed_files} file(s) changed, {c.healed} finding(s) healed, "
                         f"{len(c.exposed)} exposed")
            if c.note:
                lines.append(f"  {c.note}")
        lines.append("")
        if self.readiness_after is not None:
            lines += ["after", *("  " + ln for ln in self.readiness_after.render().splitlines()), ""]
        if self.on_the_table:
            lines.append(f"left on the table for a human ({len(self.on_the_table)}): "
                         "each needs a judgement the tree does not contain")
            for f in self.on_the_table[:12]:
                lines.append(f"  [{f.severity.value:8s}] {f.detector:24s} {f.summary[:70]}")
            if len(self.on_the_table) > 12:
                lines.append(f"  (+{len(self.on_the_table) - 12} more)")
            lines.append("")
        if self.serum:
            lines += ["serum (measured, not applied):", *("  " + s for s in self.serum), ""]
        return "\n".join(lines)


def _ids(findings: Sequence[Finding]) -> Set[str]:
    return {f.id for f in findings}


def _remedy_annotate(root: Path, files: Sequence[Path]) -> tuple[int, str]:
    """The one v1 remedy: every edit verified by syntax-tree identity."""
    _, changed, wrote_readme = annotate_names(files, root / "README.md", root=root)
    return len(changed) + int(wrote_readme), "name disagreements written down, comment-only, AST-verified"


REMEDIES: Dict[str, Callable[[Path, Sequence[Path]], tuple[int, str]]] = {
    "annotate": _remedy_annotate,
}


def operate(root: Path, files: Sequence[Path], findings: Sequence[Finding],
            checks: Dict[str, str], *, casefile: Optional[Casefile] = None,
            branch: Optional[str] = None, dry_run: bool = False,
            rescan: Callable[[Sequence[Path]], List[Finding]] = run_all) -> Operation:
    """Operate on `root`. Refuses rather than proceeding on a bad table."""
    root = Path(root)
    try:
        _git(root, "rev-parse", "--git-dir")
    except Refused:
        raise Refused("not a git repository; the surgeon needs a table")
    if not dry_run and _git(root, "status", "--porcelain"):
        # A dry run diagnoses and writes nothing, so a dirty tree is fine to
        # examine. An operation needs a clean table.
        raise Refused("working tree is dirty; commit or stash before operating")

    head_before = _git(root, "rev-parse", "HEAD")
    came_in_on = _git(root, "branch", "--show-current")
    # A patient that came in detached has no branch to protect, only a
    # commit; that is where it goes back to. Returning to "HEAD" would
    # leave it on the table (the first patient did exactly that).
    return_to = came_in_on or head_before
    came_in_on = came_in_on or "detached HEAD"
    branch = branch or f"ghost/operate-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"

    op = Operation(root=root, branch=branch, came_in_on=came_in_on, head_before=head_before,
                   readiness_before=readiness.assess(findings, checks, _retired(casefile)), dry_run=dry_run)
    if dry_run:
        # Nothing is written and no branch is opened, so there is nothing to
        # put back; the table below runs unguarded.
        _cut(op, root, files, findings, checks, casefile, rescan, dry_run=True)
        op.head_after = _git(root, "rev-parse", "HEAD")
        return op

    _git(root, "checkout", "-q", "-b", branch)
    with _on_the_table(root, return_to):
        _cut(op, root, files, findings, checks, casefile, rescan, dry_run=False)
    op.head_after = _git(root, "rev-parse", "HEAD")
    return op


def _cut(op: "Operation", root: Path, files: Sequence[Path], findings: Sequence[Finding],
         checks: Dict[str, str], casefile: Optional[Casefile],
         rescan: Callable[[Sequence[Path]], List[Finding]], *, dry_run: bool) -> None:
    """The operation itself: apply, re-examine, commit, assess.

    Split out of `operate` so the branch switch and its restoration can wrap
    every statement of it, rather than only the statements that run when
    nothing goes wrong.
    """
    current = list(findings)
    step = 0
    re_examines = set(registered_detectors())
    for name, remedy in REMEDIES.items():
        if dry_run:
            continue
        changed, note = remedy(root, files)
        if not changed:
            continue
        step += 1
        corpus.reset()
        carried = [f for f in current if f.detector not in re_examines]
        after = carried + list(rescan(files))
        closed = sorted(_ids(current) - _ids(after))
        exposed = sorted(_ids(after) - _ids(current))
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m",
             f"operate: {name}\n\n{note}\n\n{len(closed)} finding(s) healed, "
             f"{len(exposed)} exposed by this cut.")
        commit = _git(root, "rev-parse", "HEAD")
        op.cuts.append(Cut(step, name, changed, closed, exposed, commit, note))
        if casefile is not None:
            by_id = {f.id: f for f in current}
            for fid in closed:
                casefile.record_outcome(by_id[fid], HEALED, f"by {name}")
            by_id = {f.id: f for f in after}
            for fid in exposed:
                casefile.record_outcome(by_id[fid], EXPOSED, f"by {name}")
        current = after

    op.readiness_after = readiness.assess(current, checks, _retired(casefile))
    op.on_the_table = [f for f in current if f.detector not in ("name_disagreement",)]

    if op.readiness_after.candidate:
        started = time.perf_counter()
        corpus.reset()
        with Profile() as prof:
            rescan(files)
        op.serum = prof.render(time.perf_counter() - started).splitlines()
        pitstops = [f for f in current if f.detector in ("list_membership_in_loop", "loop_invariant_call")]
        if pitstops:
            op.serum.append(f"{len(pitstops)} static pitstop(s) in the report above")

    if casefile is not None and not dry_run:
        casefile.save()
