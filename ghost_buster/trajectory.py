"""trajectory.py -- direction and surprise, over the ledger's own history.

WHAT THE LEDGER COULD NOT SAY
-----------------------------
Its four signals are all threshold counts on a single finding: this one
has returned three times, this one has been open ten runs, this check
has not run five times. Every one is about a finding. None is about the
REPOSITORY, and none has a rate.

So a scan reporting 340 findings could not distinguish a project that
has sat at 340 for two months from one that was at 180 a fortnight ago.
Those are opposite situations with identical reports.

Two signals fix that, both taken from a constant-velocity Kalman filter
already in service in a pediatric deterioration engine, where the same
question -- is this getting worse, and how fast -- is asked of vital
signs:

  velocity     smoothed rate of change, so one noisy run does not read
               as a trend and a real trend is not lost in noise.
  innovation   measurement minus prediction: how surprising this run is
               given the ones before it. A jump the trend did not
               anticipate is worth saying out loud even when the level
               is unremarkable.

WHY DENSITY AND NOT COUNTS
--------------------------
A repository that doubles in size roughly doubles its findings. Velocity
over raw counts would report healthy growth as decay, and the report
would be worse than silence because it would be confidently wrong. The
series is therefore findings per file scanned, which is flat when a
project grows at constant quality and rises only when quality actually
falls.

WHAT IT REFUSES TO ASSESS, AND WHY THAT IS THE POINT
----------------------------------------------------
A number is only comparable to another number measured the same way.
Three situations break that, and in each this module abstains rather
than producing a figure nobody should act on:

  * A run with no denominator. Ledgers written before `scanned` existed
    have none, and a density cannot be invented for them.
  * A run whose CHECK SET differs. `--no-tests` produces fewer findings
    with no change in quality whatsoever; comparing it to a full run
    measures the flags, not the code. The ledger already records exactly
    which checks ran, so this is decidable from evidence rather than
    guessed at.
  * Too few comparable runs to have a trend at all. The filter says so
    on the receipt line rather than emitting a finding, the same way the
    clinical adapter reports "warming up" instead of scoring.

That last refusal is why this module is additive in the ledger's sense.
It never suppresses, never tunes a threshold, and when it cannot see it
says so instead of reporting zero.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "trajectory"

#: Runs needed before the filter's prediction means anything. Below this it
#: is still learning the level and every innovation looks large.
WARMUP_RUNS = 3

#: Process and measurement noise, as FRACTIONS OF THE SERIES LEVEL rather
#: than absolute quantities.
#:
#: The first version used absolute constants tuned for a density around
#: 0.1-1 findings per file. Dogfooded on 2026-09-10 against a two-file
#: repository whose density was 5.5, the filter's variance collapsed and it
#: reported z=9.0 -- "a departure from its own trend" -- on a run where
#: nothing had changed at all. A density is a ratio and spans orders of
#: magnitude between a small package and a monorepo, so noise proportional
#: to the level is the only calibration that serves both. A signal that
#: cries surprise on an unchanged run teaches its reader to ignore it.
_Q_LEVEL_FRAC, _Q_RATE_FRAC, _R_FRAC = 0.02, 0.002, 0.08

#: Floor for the level used in that scaling, so a repository with no
#: findings at all does not divide the noise to nothing.
_MIN_LEVEL = 1e-3

#: Direction worth reporting, as a FRACTION OF THE CURRENT DENSITY per run.
#: 2% per run compounds to roughly a quarter over a dozen runs.
#:
#: This was an absolute 0.002 findings/file/run, which is the same mistake
#: the noise constants made: at a density of 0.0075 it is an enormous move
#: and at 5.5 it is nothing. Measured 2026-09-10, an ordinary one-finding
#: wobble in a two-file repository produced a velocity ten times the
#: absolute threshold and would have been announced as an improving trend.
ADVERSE_FRACTION = 0.02

#: Below this density the fraction is meaningless (a near-clean repository
#: would trip on a single finding), so an absolute floor applies as well.
_MIN_ADVERSE_RATE = 1e-5


def adverse_rate_for(density: float) -> float:
    """The rate that counts as direction at this density."""
    return max(abs(density) * ADVERSE_FRACTION, _MIN_ADVERSE_RATE)

#: How surprising a single run must be, as a z-score against the filter's
#: own prediction, before it is worth reporting on its own.
SURPRISE_Z = 3.0


def _noise_for(level: float) -> Tuple[float, float, float]:
    """Noise terms scaled to the series level. See the constants above."""
    scale = max(abs(level), _MIN_LEVEL)
    return (_Q_LEVEL_FRAC * scale) ** 2, (_Q_RATE_FRAC * scale) ** 2, (_R_FRAC * scale) ** 2


@dataclass
class _Kalman1D:
    """Constant-velocity filter over one series. Deterministic: an identical
    sequence of (value, dt) yields identical output, which matters because
    a nondeterministic signal is exactly what `flapping_finding` exists to
    catch and this module must never become one."""
    level: Optional[float] = None
    rate: float = 0.0
    p00: float = 1.0
    p01: float = 0.0
    p10: float = 0.0
    p11: float = 1.0

    def step(self, z: float, dt: float) -> Tuple[float, float]:
        """Fold in one measurement; return (innovation, |z-score|)."""
        if self.level is None:
            self.level = z
            scale = max(abs(z), _MIN_LEVEL)
            self.p00 = self.p11 = scale * scale
            return 0.0, 0.0

        q_level, q_rate, r = _noise_for(self.level)

        # Predict.
        self.level += self.rate * dt
        p00 = self.p00 + dt * (self.p10 + self.p01) + dt * dt * self.p11 + q_level
        p01 = self.p01 + dt * self.p11
        p10 = self.p10 + dt * self.p11
        p11 = self.p11 + q_rate

        # Update, over the full 2x2 so the rate is driven by the
        # level-rate cross term rather than an ad-hoc nudge.
        innovation = z - self.level
        s = p00 + r
        k0, k1 = p00 / s, p10 / s
        self.level += k0 * innovation
        self.rate += k1 * innovation
        self.p00 = (1.0 - k0) * p00
        self.p01 = (1.0 - k0) * p01
        self.p10 = p10 - k1 * p00
        self.p11 = p11 - k1 * p01
        return innovation, abs(innovation) / math.sqrt(s) if s > 0 else 0.0


def _ran(checks) -> frozenset:
    """The set of checks that actually ran, which is what makes two runs
    comparable. A run that declined a check measured something different."""
    return frozenset(name for name, state in (checks or {}).items() if state == "ran")


def _at(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Assessment:
    """What the filter concluded, including that it concluded nothing."""
    assessed: bool
    reason: str = ""
    comparable_runs: int = 0
    density: float = 0.0
    velocity: float = 0.0
    surprise_z: float = 0.0


def comparable(runs: Sequence, signature: frozenset) -> List:
    """Runs measured the same way as the current one, oldest first."""
    return [r for r in runs
            if _ran(r.checks) == signature and "scanned" in r.counts
            and r.counts.get("scanned", 0) > 0]


def assess(runs: Sequence) -> Assessment:
    """Direction and surprise over the run history, or a stated refusal."""
    if not runs:
        return Assessment(False, "no runs recorded")
    signature = _ran(runs[-1].checks)
    series = comparable(runs, signature)
    if len(series) < WARMUP_RUNS:
        return Assessment(
            False,
            f"{len(series)} comparable run(s), need {WARMUP_RUNS}",
            comparable_runs=len(series),
        )

    kf = _Kalman1D()
    previous: Optional[datetime] = None
    z_score = 0.0
    density = 0.0
    for run in series:
        # Primary findings only: the series is a measurement of the TREE,
        # and a correlation is a statement about two findings. Counting
        # derived findings here makes adding a connector look like the
        # code got worse. Runs written before `primary` existed have only
        # `found`, and using it keeps their point on the series rather
        # than dropping history to make the new rule look tidy.
        counted = run.counts.get("primary", run.counts["found"])
        density = counted / run.counts["scanned"]
        moment = _at(run.at)
        if previous is None or moment is None:
            dt = 1.0
        else:
            dt = max((moment - previous).total_seconds() / 86400.0, 1e-6)
            dt = min(dt, 30.0)
        if moment is not None:
            previous = moment
        _, z_score = kf.step(density, dt)

    return Assessment(True, "", len(series), density, kf.rate, z_score)


def derive(runs: Sequence, root_label: str = ".") -> List[Finding]:
    """Findings for a direction worth knowing about. Additive only."""
    result = assess(runs)
    if not result.assessed:
        return []

    out: List[Finding] = []
    evidence = Evidence(file=root_label)
    shared = {
        "comparable_runs": str(result.comparable_runs),
        "density": f"{result.density:.5f}",
        "velocity_per_run": f"{result.velocity:+.5f}",
    }

    threshold = adverse_rate_for(result.density)
    if result.velocity >= threshold:
        out.append(Finding(
            detector=DETECTOR, category=Category.HISTORY, layer=Layer.MECHANICAL,
            severity=Severity.MINOR, status=Status.CONFIRMED,
            summary=(f"finding density is rising: {result.velocity:+.4f} per file per run "
                     f"over {result.comparable_runs} comparable run(s)"),
            detail=(
                "Not a defect, and not a claim that any particular finding is "
                "wrong -- a claim about DIRECTION, which no single run can make. "
                "The series is findings per file scanned, so ordinary growth is "
                "already divided out: this rises only when findings are "
                "outpacing the code they are found in.\n\n"
                "Only runs measured the same way are compared. A run with a "
                "different set of checks, or none recorded, is excluded rather "
                "than folded in, because comparing them would measure the flags "
                "instead of the code."
            ),
            evidence=evidence, attributes=dict(shared, kind="deteriorating_trend"),
        ))
    elif result.velocity <= -threshold:
        out.append(Finding(
            detector=DETECTOR, category=Category.HISTORY, layer=Layer.MECHANICAL,
            severity=Severity.INFORMATIONAL, status=Status.CONFIRMED,
            summary=(f"finding density is falling: {result.velocity:+.4f} per file per run "
                     f"over {result.comparable_runs} comparable run(s)"),
            detail=(
                "Recorded because evidence of improvement is evidence. A tool "
                "that only ever reports decay teaches its reader that its "
                "silence is the good news, and silence is the one thing this "
                "project refuses to let carry meaning."
            ),
            evidence=evidence, attributes=dict(shared, kind="improving_trend"),
        ))

    if result.surprise_z >= SURPRISE_Z:
        out.append(Finding(
            detector=DETECTOR, category=Category.HISTORY, layer=Layer.MECHANICAL,
            severity=Severity.MINOR, status=Status.CONFIRMED,
            summary=(f"this run's finding density is a departure from its own trend "
                     f"(z={result.surprise_z:.1f})"),
            detail=(
                "The level may be unremarkable; what is remarkable is that the "
                "history did not predict it. A jump the trend did not anticipate "
                "usually means something changed in one commit rather than "
                "drifting -- a merge, a vendored tree, a detector newly able to "
                "see a file it could not parse before.\n\n"
                "Reported separately from direction because a repository can be "
                "improving steadily and still take one surprising step."
            ),
            evidence=evidence, attributes=dict(shared, kind="surprising_run",
                                               surprise_z=f"{result.surprise_z:.2f}"),
        ))
    return out


def render_report(runs: Sequence) -> str:
    """One line, on the same channel as every other check."""
    result = assess(runs)
    if not result.assessed:
        return f"ghost_buster: trajectory not yet assessable ({result.reason})"
    threshold = adverse_rate_for(result.density)
    direction = ("rising" if result.velocity >= threshold
                 else "falling" if result.velocity <= -threshold else "flat")
    return (f"ghost_buster: trajectory {direction} "
            f"({result.velocity:+.4f} findings/file/run, density "
            f"{result.density:.4f}, over {result.comparable_runs} comparable run(s))")
