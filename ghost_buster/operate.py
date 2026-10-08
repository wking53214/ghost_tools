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

One remedy qualifies today: `annotate` writes comments only,
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

import hashlib
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set

from . import corpus, readiness
from . import serum as serum_mod
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
    #: The rendered serum, and the record it was rendered from. Both,
    #: because the report prints text and the ledger needs the facts.
    serum: List[str] = field(default_factory=list)
    serum_report: Optional["serum_mod.SerumReport"] = None
    head_after: Optional[str] = None
    dry_run: bool = False
    #: Seconds the serum may spend grading enhancement sites. It rides on
    #: the Operation rather than through `_cut`'s signature: the two call
    #: sites became byte-identical two-line blocks when it was a parameter,
    #: which this toolkit's own intra_function_duplicate_block detector
    #: rated MINOR on the function that runs the surgeon.
    serum_budget: float = serum_mod.DEFAULT_BUDGET

    @property
    def came_in_untouched(self) -> bool:
        """The branch the patient came in on has the HEAD it had.

        Not named after the patient: this tool's own identifiers are the
        vestigial-domain detector's reference corpus, and `patient` is a
        domain word in half the library. The metaphor lives in the prose."""
        return self.head_after == self.head_before

    def render(self) -> str:
        lines = [f"OPERATIVE REPORT  {self.root}",
                 f"  table      : {self.branch}" + ("  (dry run: no cut written)" if self.dry_run else ""),
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
            lines += [*self.serum, ""]
        return "\n".join(lines)


def _ids(findings: Sequence[Finding]) -> Set[str]:
    return {f.id for f in findings}


def _remedy_annotate(root: Path, files: Sequence[Path],
                     findings: Sequence[Finding]) -> tuple[int, str]:
    """Write down every name disagreement. Verified by syntax-tree identity.

    Takes `findings` and ignores them: it re-derives the disagreements from
    the tree itself. The parameter is part of the remedy contract, which
    every remedy shares whether or not it needs the whole of it.
    """
    _, changed = annotate_names(files, root=root)
    return len(changed), "name disagreements written down, comment-only, AST-verified"


REMEDIES: Dict[str, Callable[[Path, Sequence[Path], Sequence[Finding]], tuple[int, str]]] = {
    "annotate": _remedy_annotate,
}


#: Files ghost_buster writes into a repository it is examining. They are the
#: surgeon's own notes, not the patient's uncommitted work, and the
#: distinction matters twice below.
SURGEONS_NOTES = (".ghost_ledger.json", ".ghost_baseline.json", ".ghost_casefile.json")


def notes_on_arrival(root: Path) -> Dict[str, str]:
    """Digest of each surgeon's note as it stood before this run touched it.

    Called by the CLI before the workup, because "before" is a moment only
    the entry point can identify. The scan writes the ledger into the
    repository it is scanning, so by the time `operate` asks whether a
    committed note is dirty, the answer is yes and the reason is us --
    which is the whole deadlock `_dirty_paths` describes.

    A note that is absent or unreadable gets no entry, which reads
    downstream as "not clean on arrival" and is the safe direction: it
    refuses rather than proceeding.
    """
    out: Dict[str, str] = {}
    for name in SURGEONS_NOTES:
        try:
            out[name] = _note_digest((Path(root) / name).read_text(
                encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return out


def _note_digest(text: str) -> str:
    """A note's content, normalised the same way on both sides.

    Stripped before hashing because the other side of the comparison comes
    back through `git show`, whose output this module strips. Hashing raw
    bytes on one side and stripped text on the other never matches, which
    made every committed note look edited and kept the deadlock in place --
    found by the test below rather than by reading this function.

    A trailing-newline difference in a JSON record is not somebody's edit,
    so normalising it away is right on its own terms as well.
    """
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _was_clean_on_arrival(root: Path, path: str, arrival: Dict[str, str]) -> bool:
    """Did this note match its committed version when this run started?

    Compared against HEAD rather than against the file now: the file now is
    whatever the workup wrote, which is the thing being asked about.
    """
    if path not in arrival:
        return False
    try:
        committed = _git(root, "show", f"HEAD:{path}")
    except Refused:
        return False
    return _note_digest(committed) == arrival[path]


def _dirty_paths(root: Path, arrival: Optional[Dict[str, str]] = None) -> List[str]:
    """Uncommitted paths that belong to the PATIENT.

    WHY THIS IS NOT JUST `git status --porcelain` (v1.6.1)

    An operation refuses a dirty tree, and it was refusing trees it had
    dirtied itself. A scan writes `.ghost_ledger.json` into the repository
    it scanned; `--operate` scans first and operates second, in one
    process; so the door check saw the ledger the same run had just
    written and refused. Measured on ghost_tools at 8ac6744, from a
    verifiably clean checkout, in a single command: the run created the
    ledger and then refused its own output.

    That made `--operate` impossible with default flags on any repository
    that does not already track or ignore the ledger. The first real
    operation in the library only succeeded because it was run with
    `--no-ledger`, which nothing said was required.

    Untracked notes are ignored here. A TRACKED note that has been
    modified is not, PROVIDED the modification is not this run's own
    (v1.7.3).

    THE SAME BUG, ONE LEVEL DOWN

    "Tracked note, therefore somebody's real edit" is the wrong test, and
    it reinstated the exact deadlock the paragraph above describes for any
    repository that commits its ledger -- which this module's own
    documentation recommends doing, on the grounds that a governance
    record nobody keeps is worth nothing.

    Measured on a clean checkout, single command, no harness: commit
    `.ghost_ledger.json`, run `--operate`, and the workup writes the
    ledger, the door check sees a modified tracked file, and the operation
    refuses. Every time, forever. The tool dirties the tree and then
    declines to work because the tree is dirty.

    The distinction that matters was never tracked versus untracked. It is
    WHOSE EDIT IT IS. `arrival` is the digest of each note as it stood
    before this run touched anything, so a note that was clean when we
    arrived and differs now differs because of us. A note that was ALREADY
    modified on arrival is somebody's real uncommitted edit to a committed
    record, and refusing that is the behaviour worth keeping: the workup
    would otherwise overwrite it.

    With no `arrival` recorded, a tracked note counts as dirt exactly as
    before. Callers that do not snapshot lose nothing they had.
    """
    arrival = dict(arrival or {})
    dirt = []
    for line in _git(root, "status", "--porcelain").splitlines():
        # Split on the status token rather than by column. Porcelain pads
        # the status to two characters, and _git strips the output, so the
        # leading space of a " M path" line is gone by the time it arrives
        # and fixed columns read one character into the path. That cost a
        # test run to find, which is the argument for not parsing by
        # column in the first place.
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        code, path = parts
        # Porcelain quotes a path containing unusual characters, and a
        # quoted path is never one of ours, so it counts as the patient's.
        if path in SURGEONS_NOTES:
            if code == "??":
                continue
            if _was_clean_on_arrival(root, path, arrival):
                continue
        dirt.append(path)
    return dirt


def operate(root: Path, files: Sequence[Path], findings: Sequence[Finding],
            checks: Dict[str, str], *, casefile: Optional[Casefile] = None,
            branch: Optional[str] = None, dry_run: bool = False,
            arrival: Optional[Dict[str, str]] = None,
            serum_budget: float = serum_mod.DEFAULT_BUDGET,
            rescan: Callable[[Sequence[Path]], List[Finding]] = run_all) -> Operation:
    """Operate on `root`. Refuses rather than proceeding on a bad table."""
    root = Path(root)
    try:
        _git(root, "rev-parse", "--git-dir")
    except Refused:
        raise Refused("not a git repository; the surgeon needs a table")
    if not dry_run:
        # A dry run diagnoses and cuts nothing, so a dirty tree is fine to
        # examine. An operation needs a clean table.
        dirt = _dirty_paths(root, arrival)
        if dirt:
            raise Refused("working tree is dirty; commit or stash before operating "
                          f"({len(dirt)} path(s), first: {dirt[0]})")

    head_before = _git(root, "rev-parse", "HEAD")
    came_in_on = _git(root, "branch", "--show-current")
    # A patient that came in detached has no branch to protect, only a
    # commit; that is where it goes back to. Returning to "HEAD" would
    # leave it on the table (the first patient did exactly that).
    return_to = came_in_on or head_before
    came_in_on = came_in_on or "detached HEAD"
    branch = branch or f"ghost/operate-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"

    op = Operation(root=root, branch=branch, came_in_on=came_in_on, head_before=head_before,
                   readiness_before=readiness.assess(findings, checks, _retired(casefile)),
                   dry_run=dry_run, serum_budget=serum_budget)
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
        changed, note = remedy(root, files, current)
        if not changed:
            continue
        step += 1
        corpus.reset()
        carried = [f for f in current if f.detector not in re_examines]
        after = carried + list(rescan(files))
        closed = sorted(_ids(current) - _ids(after))
        exposed = sorted(_ids(after) - _ids(current))
        # Only the patient. `add -A` would sweep the surgeon's own notes
        # into the patient's history, because a scan writes its ledger into
        # the tree it scanned and the operation runs in the same process.
        _git(root, "add", "-A", "--", ".", *(f":(exclude){note_file}" for note_file in SURGEONS_NOTES))
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

    # Which criteria the re-examination could not re-establish. Only worth
    # saying when something actually changed: with no cuts the tree is the
    # one the workup examined, so nothing is carried.
    carried = (readiness.TESTS, readiness.SECRETS) if op.cuts else ()
    op.readiness_after = readiness.assess(current, checks, _retired(casefile), carried=carried)
    op.on_the_table = [f for f in current if f.detector not in ("name_disagreement",)]

    if op.readiness_after.candidate:
        # The profiler's counters wrap ast.parse, Path.read_* and
        # subprocess.run, which are ghost_buster's calls, not the
        # patient's. They are still measured -- they found the
        # 9.5-parses-per-file redundancy in this toolkit -- but they are
        # handed to the serum as the SCAN's work and labelled that way,
        # rather than printed under the patient's name as if they were a
        # finding about the patient. See serum.py.
        started = time.perf_counter()
        corpus.reset()
        with Profile() as prof:
            rescan(files)
        scan_work = prof.render(time.perf_counter() - started).splitlines()
        op.serum_report = serum_mod.assess(
            op.root, files, scan_work=scan_work, budget=op.serum_budget)
        op.serum = serum_mod.render(op.serum_report)

    if casefile is not None and not dry_run:
        casefile.save()
