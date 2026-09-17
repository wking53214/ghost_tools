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

import hashlib
import re
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
# One containment rule, shared, deliberately. It lives in annotate.py because
# that is where the first hole was found and where its tests and mutants are;
# importing it rather than restating it is what makes "every write into the
# patient is contained" a single fact rather than three hopeful ones.
from .annotate import refuses as outside_the_patient
from .casefile import EXPOSED, HEALED, Casefile
from .mechanical import (_DATED_DOCUMENT, _TEST_COUNT_CLAIM_RE,
                        _WRITABILITY_LOOKBACK, claim_context, claim_shape,
                        registered_detectors, run_all, why_not_writable)
from .schema import Finding
from .speed import Profile


def _retired(casefile) -> set:
    """The finding ids the case file has dismissed as false, or nothing."""
    return casefile.retired() if casefile is not None else set()



class Refused(Exception):
    """The surgeon will not operate, and says why."""


class RemedyFailed(Exception):
    """A remedy wrote something and could not then prove it wrote what it
    meant to. Raised rather than returned, so the restoration guard puts
    the tree back: a cut whose verification did not hold is not a cut."""


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
    _, changed, wrote_readme = annotate_names(files, root / "README.md", root=root)
    return len(changed) + int(wrote_readme), "name disagreements written down, comment-only, AST-verified"


def _resolve(root: Path, finding: Finding) -> Optional[Path]:
    """The file a finding points at, as a path that exists under `root`.

    A finding records whatever path the scan walked, which may be absolute
    or relative to the caller's working directory rather than to the
    repository. A remedy writes to disk, so it resolves the path itself and
    declines rather than guessing when the answer is not inside the patient.
    """
    for candidate in (Path(finding.evidence.absolute_file or ""),
                      Path(finding.evidence.file or ""),
                      root / (finding.evidence.file or "")):
        if not str(candidate):
            continue
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            return resolved
    return None


