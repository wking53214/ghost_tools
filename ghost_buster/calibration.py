"""The calibration record: what each detector was measured on, when, and
what the measurement changed.

`calibration.json` beside this module holds one record per detector and
per repository-level check. It is the "measured before built" principle
applied to the tool itself, in a form a skeptical reader can query rather
than a paragraph they have to find. A record whose corpus is null says so
in `disclosed`: a threshold set by convention is not a measurement.

    from ghost_buster.calibration import records
    records()["dead_end_call"]["after"]   # {'findings': 1}

Tests/test_calibration.py holds every registered detector to having a
record, and every record to naming something that exists.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

PATH = Path(__file__).with_name("calibration.json")

REQUIRED = ("name", "kind", "date", "corpus", "before", "after", "exclusions", "disclosed",
            "source", "reproduce")

#: What a `reproduce` block must name for somebody else to recompute the
#: number. A block whose `command` is null is a record that can be audited
#: for method and not recomputed, and it has to say why in `note`.
REPRODUCE_FIELDS = ("command", "tool_version", "corpus_manifest", "note")


def reproducible(record: dict) -> bool:
    """Whether an independent party could recompute this number.

    THE DISTINCTION THIS DRAWS

    "The repository records that this measurement occurred" and "the
    repository contains enough for somebody else to redo it" are different
    claims, and every record here made the first while the word
    calibration invited the second. A record is reproducible when it names
    the command, the tool version that ran it, and a corpus manifest
    pinning each repository to a commit. Anything less is a recorded
    assertion, which is worth keeping and worth labelling.

    Records written before 1.6.0 are the second kind and say so: their
    corpora were named in prose, and pinning them afterwards would mean
    inventing the commits.
    """
    block = record.get("reproduce") or {}
    return bool(block.get("command") and block.get("tool_version") and block.get("corpus_manifest"))


@lru_cache(maxsize=1)
def records() -> Dict[str, dict]:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    return {r["name"]: r for r in data["records"]}


def render(name: str) -> str:
    r = records()[name]
    lines = [f"{r['name']} ({r['kind']}): measured {r['date'] or 'never'} on {r['corpus'] or 'no corpus'}"]
    if r["before"] is not None:
        lines.append(f"  before: {json.dumps(r['before'])}")
    if r["after"] is not None:
        lines.append(f"  after:  {json.dumps(r['after'])}")
    block = r.get("reproduce") or {}
    if reproducible(r):
        pinned = len(block["corpus_manifest"])
        lines.append(f"  reproduce: {block['command']}")
        lines.append(f"    on ghost_buster {block['tool_version']}, "
                     f"{pinned} repositor{'y' if pinned == 1 else 'ies'} pinned by commit")
    else:
        lines.append(f"  reproduce: not reproducible from this repository. "
                     f"{block.get('note') or 'no reason recorded'}")
    for e in r["exclusions"]:
        lines.append(f"  excludes: {e}")
    for d in r["disclosed"]:
        lines.append(f"  disclosed: {d}")
    lines.append(f"  source: {r['source']}")
    return "\n".join(lines)
