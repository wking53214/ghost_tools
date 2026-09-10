"""ledger.py -- what ghost_buster remembers between runs.

WHY A LEDGER AND NOT A BIGGER BASELINE
--------------------------------------
The baseline answers one question: "is this finding present right now,
and have I agreed to stop hearing about it?" It is a set of ids. It has
no notion of time, so three facts that matter are unsayable in it:

  * A finding that was fixed and came back looks exactly like a finding
    that is merely new.
  * A finding open for ninety days looks exactly like one opened today.
  * A check that has not run against this repository in forty runs looks
    exactly like a check that ran and found nothing.

The last one is not hypothetical. Measured 2026-09-10 on a pediatric
deterioration engine: a scan reported 34 findings, exit 1, looked like a
finished audit, and never said that test status had gone unexamined --
where five clinical missed detections were sitting behind skips. The
tool had no way to notice its own blind spot because it remembered
nothing about its own past behaviour.

WHAT THIS LEDGER WILL NOT DO
----------------------------
It never suppresses anything, and it never tunes a threshold. Memory
that removes signal is a self-tuning suppressor, and every self-tuning
suppressor shares one gradient: fewer findings looks like success, so it
walks itself to silence. This module is strictly additive. It can raise
a severity (a regression is worse than a first sighting) and it can emit
new findings. It cannot lower one, drop one, or decide on a human's
behalf.

WHAT IS RECORDED IS WHAT WAS FOUND, NOT WHAT WAS REPORTED
---------------------------------------------------------
Findings enter the ledger BEFORE the baseline diff. Accepting something
into the baseline changes what you are shown; it must not change what
the tool remembers, or `--accept` becomes a way to erase history --
the silence problem wearing a different hat.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "ledger"
SCHEMA_VERSION = 1

#: Runs kept in full. Older runs collapse into `totals` so the file stays
#: flat in git history instead of growing without bound -- a governance
#: record nobody wants to commit is a governance record nobody keeps.
MAX_RUNS_KEPT = 200

#: Consecutive runs before an undispositioned finding is called persistent.
PERSISTENT_AFTER = 10

#: Consecutive runs a check may be absent before it is called a blind spot.
BLIND_SPOT_AFTER = 5

#: Distinct disappear/reappear cycles before a finding is called flapping.
FLAPPING_AFTER = 3

# Check states. `RAN` is the only one that means the question was asked.
RAN = "ran"
DECLINED = "declined"          # the caller said --no-X
COULD_NOT_RUN = "could_not_run"  # no git, no tests, no gitleaks
NOT_RUN = "not_run"            # opt-in and not opted into (--mutate)

#: The states in which a check did NOT look at anything.
_DID_NOT_LOOK = frozenset({DECLINED, COULD_NOT_RUN, NOT_RUN})

#: How loud a blind spot is depends on WHY nobody looked, and getting this
#: wrong is how the whole feature becomes noise. --mutate is opt-in on
#: cost, so it is NOT_RUN on every repository of everyone who does not use
#: it: rating that MAJOR would put a permanent unfixable MAJOR in every
#: ledger, and a permanent unfixable MAJOR is how a tool teaches people to
#: stop reading it. Turning OFF a check that is on by default is the loud
#: case, because that is a choice someone made and can unmake.
_BLIND_SPOT_SEVERITY = {
    DECLINED: Severity.MAJOR,
    COULD_NOT_RUN: Severity.MINOR,
    NOT_RUN: Severity.INFORMATIONAL,
}

_SEVERITY_LADDER = [
    Severity.INFORMATIONAL, Severity.MINOR, Severity.MAJOR, Severity.CRITICAL,
]


def _escalate(severity: Severity) -> Severity:
    """One step up the ladder, capped. A thing you fixed that came back is
    worse than a thing you never fixed, but it is not automatically the
    worst thing in the repository."""
    try:
        i = _SEVERITY_LADDER.index(severity)
    except ValueError:
        return severity
    return _SEVERITY_LADDER[min(i + 1, len(_SEVERITY_LADDER) - 1)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _head_commit(root: Path) -> str:
    """Best effort. A repository is not required to use this tool, so a
    missing commit is recorded as empty rather than raising."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