def _remedy_doc_counts(root: Path, files: Sequence[Path],
                       findings: Sequence[Finding]) -> tuple[int, str]:
    """Write the measured test count over a documented one that contradicts it.

    WHY THIS IS THE SECOND REMEDY (v1.7.0)

    The first operation on a full-size patient made one cut, changed four
    files and healed nothing, because annotating a name disagreement
    records it rather than resolving it. The remedy set was documentary.
    This one closes findings.

    It is also the only pool in the library where the correct value is
    fully determined by evidence the tool already holds. A README claiming
    a test count is either right or wrong about a number that a run just
    measured; there is no judgement in the difference, which is what makes
    it safe to automate and why it is first rather than the larger pools
    (416 dead-code and 399 vestigial-name findings, both of which need a
    judgement the tree does not contain).

    THREE THINGS IT REFUSES, EACH FOR A DIFFERENT REASON

    A claim the run did not measure. It acts only on
    `doc_count_contradicted_by_run`, which exists only when `--tests`
    actually ran. The static detector's own count is a lower bound and says
    so, so writing that would replace a stale number with a wrong one.

    A suite that is not green. When collected and passed disagree, the
    sentence around the number is wrong for a reason no number can fix:
    "1727 tests passing" beside forty failures is accurate arithmetic and a
    false claim. Rewriting the digits would make the false sentence look
    checked. That one goes to a human.

    A claim that is not about this suite. A delta, a recorded transition,
    or a count quoted from somewhere else all match the same regex and all
    mean something other than a total. The connector filters these already;
    this re-checks, because the connector recommends and this one WRITES.

    THE VERIFICATION THAT CAN FAIL

    After writing, the file is read back from disk and three things must
    hold: the bytes are what was meant to be written, the claim at that
    position now reads the measured number, and the file's length moved by
    exactly the difference between the two numbers, so nothing but digits
    changed. Any of them failing raises `RemedyFailed`, and the guard puts
    the tree back.
    """
    claims = [f for f in findings if f.detector == "doc_count_contradicted_by_run"]
    if not claims:
        return 0, ""

    changed = 0
    declined: List[str] = []
    for finding in claims:
        documented = finding.attributes.get("documented_count", "")
        collected = finding.attributes.get("collected", "")
        passed = finding.attributes.get("passed", "")
        if not (documented and collected):
            continue
        if finding.attributes.get("writable") != "yes":
            # The detector read the document and the sentence around the
            # claim and said a machine must not rewrite this one. Measured
            # on the 38-repository library: this declines all 65.
            declined.append(finding.attributes.get("not_writable_because")
                            or "a claim the detector did not mark writable")
            continue
        if passed != collected:
            declined.append("a suite that is not green")
            continue
        # WHAT NEVER RAN IS NOT IN EITHER NUMBER (v1.7.3).
        #
        # `passed == collected` is satisfied by a suite with a whole file
        # missing from it. A module that cannot be imported contributes
        # nothing to either side, so the subtraction says green and the
        # sentence this remedy writes says "all passing".
        #
        # The tool knew. The same run reported the blocked module as a
        # finding of its own, named the missing import, and then certified
        # the suite anyway. That is the one failure a reader cannot catch
        # by looking at the diff: every byte is in a permitted place and
        # the document is now false.
        #
        # Absent attribute reads as zero, so a finding from an older run,
        # or from a connector that does not publish it, behaves exactly as
        # before rather than being declined on a number nobody supplied.
        unexamined = finding.attributes.get("unexamined", "")
        if unexamined.isdigit() and int(unexamined) > 0:
            declined.append(
                "a suite that did not finish running: %s test file(s) could "
                "not be collected, so the measured total is not a total"
                % unexamined)
            continue
        path = _resolve(root, finding)
        line_no = finding.evidence.line_start
        if path is None or not line_no:
            declined.append("a claim whose file could not be resolved")
            continue

        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        if line_no > len(lines):
            declined.append("a claim past the end of its file")
            continue
        offset = sum(len(line) for line in lines[:line_no - 1])
        here = [m for m in _TEST_COUNT_CLAIM_RE.finditer(lines[line_no - 1])
                if m.group(1) == documented]
        if len(here) != 1:
            # Two claims of the same number on one line, or none: either way
            # there is no single span this finding names.
            declined.append("a line whose claim is not unique")
            continue
        match = here[0]
        start, end = offset + match.start(1), offset + match.end(1)
        claim_at = offset + match.start()
        claim_ends = offset + match.end()
        if claim_shape(claim_context(text, claim_at)) is not None:
            declined.append("a claim that is not about this suite")
            continue

        # THE WRITABILITY DECISION IS RE-DERIVED HERE, AND FROM THIS FILE.
        #
        # `finding.attributes["writable"]` was decided during the workup,
        # about the text as it was then and about the path the scan walked.
        # Two things can have changed by the time this runs, and both were
        # found by pointing an adversary at it rather than by reading it.
        #
        # The text. A repository's own test suite runs during the workup --
        # the tool starts it -- so a test that rewrites a document executes
        # inside the window between the reading and the writing. Re-running
        # `claim_shape` above is not enough: that predicate answers "is this
        # a claim about the current suite at all", which is the REPORTING
        # question. The one that authorises a write is this one, and it was
        # never re-asked. A live sentence replaced mid-run by a dated one
        # passes claim_shape and is exactly the sentence a machine must not
        # edit.
        #
        # The path. `_resolve` follows symlinks, correctly, because the
        # question is which file the bytes land in. But the name the
        # workup judged was the one it walked, and `why_not_writable` opens
        # by asking whether the FILENAME is a current-state document. Judge
        # `README.md`, write through the link, and a file whose own name the
        # same rule would have refused gets rewritten -- while the finding
        # names a path whose history will show no change.
        #
        # So: the resolved file's real name, and the text as it is now.
        stale = why_not_writable(
            path.name,
            text[max(0, claim_at - _WRITABILITY_LOOKBACK):claim_at],
            text[claim_ends:claim_ends + _WRITABILITY_LOOKBACK],
            # Re-derived from the file's own head at write time, like every
            # other half of this verdict.
            text)
        if stale is not None:
            declined.append(stale)
            continue

        meant = text[:start] + collected + text[end:]
        path.write_text(meant, encoding="utf-8")

        # Two checks, and they are deliberately not three. A first draft
        # also compared the whole file against what was meant and compared
        # the length delta against the digits. Both were redundant with
        # these, which mutation testing showed by killing neither: every
        # failure one caught, another caught too. Two guards that cannot
        # each be made to fail alone are one guard and some decoration.
        written = path.read_text(encoding="utf-8")
        after_lines = written.splitlines()
        line_now = after_lines[line_no - 1] if line_no <= len(after_lines) else ""
        if not any(m.group(1) == collected
                   for m in _TEST_COUNT_CLAIM_RE.finditer(line_now)):
            # The write did not land, or it landed somewhere other than the
            # span this finding named.
            raise RemedyFailed(
                f"{path}:{line_no}: after writing, the claim does not read {collected}")
        if written[:start] != text[:start] or written[start + len(collected):] != text[end:]:
            # Everything outside the number is the author's, byte for byte.
            raise RemedyFailed(f"{path}: text outside the claim changed")
        changed += 1

    if changed:
        note = f"{changed} documented test count(s) rewritten to the measured collected count"
        if declined:
            note += "; left for a human: " + ", ".join(sorted(set(declined)))
    else:
        note = ""
    return changed, note


