# Adapted from wking53214/content-polish-pipeline, branch
# claude/ats-oscillation-detection-qs1k74, commit
# b0740bf3d827a30c339c5f54e1a14432548d2689 (2026-08-30). See PROVENANCE.md
# at the ghost_tools root for what changed in this copy.
"""Oscillation detector: identifies repeated pipeline outputs.

Tracks a bounded history of observed strings and signals when the same
value recurs. Replaces the unbounded ``set`` of response hashes
``ContentPolishPipeline.execute`` used to carry inline: same purpose
(stop a retry loop from cycling on the same rejected output forever),
extracted into a reusable, independently testable class with a bound on
memory.

DELIBERATE DEVIATION FROM THE SOURCE BRANCH: no normalization here.
The source's ``observe()`` lowercased and stripped its input before
comparing. ``ContentPolishPipeline`` already normalizes a response
(``_normalize``, whitespace-collapse only) before this detector ever
sees it, so adding a second, case-insensitive normalization on top would
make "The flag is removed." and "the flag is removed." count as the same
output -- a real behavior change, not a refactor, and one the pipeline's
existing tests were never written to expect. This detector compares
exactly what it is given; normalization is the caller's decision.
"""

from collections import deque


class OscillationDetector:
    """Detect a repeated value within a bounded history.

    Args:
        max_history: how many prior observations to retain. Must be >= 1.
            Once the limit is reached, the oldest observation is dropped
            when a new one is added. ContentPolishPipeline's own retry
            loop never exceeds a handful of iterations, so the bound is
            headroom for a caller with a larger max_attempts, not a
            behavior change at the pipeline's current scale.

    Raises:
        ValueError: if ``max_history`` is less than 1.
    """

    def __init__(self, max_history: int = 32):
        if max_history < 1:
            raise ValueError(f"max_history must be >= 1, got {max_history}")
        self.history: deque[str] = deque(maxlen=max_history)

    def observe(self, value: str) -> bool:
        """Record `value` and report whether it was already in history.

        Returns True if `value` is an exact match for something already
        observed (before this call), False otherwise. Either way, `value`
        is appended to history afterward.
        """
        repeated = value in self.history
        self.history.append(value)
        return repeated

    def reset(self) -> None:
        """Clear all history. ContentPolishPipeline calls this once per
        `execute()`, so repetition is judged within one proposal's retry
        attempts, never across separate calls."""
        self.history.clear()

    def get_history(self) -> list[str]:
        """Return a snapshot of current history (oldest first)."""
        return list(self.history)