@dataclass
class RunRecord:
    """One invocation of ghost_buster, and crucially what it did NOT do."""
    run_id: str
    at: str
    commit: str
    tool_version: str
    checks: Dict[str, str] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id, "at": self.at, "commit": self.commit,
            "tool_version": self.tool_version, "checks": dict(self.checks),
            "counts": dict(self.counts),
        }

    @staticmethod
    def from_dict(d: dict) -> "RunRecord":
        return RunRecord(
            run_id=str(d.get("run_id", "")), at=str(d.get("at", "")),
            commit=str(d.get("commit", "")), tool_version=str(d.get("tool_version", "")),
            checks={str(k): str(v) for k, v in (d.get("checks") or {}).items()},
            counts={str(k): int(v) for k, v in (d.get("counts") or {}).items()},
        )


@dataclass
class FindingHistory:
    """Everything the ledger knows about one finding id across time.

    `runs_seen` and `absences` are counters rather than a full run list:
    the whole point of the cap on run history is that this file must not
    grow without bound, and per-finding run lists would defeat it.
    """
    finding_id: str
    detector: str = ""
    file: str = ""
    summary: str = ""
    severity: str = ""
    first_seen: str = ""
    first_commit: str = ""
    last_seen: str = ""
    last_commit: str = ""
    runs_seen: int = 0
    consecutive: int = 0
    #: How many times this went away and came back. 1 is a regression;
    #: FLAPPING_AFTER or more is a detector nobody should trust yet.
    returns: int = 0
    #: True when the most recent run did not find it. Kept explicitly so a
    #: return is detectable without replaying the whole run list.
    absent_last_run: bool = False
    dispositions: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "detector": self.detector, "file": self.file, "summary": self.summary,
            "severity": self.severity, "first_seen": self.first_seen,
            "first_commit": self.first_commit, "last_seen": self.last_seen,
            "last_commit": self.last_commit, "runs_seen": self.runs_seen,
            "consecutive": self.consecutive, "returns": self.returns,
            "absent_last_run": self.absent_last_run,
            "dispositions": list(self.dispositions),
        }

    @staticmethod
    def from_dict(fid: str, d: dict) -> "FindingHistory":
        return FindingHistory(
            finding_id=fid,
            detector=str(d.get("detector", "")), file=str(d.get("file", "")),
            summary=str(d.get("summary", "")), severity=str(d.get("severity", "")),
            first_seen=str(d.get("first_seen", "")), first_commit=str(d.get("first_commit", "")),
            last_seen=str(d.get("last_seen", "")), last_commit=str(d.get("last_commit", "")),
            runs_seen=int(d.get("runs_seen", 0)), consecutive=int(d.get("consecutive", 0)),
            returns=int(d.get("returns", 0)),
            absent_last_run=bool(d.get("absent_last_run", False)),
            dispositions=list(d.get("dispositions") or []),
        )


