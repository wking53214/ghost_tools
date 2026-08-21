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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ghost_buster.schema import Finding
from ghost_buster.semantic import ModelClient, SemanticRunReport, _run_json_check


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
    "via a low confidence value rather than guessing."
)

_CORRECT_FORMAT = (
    'Respond ONLY with valid JSON, no other text, wrapping your single '
    'proposal in a "findings" list of exactly one item (this shares its '
    'parsing contract with ghost_buster\'s own semantic checks -- see '
    '_run_json_check): '
    '{"findings": [{"proposed_replacement": "...", "reasoning": "...", '
    '"confidence": 0.0-1.0}]}'
)


def propose_correction(
    client: ModelClient, doc_drift_finding: Finding, code_summary: str,
) -> tuple[Optional[CorrectionProposal], SemanticRunReport]:
    """doc_drift_finding must be a Category.DOC_DRIFT finding (as produced
    by ghost_buster.semantic.detect_doc_drift) -- its `summary` carries the
    stale claim, its `evidence.file` the doc it came from. code_summary is
    the current, accurate description of what the code does, supplied by
    the caller (same reasoning as detect_doc_drift: this module does not
    go read the codebase itself, the caller already knows the current
    truth or wouldn't have flagged drift in the first place).
    """
    raw_findings, report = _run_json_check(
        client,
        _CORRECT_SYSTEM,
        {"stale_claim": doc_drift_finding.summary, "current_code_behavior": code_summary},
        _CORRECT_FORMAT,
    )
    # propose_correction expects a single-object response, not a list --
    # reuse _run_json_check's fenced-call/fail-closed plumbing anyway by
    # asking for the same {"findings": [...]} shape and taking the first.
    if not raw_findings:
        return None, report
    item = raw_findings[0] if isinstance(raw_findings[0], dict) else {}
    replacement = item.get("proposed_replacement")
    if not replacement:
        return None, report
    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        confidence = 0.5
    return CorrectionProposal(
        doc_path=doc_drift_finding.evidence.file,
        original_claim=doc_drift_finding.summary,
        proposed_replacement=str(replacement),
        reasoning=str(item.get("reasoning", "")),
        confidence=float(confidence),
    ), report
