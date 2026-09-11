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

REQUIRED = ("name", "kind", "date", "corpus", "before", "after", "exclusions", "disclosed", "source")


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
    for e in r["exclusions"]:
        lines.append(f"  excludes: {e}")
    for d in r["disclosed"]:
        lines.append(f"  disclosed: {d}")
    lines.append(f"  source: {r['source']}")
    return "\n".join(lines)
