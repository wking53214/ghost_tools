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


def render_triage_report(findings: List[Finding], title: str = "Ghost Findings, Awaiting Triage") -> str:
    """The other report: EVERYTHING ghost_buster found, for the person doing
    the triage, most severe first, grouped by file so one file's problems
    read together.

    This is deliberately not the document mode. It says on its face that
    nothing in it has been reviewed, so it can never be mistaken for a
    design decision. Findings that already carry a disposition are listed
    in a closing section with the decision, so a re-run report shows what
    was decided and what is still open.

    A `vacuous_check` finding carries its proof (the mutation the test
    survived) in `detail`; it is rendered as its own line because a reader
    who wants to reproduce the finding needs exactly that sentence.
    """
    severity_order = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2, Severity.INFORMATIONAL: 3}
    items = list(findings)
    open_items = [f for f in items if not f.disposition]
    decided = [f for f in items if f.disposition]

    lines = [f"## {title}", ""]
    lines.append(
        "_Every entry below was produced by ghost_buster and has NOT been "
        "reviewed by a human. It is a list of things to look at, not a list "
        "of defects. Record decisions with `ghost_triage`._"
    )
    lines.append("")

    # Summary table by severity and detector.
    counts: Dict[Severity, int] = defaultdict(int)
    by_detector: Dict[str, int] = defaultdict(int)
    for f in open_items:
        counts[f.severity] += 1
        by_detector[f.detector] += 1
    lines.append(f"**{len(open_items)} open**, {len(decided)} decided.")
    lines.append("")
    lines.append("| severity | count |")
    lines.append("|---|---|")
    for sev in sorted(counts, key=lambda s: severity_order[s]):
        lines.append(f"| {sev.value} | {counts[sev]} |")
    lines.append("")
    lines.append("| detector | count |")
    lines.append("|---|---|")
    for det, n in sorted(by_detector.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {det} | {n} |")
    lines.append("")

    # Open findings by file, most severe file first.
    by_file: Dict[str, List[Finding]] = defaultdict(list)
    for f in open_items:
        by_file[f.evidence.file].append(f)

    def file_rank(path: str) -> tuple:
        worst = min(severity_order[f.severity] for f in by_file[path])
        return (worst, -len(by_file[path]), path)

    for path in sorted(by_file, key=file_rank):
        entries = sorted(by_file[path], key=lambda f: (severity_order[f.severity], f.evidence.line_start or 0))
        lines.append(f"### `{path}` ({len(entries)})")
        lines.append("")
        for f in entries:
            line = f":{f.evidence.line_start}" if f.evidence.line_start else ""
            lines.append(f"- **[{f.severity.value}]** {f.summary} (`{f.detector}`, line{line}, `{f.id}`)")
            if f.category is Category.VACUOUS_CHECK and f.detail:
                lines.append(f"  *Proof:* {f.detail}")
            elif f.detail:
                lines.append(f"  {f.detail}")
        lines.append("")

    if decided:
        lines.append("### Already decided")
        lines.append("")
        for f in sorted(decided, key=lambda f: (f.disposition or "", severity_order[f.severity])):
            note = f" -- {f.disposition_note}" if f.disposition_note else ""
            lines.append(f"- `{f.disposition}` {f.summary} (`{f.id}`){note}")
        lines.append("")
    if not open_items:
        lines.append("_Nothing open._")
        lines.append("")
    return "\n".join(lines)
