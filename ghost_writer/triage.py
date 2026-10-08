"""triage.py -- the human step between ghost_buster and ghost_writer, as a tool.

The README has always drawn the pipeline as

    ghost_buster --json  ->  HUMAN TRIAGE  ->  ghost_writer

and `Finding.disposition` has always said "set by the human triage step, see
triage.py". There was no triage.py. Dispositions had to be set by editing
JSON by hand, which nobody did, so ghost_writer's document mode had nothing
to render and the gate it enforces was a gate on an empty room.

This closes the loop. It reads a FindingSet JSON, records a disposition and
a note against finding ids, and writes the file back. Three dispositions,
matching the README:

    fix        a real defect; goes to the issue tracker, never into a doc
    suppress   accepted debt; `ghost_buster --accept` puts it in the baseline
    document   worth writing down as-is; ghost_writer renders it

Nothing here touches code, docs, or the baseline. It records a decision a
person made, with the reason, so the next reader knows who decided what and
why. Unknown ids are an error, not a silent no-op.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from ghost_buster.casefile import Casefile
from ghost_buster.schema import Finding, FindingSet

DISPOSITIONS = ("fix", "suppress", "document")


def apply_dispositions(
    findings: Iterable[Finding],
    decisions: Iterable[Tuple[str, str, str]],
) -> List[Finding]:
    """decisions: (finding id or unique id prefix, disposition, note).

    Returns the findings with dispositions applied. Raises ValueError for an
    id that matches nothing, matches more than one finding, or a disposition
    outside the three the pipeline knows.
    """
    items = list(findings)
    for ident, disposition, note in decisions:
        if disposition not in DISPOSITIONS:
            raise ValueError(f"unknown disposition {disposition!r}; expected one of {DISPOSITIONS}")
        matches = [f for f in items if f.id == ident or f.id.startswith(ident)]
        if not matches:
            raise ValueError(f"no finding matches id {ident!r}")
        if len(matches) > 1:
            raise ValueError(f"id {ident!r} is ambiguous: {', '.join(f.id for f in matches)}")
        matches[0].disposition = disposition
        matches[0].disposition_note = note
    return items


def pending(findings: Iterable[Finding]) -> List[Finding]:
    """Findings no human has dispositioned yet."""
    return [f for f in findings if not f.disposition]


def _parse_decision(text: str) -> Tuple[str, str, str]:
    """ID=DISPOSITION[:NOTE]"""
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"expected ID=DISPOSITION[:NOTE], got {text!r}")
    ident, rest = text.split("=", 1)
    disposition, _, note = rest.partition(":")
    return ident.strip(), disposition.strip(), note.strip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ghost_triage",
        description="record human dispositions on a ghost_buster FindingSet",
    )
    parser.add_argument("findings", type=Path, help="a FindingSet JSON file (from ghost_buster --json)")
    parser.add_argument(
        "--set", action="append", default=[], type=_parse_decision, metavar="ID=DISPOSITION[:NOTE]",
        help="record a decision; ID may be a unique prefix; DISPOSITION is fix, suppress or document",
    )
    parser.add_argument("--list", action="store_true", help="list findings still awaiting a decision")
    parser.add_argument("--out", type=Path, default=None, help="write to this file instead of in place")
    parser.add_argument(
        "--casefile", type=Path, default=None, metavar="PATH",
        help="also record each decision in this case file, so the next scan can show "
             "what happened the last time this kind of finding came up. Point every "
             "repository at one file and the surgeon learns across the library. "
             "Never hides a finding; only attaches history to it.",
    )
    args = parser.parse_args(argv)

    if not args.findings.is_file():
        print(f"error: {args.findings} is not a file", file=sys.stderr)
        return 2
    fs = FindingSet.from_json(args.findings.read_text(encoding="utf-8"))
    items = list(fs)

    if args.set:
        try:
            apply_dispositions(items, args.set)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        target = args.out or args.findings
        target.write_text(FindingSet(items).to_json(), encoding="utf-8")
        print(f"recorded {len(args.set)} decision(s) in {target}")
        if args.casefile:
            decided_ids = {ident for ident, _, _ in args.set}
            just_decided = [f for f in items if f.disposition
                            and any(f.id.startswith(i) for i in decided_ids)]
            casefile = Casefile(args.casefile)
            learned = casefile.record_dispositions(just_decided)
            casefile.save()
            print(f"case file {args.casefile}: {learned} lesson(s) added, {len(casefile)} total")

    if args.list or not args.set:
        waiting = pending(items)
        print(f"\n{len(waiting)} of {len(items)} finding(s) awaiting a decision\n")
        for f in waiting:
            loc = f.evidence.file + (f":{f.evidence.line_start}" if f.evidence.line_start else "")
            print(f"  {f.id}  [{f.severity.value:13s}] {f.detector:22s} {loc}")
            print(f"      {f.summary}")
        if waiting:
            print("\n  decide with: ghost_triage FINDINGS --set ID=fix|suppress|document:NOTE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
