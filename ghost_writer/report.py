"""report.py -- renders DISPOSITIONED findings into readable markdown.

THE TRIAGE GATE, ENFORCED HERE
----------------------------------
This is the structural addition the original ghost_buster -> ghost_writer
proposal didn't have: ghost_writer never reads ghost_buster's raw output.
It only reads findings a human has already looked at and marked
disposition="document" on schema.Finding. Everything else --
disposition="fix" (a real bug, goes to an issue tracker, not a doc),
disposition="suppress" (accepted debt, stays in the baseline), or no
disposition at all (not yet reviewed) -- is filtered out here, not
upstream, so a caller who forgets to filter still gets the right result
instead of silently documenting a bug as if it were a design decision.

Pure templating, no LLM call in this module -- generating a report from
already-structured, already-reviewed Finding data doesn't need judgment,
it needs formatting. The LLM-backed piece (proposing a specific text
correction to an existing doc, which DOES need judgment) is correct.py,
kept separate on purpose.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from ghost_buster.schema import Category, Finding, Severity

DOCUMENT_DISPOSITION = "document"


def dispositioned_for_documentation(findings: List[Finding]) -> List[Finding]:
    """The triage gate. The only findings ghost_writer will ever act on."""
    return [f for f in findings if f.disposition == DOCUMENT_DISPOSITION]


def render_ghost_report(findings: List[Finding], title: str = "Known Structural Ghosts") -> str:
    """Renders a markdown section suitable for dropping into a README or
    an ARCHITECTURE.md -- grouped by category, most severe first, every
    entry carrying its own evidence and the human's disposition note (the
    REASON this was documented rather than fixed, which is exactly the
    kind of context a stale doc usually lacks).
    """
    to_document = dispositioned_for_documentation(findings)
    if not to_document:
        return f"## {title}\n\n_None currently dispositioned for documentation._\n"

    severity_order = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2, Severity.INFORMATIONAL: 3}
    by_category: Dict[Category, List[Finding]] = defaultdict(list)
    for f in to_document:
        by_category[f.category].append(f)

    lines = [f"## {title}", ""]
    lines.append(
        "_Findings below were surfaced by ghost_buster and explicitly "
        "reviewed by a human, who decided documenting the current state "
        "was the right call rather than fixing it immediately. This "
        "section is generated -- see each entry's `id` to re-run "
        "ghost_buster and confirm it's still accurate before trusting it "
        "blindly on a later read._"
    )
    lines.append("")

    for category in sorted(by_category, key=lambda c: c.value):
        items = sorted(by_category[category], key=lambda f: severity_order[f.severity])
        lines.append(f"### {category.value.replace('_', ' ').title()}")
        lines.append("")
        for f in items:
            loc = f.evidence.file
            if f.evidence.line_start:
                loc += f":{f.evidence.line_start}"
            lines.append(f"- **{f.summary}** (`{loc}`, `{f.id}`, severity: {f.severity.value})")
            if f.detail:
                lines.append(f"  {f.detail}")
            if f.disposition_note:
                lines.append(f"  *Why documented, not fixed:* {f.disposition_note}")
            lines.append("")

    return "\n".join(lines)
