"""Turn a Census into text, JSON, or a draft CENSUS.md entry.

The draft entry ends with the decision line left blank on purpose. The census
reports; the person decides, and an entry that decided for them would be the
one thing in the file not written by the person it describes.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

from .census import GRAVESTONE, LIVE, RETIRED_FULL, Census, External, Row

DECISION_PROMPT = (
    "Decision: (write at least one of PROMOTE, DEMOTE, ARCHIVE, "
    "or \"no change this cycle, because ...\")"
)
UNKNOWN = "?"


def _cell(value: Any) -> str:
    return UNKNOWN if value is None else str(value)


def _table_rows(rows: List[Row]) -> List[List[str]]:
    header = ["REPO", "LAST", "30D", "TOTAL", "BRANCH", "LIC", "CI", "README", "PINNED-BY", "HINT"]
    body = []
    for row in rows:
        f = row.facts
        body.append([
            f.name, _cell(f.last_commit), _cell(f.commits_30d), _cell(f.commits_total),
            _cell(f.branch), "yes" if f.has_license else "no", "yes" if f.has_ci else "no",
            f.readme, str(len(row.pinned_by)), row.hint,
        ])
    return [header] + body


def _format_table(table: List[List[str]]) -> List[str]:
    widths = [max(len(r[i]) for r in table) for i in range(len(table[0]))]
    return ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)).rstrip() for r in table]


def _counts(census: Census) -> Dict[str, int]:
    states = Counter(r.state for r in census.rows)
    return {"repos": len(census.rows), "live": states[LIVE],
            "gravestones": states[GRAVESTONE], "retired_but_full": states[RETIRED_FULL]}


def _flag_lines(census: Census) -> List[str]:
    return [f"  {r.facts.name}: {flag}" for r in census.rows for flag in r.flags]


def _external_note(item: External) -> str:
    return f"  [retired {item.retired_on}]" if item.retired_on else ""


def _external_lines(census: Census) -> List[str]:
    return [f"  {target} <- {', '.join(item.consumers)}{_external_note(item)}"
            for target, item in census.external.items()]


def text(census: Census) -> str:
    c = _counts(census)
    graveyard = "read" if census.graveyard_read else "NOT READ (folder missing), so no repo is marked retired"
    out = [f"Stack census {census.today}  ({census.parent})",
           f"{c['repos']} repos: {c['live']} live, {c['gravestones']} gravestones, "
           f"{c['retired_but_full']} retired but still full. Graveyard: {graveyard}.",
           "", *_format_table(_table_rows(census.rows))]
    flags = _flag_lines(census)
    out += ["", f"FLAGS ({len(flags)})", *(flags or ["  none"])]
    external = _external_lines(census)
    out += ["", "PINNED BUT NOT CLONED HERE (tier unknown unless retired)", *(external or ["  none"])]
    out += ["", "Hints are starting points, not tiers. A '?' means git could not say.",
            "Next: assign tiers, check promises, then end with a decision (see the entry draft)."]
    return "\n".join(out)


def as_dict(census: Census) -> Dict[str, Any]:
    rows = []
    for r in census.rows:
        f = r.facts
        rows.append({
            "repo": f.name, "state": r.state, "retired_on": r.retired_on or None,
            "last_commit": f.last_commit, "commits_30d": f.commits_30d,
            "commits_total": f.commits_total, "branch": f.branch,
            "license": f.has_license, "ci": f.has_ci, "readme": f.readme,
            "pinned_by": r.pinned_by, "hint": r.hint, "flags": r.flags,
            "pins": [{"target": p.target, "ref": p.ref, "kind": p.kind, "file": p.file}
                     for p in r.pins],
        })
    return {"date": census.today, "parent": census.parent, "counts": _counts(census),
            "graveyard_read": census.graveyard_read, "repos": rows,
            "pinned_not_cloned": {
                t: {"consumers": i.consumers, "retired_on": i.retired_on or None}
                for t, i in census.external.items()}}


def as_json(census: Census) -> str:
    return json.dumps(as_dict(census), indent=2, sort_keys=True)


def entry(census: Census) -> str:
    c = _counts(census)
    hints = Counter(r.hint for r in census.rows)
    flags = _flag_lines(census)
    lines = [f"## {census.today}", "",
             f"{c['repos']} repos: {c['live']} live, {c['gravestones']} gravestones.",
             "Hints: " + ", ".join(f"{n} {h}" for h, n in sorted(hints.items())) + ".",
             f"{len(flags)} flag(s):", *(flags or ["  none"]), "", DECISION_PROMPT]
    return "\n".join(lines)