class LedgerError(ValueError):
    """A ledger that cannot be read is a usage error, never a silent empty
    one. Starting fresh on a corrupt file would erase the record and
    report a healthy history that does not exist."""


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.runs: List[RunRecord] = []
        self.findings: Dict[str, FindingHistory] = {}
        #: Aggregate counters for runs that have aged out of `runs`.
        self.totals: Dict[str, int] = {"runs": 0}
        self._existed = self.path.exists()
        if self._existed:
            self._load()

    @property
    def existed(self) -> bool:
        """False on the very first run against a repository. The caller
        says so out loud rather than reporting an empty history as if it
        were a clean one."""
        return self._existed

    @property
    def run_count(self) -> int:
        return int(self.totals.get("runs", 0))

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise LedgerError(f"{self.path}: {type(e).__name__}: {e}") from e
        if not isinstance(raw, dict):
            raise LedgerError(f"{self.path}: not a ghost_buster ledger (got {type(raw).__name__})")
        version = raw.get("schema")
        if version != SCHEMA_VERSION:
            raise LedgerError(
                f"{self.path}: ledger schema {version!r}, this ghost_buster writes "
                f"{SCHEMA_VERSION}. Refusing to read it rather than guess at the "
                f"difference and silently lose history."
            )
        self.runs = [RunRecord.from_dict(r) for r in (raw.get("runs") or [])]
        self.findings = {
            str(k): FindingHistory.from_dict(str(k), v)
            for k, v in (raw.get("findings") or {}).items() if isinstance(v, dict)
        }
        self.totals = {str(k): int(v) for k, v in (raw.get("totals") or {"runs": 0}).items()}

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "totals": dict(self.totals),
            "runs": [r.to_dict() for r in self.runs],
            "findings": {k: v.to_dict() for k, v in sorted(self.findings.items())},
        }

    def save(self) -> None:
        """Atomic. An interrupted run must not leave a half-written
        governance record; the old one is strictly better than a corrupt
        one, because a corrupt one is refused on the next read and the
        history is gone either way."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".ghost_ledger.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---------------------------------------------------------------- record

    def record(
        self, findings: Sequence[Finding], *, checks: Dict[str, str],
        commit: str, tool_version: str, at: Optional[str] = None,
    ) -> RunRecord:
        """Fold one run into memory. `findings` is everything FOUND, before
        the baseline diff -- see the module docstring on why."""
        at = at or _now()
        run = RunRecord(
            run_id=f"{at}:{commit[:12]}" if commit else at,
            at=at, commit=commit, tool_version=tool_version, checks=dict(checks),
            counts={"found": len(findings)},
        )

        # The ledger never remembers its own output. Without this, a
        # `regressed_finding` becomes a finding that can itself regress,
        # and history compounds on history -- the same trap correlate.py
        # closes by refusing to correlate correlations.
        findings = [f for f in findings if f.detector != DETECTOR]
        run.counts["found"] = len(findings)

        seen_now = {f.id for f in findings}
        by_id = {f.id: f for f in findings}

        for fid, hist in self.findings.items():
            if fid in seen_now:
                continue
            # Absent this run. Streak breaks; the absence is what makes a
            # later sighting a RETURN rather than a first sighting.
            hist.consecutive = 0
            hist.absent_last_run = True

        for fid in sorted(seen_now):
            f = by_id[fid]
            hist = self.findings.get(fid)
            if hist is None:
                hist = FindingHistory(finding_id=fid, first_seen=at, first_commit=commit)
                self.findings[fid] = hist
            elif hist.absent_last_run:
                # It was gone and it is back. This is the fact the baseline
                # structurally cannot hold: to a set of ids, a return and a
                # first sighting are the same event.
                hist.returns += 1
            hist.detector = f.detector
            hist.file = f.evidence.file
            hist.summary = f.summary
            hist.severity = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
            hist.last_seen = at
            hist.last_commit = commit
            hist.runs_seen += 1
            hist.consecutive += 1
            hist.absent_last_run = False
            if f.disposition:
                hist.dispositions.append({
                    "at": at, "state": str(f.disposition),
                    "note": f.disposition_note or "",
                })

        self.runs.append(run)
        self.totals["runs"] = self.run_count + 1
        if len(self.runs) > MAX_RUNS_KEPT:
            # Aged-out runs survive as counters, never as nothing: the
            # blind-spot streak below counts over kept runs, so the cap is
            # also the ceiling on how far back a streak can be proven.
            for old in self.runs[:-MAX_RUNS_KEPT]:
                for name, state in old.checks.items():
                    key = f"check.{name}.{state}"
                    self.totals[key] = self.totals.get(key, 0) + 1
            self.runs = self.runs[-MAX_RUNS_KEPT:]
        return run

    # ------------------------------------------------------------- derive

    def _blind_spot_streaks(self) -> Dict[str, int]:
        """For each check, how many runs in a row, ending with the most
        recent, nobody actually looked. A check that ran breaks its streak."""
        streaks: Dict[str, int] = {}
        names = {n for r in self.runs for n in r.checks}
        for name in names:
            streak = 0
            for run in reversed(self.runs):
                state = run.checks.get(name)
                if state is None or state == RAN:
                    break
                streak += 1
            streaks[name] = streak
        return streaks

    def derive(self, findings: Sequence[Finding]) -> List[Finding]:
        """The four things a single run cannot know. Purely additive: every
        return is a NEW finding. Nothing here removes or downgrades."""
        out: List[Finding] = []
        present = {f.id: f for f in findings}

        for fid, hist in sorted(self.findings.items()):
            if fid not in present:
                continue
            f = present[fid]

            if hist.returns >= FLAPPING_AFTER:
                out.append(self._finding(
                    "flapping_finding", Severity.MAJOR, f,
                    f"{hist.detector} finding in {hist.file} has come and gone "
                    f"{hist.returns} times across {self.run_count} run(s)",
                    "A finding that keeps reappearing is usually a detector that is not "
                    "deterministic, and occasionally a real intermittent defect. Either "
                    "way the detector's verdict on this file cannot be trusted until the "
                    "cause is known -- do not baseline it, diagnose it.",
                    {"returns": str(hist.returns), "runs_seen": str(hist.runs_seen)},
                ))
            elif hist.returns >= 1:
                out.append(self._finding(
                    "regressed_finding", _escalate(f.severity), f,
                    f"{hist.detector} finding in {hist.file} was fixed and has come back "
                    f"(first seen {hist.first_seen}, gone, now back)",
                    "A defect that returns is worse than one never fixed: something in the "
                    "process reintroduced it, and nothing prevented that. Severity is one "
                    "step above the underlying finding for exactly that reason. The "
                    "baseline cannot see this -- to a set of ids, a return and a first "
                    "sighting are the same event.",
                    {"returns": str(hist.returns), "first_seen": hist.first_seen},
                ))

            if (hist.consecutive >= PERSISTENT_AFTER and not hist.dispositions):
                out.append(self._finding(
                    "persistent_finding", Severity.MINOR, f,
                    f"{hist.detector} finding in {hist.file} has been open for "
                    f"{hist.consecutive} consecutive run(s) with no decision recorded",
                    "Not a claim that it is wrong -- a claim that nobody has said either "
                    "way. Fix it, or record the decision to keep it with ghost-triage so "
                    "the reason survives. Ageing out of attention without a decision is "
                    "how a known problem becomes an unknown one.",
                    {"consecutive": str(hist.consecutive), "first_seen": hist.first_seen},
                ))

        for name, streak in sorted(self._blind_spot_streaks().items()):
            if streak < BLIND_SPOT_AFTER:
                continue
            last = self.runs[-1].checks.get(name, NOT_RUN)
            out.append(Finding(
                detector=DETECTOR, category=Category.HISTORY, layer=Layer.MECHANICAL,
                severity=_BLIND_SPOT_SEVERITY.get(last, Severity.MINOR),
                status=Status.CONFIRMED,
                summary=(f"the '{name}' check has not actually run here in {streak} "
                         f"consecutive run(s) (most recent state: {last})"),
                evidence=Evidence(file=str(self.path)),
                detail=(
                    "A check that never runs and says nothing is indistinguishable in the "
                    "output from a check that ran and found nothing. Measured 2026-09-10 on "
                    "a pediatric deterioration engine: a scan reported 34 findings and exit "
                    "1, looked like a finished audit, and never mentioned that test status "
                    "had gone unexamined -- five clinical missed detections were sitting "
                    "behind skips it would have rated MAJOR. This finding is the tool "
                    "noticing its own blind spot. Either run the check or record why not. "
                    "Severity follows the reason: declining a check that is on by default "
                    "is a choice someone made and can unmake (MAJOR); an environment that "
                    "cannot run it is a gap but not a decision (MINOR); a check that is "
                    "opt-in by design was never promised (INFORMATIONAL)."
                ),
                attributes={"check": name, "streak": str(streak), "state": last},
            ))
        return out

    def _finding(self, kind, severity, source, summary, detail, attributes) -> Finding:
        attrs = {"kind": kind, "source_finding": source.id, "source_detector": source.detector}
        attrs.update(attributes)
        return Finding(
            detector=DETECTOR, category=Category.HISTORY, layer=Layer.MECHANICAL,
            severity=severity, status=Status.CONFIRMED,
            summary=f"{kind}: {summary}",
            evidence=Evidence(file=source.evidence.file, line_start=source.evidence.line_start,
                              line_end=source.evidence.line_end),
            detail=detail, attributes=attrs,
        )


def render_report(ledger: "Ledger", derived: Sequence[Finding]) -> str:
    """One line, on the same channel as every other check's line."""
    if not ledger.existed:
        return (f"ghost_buster: ledger started at {ledger.path} "
                f"(first run here, so no history to compare against yet)")
    kinds = {}
    for f in derived:
        k = f.attributes.get("kind") or ("blind_spot" if f.attributes.get("check") else "history")
        kinds[k] = kinds.get(k, 0) + 1
    if not kinds:
        return (f"ghost_buster: ledger has {ledger.run_count} run(s) of history, "
                f"nothing new about them")
    detail = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
    return f"ghost_buster: ledger ({ledger.run_count} run(s) of history) found {detail}"