#: The block a repository can hand the tool to maintain. Inside it, the
#: number is the tool's; outside it, every word belongs to whoever wrote it.
COUNT_BLOCK_OPEN = "<!-- ghost_buster:test-count -->"
COUNT_BLOCK_CLOSE = "<!-- /ghost_buster:test-count -->"
_COUNT_BLOCK = re.compile(
    re.escape(COUNT_BLOCK_OPEN) + r"(.*?)" + re.escape(COUNT_BLOCK_CLOSE), re.S)


def _remedy_count_block(root: Path, files: Sequence[Path],
                        findings: Sequence[Finding]) -> tuple[int, str]:
    """Maintain the test count inside a block the repository handed over.

    WHY A BLOCK, WHEN THERE IS ALREADY A REMEDY FOR THIS (v1.7.0)

    The doc-count remedy rewrites a number inside somebody's prose, and
    prose is why it has six refusals, five claim shapes and a measured
    precision it had to earn. Of 65 candidate claims in the library, it
    accepts none of them, and that is the correct answer: every one is a
    count of another project, a single test file, or a moment in the past.

    A sentence cannot say "this number is the tool's to keep current". A
    block can. Inside these markers the number is maintained, outside them
    nothing is touched, and the distinction is a fact about the document
    rather than a judgement about English.

    THE TOOL NEVER ADDS THE BLOCK ITSELF

    A repository opts in by writing the markers once. A scanner that
    inserts its own markup into somebody's README uninvited has decided
    something that was not its to decide, and the first thing this remedy
    would then do is put markup into 38 repositories nobody asked to change.
    No block, no cut.

    WHAT THE MARKERS HAND OVER (v1.7.1)

    The COUNT, and nothing else. The first version replaced the whole region
    between the markers, which is a different promise and a worse one: a
    repository that wrote a sentence inside the block -- explaining why the
    suite is split the way it is, say -- had that sentence deleted on the
    next operation.

    So the number is rewritten in place and every other byte in the block is
    the author's. A block with no count in it and nothing else in it is a
    repository asking for the sentence to be written, and gets it. A block
    with something that is not a count in it is left alone and said so. A
    block with two counts is left alone: there is no single span to name.

    THE VERIFICATION THAT CAN FAIL

    After writing, the file is read back: the block must hold the measured
    number, and every byte outside THE DIGITS must be unchanged. The earlier
    version checked the bytes outside the block, which was sound and could
    not fail for the defect above -- the loss was inside.
    """
    measured = next((f.attributes.get("collected") for f in findings
                     if f.detector == "doc_count_contradicted_by_run"
                     and f.attributes.get("collected")
                     and f.attributes.get("collected") == f.attributes.get("passed")), None)
    if not measured:
        return 0, ""

    changed = 0
    declined: List[str] = []
    for path in sorted(p for p in files if p.suffix.lower() == ".md"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        match = _COUNT_BLOCK.search(text)
        if match is None:
            continue
        escapes = outside_the_patient(path, root)
        if escapes is not None:
            # THE HOLE THE FIRST FIX MISSED (v1.7.2)
            #
            # 1.7.1 put a containment guard on the annotation writer and on
            # the path a finding resolves to, and left this one: the block
            # remedy takes its paths straight from the corpus and writes to
            # them. A README that is a symlink out of the repository, with a
            # maintained block in it, still carried the write outside.
            #
            # The first fix was tested with the case that found it. The case
            # had no block in it, so the case passed and the CLASS was still
            # open -- which is why the test below runs every writer over one
            # world rather than each writer over its own.
            declined.append(escapes)
            continue
        if _DATED_DOCUMENT.search(path.name):
            # The prose remedy refuses a dated or versioned document by name,
            # on the reasoning that such a document records a moment and its
            # numbers are correct as written. This remedy applied the same
            # tool to every markdown file carrying the markers and performed
            # no document check at all, so one repository could get two
            # different answers to "may a machine update this number",
            # decided by which mechanism happened to reach it. The markers
            # are consent to maintain a count; they are not consent to
            # falsify a record of a named day.
            declined.append("a dated or versioned document")
            continue

        body = match.group(1)
        claims = list(_TEST_COUNT_CLAIM_RE.finditer(body))

        if not claims:
            if body.strip():
                # Something is in there that is not a count. Whatever it is,
                # it is not this remedy's, and replacing the block would
                # delete it.
                declined.append("a block holding something other than a count")
                continue
            # An empty block is a repository saying "fill this in". Writing
            # the sentence into it destroys nothing.
            meant = text[:match.start(1)] + f"\n{measured} tests, all passing.\n" \
                + text[match.end(1):]
            start = end = None
        elif len(claims) > 1:
            declined.append("a block whose count is not unique")
            continue
        else:
            claim = claims[0]
            start = match.start(1) + claim.start(1)
            end = match.start(1) + claim.end(1)
            meant = text[:start] + measured + text[end:]

        if meant == text:
            continue          # already current; not a cut
        path.write_text(meant, encoding="utf-8")

        written = path.read_text(encoding="utf-8")
        again = _COUNT_BLOCK.search(written)
        if again is None or measured not in again.group(1):
            raise RemedyFailed(f"{path}: the block does not hold {measured} after writing")
        if start is None:
            # The block was empty and is now the canonical sentence. What has
            # to hold is that nothing outside the block moved.
            if written[:again.start(1)] != text[:match.start(1)] or \
                    written[again.end(1):] != text[match.end(1):]:
                raise RemedyFailed(f"{path}: text outside the block changed")
        elif written[:start] != text[:start] or \
                written[start + len(measured):] != text[end:]:
            # EVERYTHING EXCEPT THE DIGITS, BYTE FOR BYTE.
            #
            # The check this replaces compared the bytes OUTSIDE the block and
            # was sound, and it could not fail for the defect that mattered:
            # the remedy replaced the whole block body, so a sentence the
            # author had written inside the markers was deleted -- outside the
            # block nothing had moved, the verification passed, and three
            # lines of somebody's writing were gone. The verification was not
            # weak. It was answering a different question from the one the
            # invariant needed, which is the failure this comment exists to
            # stop coming back.
            raise RemedyFailed(f"{path}: text outside the count changed")
        changed += 1

    if not changed:
        return 0, ""
    note = (f"{changed} maintained test-count block(s) set to {measured}, "
            "the number this run measured")
    if declined:
        note += "; left alone: " + ", ".join(sorted(set(declined)))
    return changed, note


REMEDIES: Dict[str, Callable[[Path, Sequence[Path], Sequence[Finding]], tuple[int, str]]] = {
    "annotate": _remedy_annotate,
    "doc_counts": _remedy_doc_counts,
    "count_block": _remedy_count_block,
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
