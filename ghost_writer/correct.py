"""correct.py -- proposes a targeted correction for one stale doc claim.

DELIBERATELY NARROW, NOT "REGENERATE THE README"
------------------------------------------------------
This is the second mode from the original design discussion: correcting
existing docs is a different operation from generating new ones, and a
full regeneration risks losing hard-won specificity a human wrote for a
reason (sentinel_os's own README "Known Limitations" section is the
concrete example that motivated this -- it names four specific, disclosed,
NOT-being-fixed gaps in careful, exact language; a blind regen from "here's
what the code does now" would very plausibly flatten that into something
vaguer). So this module proposes a MINIMAL, SPECIFIC replacement for one
claim, never a rewrite of the surrounding document.

NEVER AUTO-APPLIED
-----------------------
This returns a CorrectionProposal, a suggestion with evidence -- it does
not touch any file on disk. Applying it is a human decision, made outside
this module, every time. This is the same "discovery/proposal, not
silent action" posture ghost_buster's own semantic layer already has
(REASONED, never CONFIRMED, until a human says otherwise) -- deliberately
the same shape here, not a coincidence.

Reuses ghost_buster.semantic's ModelClient protocol and injection-fencing
helpers directly rather than reimplementing them -- the exact kind of
"two independent implementations of the same thing" this whole project
exists to catch elsewhere in a codebase. Not repeating it here.

THE QUALITY GATE (ghost_writer.polish)
--------------------------------------
This is the one place in ghost_writer that generates new text rather
than templating a human's own decision, so it is the one place that gets
a gate. Every response is checked before it becomes a proposal:

  - no first-person pronouns, in the replacement or the reasoning;
  - no hedging words (might, may, could, probably, ...), in either;
  - an evidence marker in the reasoning -- the reasoning has to point at
    something in the code summary, not just assert.

The empirical check is scoped to the reasoning on purpose: a minimal doc
replacement ("The flag can be repeated.") is not an empirical claim and
must not be pushed to carry evidence vocabulary it has no use for.

A response that fails is not discarded silently: the pipeline appends the
violations to the prompt (after the fenced untrusted block, never inside
it) and asks the model again, up to ``max_attempts`` in total. That loop
is the pipeline's; there is no second one here. Empty, malformed, or
client-failed responses are NOT retried: they stay the single-shot,
fail-closed paths they always were. When every attempt fails the gate the
result is the same as every other "no proposal" outcome: ``(None, report)``
with the violations in ``report.reason``.

report.py stays ungated. It renders a human's own triage note back to
them, and that note is allowed to say "I think."
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional

from ghost_buster.schema import Finding
from ghost_buster.semantic import ModelClient, SemanticRunReport, _run_json_check

from .polish import ContentPolishPipeline, EmpiricalValidationFilter

# Paid calls per proposal, at most. The vendored pipeline's own default is
# 5; three is the ceiling here because each retry is a real API call and a
# model that cannot produce a clean correction in three tries with the
# violations spelled out is not going to on the fifth.
DEFAULT_MAX_ATTEMPTS = 3

# Nothing here consumes the pipeline's HMAC payload_signature (a proposal
# carries the parsed fields, never the signed string), so this key exists
# only so the vendored pipeline does not log its "default signing key"
# warning on every proposal. Regenerated each process; nothing verifies it.
_SIGNING_KEY = secrets.token_bytes(32)


@dataclass
class CorrectionProposal:
    doc_path: str
    original_claim: str
    proposed_replacement: str
    reasoning: str
    confidence: float


_CORRECT_SYSTEM = (
    "You are a technical writer proposing a MINIMAL correction to one "
    "specific claim in a piece of documentation, given a summary of what "
    "the code actually does now. Propose the smallest replacement text "
    "that makes the claim accurate again. Do NOT rewrite surrounding "
    "context, do NOT remove caveats or disclosed limitations that are "
    "still true, and do NOT add new claims beyond what the code summary "
    "supports. If you are not confident a correction is warranted, say so "
    "via a low confidence value rather than guessing. Write the replacement "
    "and the reasoning in the third person, with no first-person pronouns "
    "and no hedging words; the reasoning must cite the specific evidence "
    "in the current code behavior that supports the replacement."
)

_CORRECT_FORMAT = (
    'Respond ONLY with valid JSON, no other text, wrapping your single '
    'proposal in a "findings" list of exactly one item (this shares its '
    'parsing contract with ghost_buster\'s own semantic checks -- see '
    '_run_json_check): '
    '{"findings": [{"proposed_replacement": "...", "reasoning": "...", '
    '"confidence": 0.0-1.0}]}'
)


class _NoProposal(Exception):
    """Raised inside the gateway when one attempt produced nothing a
    proposal can be shaped from: client error, malformed JSON, an empty
    findings list, or an item with no replacement. The pipeline treats a
    gateway exception as terminal, which is exactly the point -- these
    paths stay single-shot and fail closed, as they were before the gate."""


@dataclass
class _GateState:
    """Side channel between the pipeline, which only ever sees strings, and
    the structured item this module needs back. Written by the gateway on
    every attempt; read once the pipeline returns."""

    report: SemanticRunReport
    item: Dict[str, Any]
    reasoning: str = ""
    aborted: bool = False


class _ReasoningScopedEmpiricalFilter:
    """The pipeline validates one string per attempt, and the gateway hands
    it the replacement and the reasoning together so the pronoun and
    speculation filters cover both. This wrapper scopes the third filter to
    the reasoning of the same attempt (which the gateway recorded just
    before returning), so an evidence word in the replacement never excuses
    an unsupported reasoning, and a doc sentence is never rejected for
    lacking one."""

    def __init__(self, state: _GateState):
        self._inner = EmpiricalValidationFilter()
        self._state = state

    def passes(self, text: str) -> bool:
        return self._inner.passes(self._state.reasoning)

    is_clean = passes

    def violations(self, text: str) -> List[str]:
        return self._inner.violations(self._state.reasoning)


def propose_correction(
    client: ModelClient, doc_drift_finding: Finding, code_summary: str,
    *, max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> tuple[Optional[CorrectionProposal], SemanticRunReport]:
    """doc_drift_finding must be a Category.DOC_DRIFT finding (as produced
    by ghost_buster.semantic.detect_doc_drift) -- its `summary` carries the
    stale claim, its `evidence.file` the doc it came from. code_summary is
    the current, accurate description of what the code does, supplied by
    the caller (same reasoning as detect_doc_drift: this module does not
    go read the codebase itself, the caller already knows the current
    truth or wouldn't have flagged drift in the first place).

    max_attempts bounds the paid calls: the first, plus one retry per
    quality-gate rejection. Must be >= 1 (the pipeline raises otherwise).

    Synchronous, like every other caller in this package; the vendored
    pipeline is async, so the loop runs here. Not callable from inside an
    already-running event loop.
    """
    sections = {
        "stale_claim": doc_drift_finding.summary,
        "current_code_behavior": code_summary,
    }
    state = _GateState(report=SemanticRunReport(ran=False, reason="not called"), item={})

    async def gateway(task_and_format: str) -> str:
        # task_and_format is _CORRECT_FORMAT, plus the pipeline's
        # recalibration feedback after the first rejection. _run_json_check
        # places it after the fenced data block, so feedback never lands
        # inside the untrusted region and the fencing is rebuilt intact on
        # every attempt.
        raw_findings, state.report = _run_json_check(
            client, _CORRECT_SYSTEM, sections, task_and_format,
        )
        # propose_correction expects a single-object response, not a list --
        # reuse _run_json_check's fenced-call/fail-closed plumbing anyway by
        # asking for the same {"findings": [...]} shape and taking the first.
        item = raw_findings[0] if raw_findings and isinstance(raw_findings[0], dict) else {}
        replacement = item.get("proposed_replacement")
        if not replacement:
            state.aborted = True
            raise _NoProposal()
        state.item = item
        state.reasoning = str(item.get("reasoning", ""))
        return f"{replacement}\n{state.reasoning}"

    pipeline = ContentPolishPipeline(
        gateway, max_attempts=max_attempts, signing_key=_SIGNING_KEY,
    )
    pipeline.empirical_filter = _ReasoningScopedEmpiricalFilter(state)
    result = asyncio.run(pipeline.execute(_CORRECT_FORMAT))

    if result["execution_status"] != "SUCCESS":
        if state.aborted:
            # The pre-gate fail-closed outcomes, reported exactly as before.
            return None, state.report
        attempts = result["retry_attempts"]
        return None, replace(
            state.report,
            reason=(
                f"quality gate rejected {attempts} attempt(s): "
                + "; ".join(result["violations"])
            ),
        )

    item = state.item
    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        confidence = 0.5
    report = state.report
    if result["retry_attempts"] > 1:
        report = replace(
            report,
            reason=f"quality gate accepted attempt {result['retry_attempts']} of {max_attempts}",
        )
    return CorrectionProposal(
        doc_path=doc_drift_finding.evidence.file,
        original_claim=doc_drift_finding.summary,
        proposed_replacement=str(item.get("proposed_replacement")),
        reasoning=state.reasoning,
        confidence=float(confidence),
    ), report
