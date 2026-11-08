"""Put the facts, the pins and the Graveyard together, and say what they imply.

Everything here is a hint or a flag. The census assigns no tier: PRODUCT in
particular is a decision about what a repo means to promise, which no file
can show. The hints exist so the person deciding starts from facts.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List

from .facts import RepoFacts, gather
from .graveyard import Burials, read_graveyard
from .pins import NONE, TAG, Pin, scan_all

STALE_DAYS = 60
GRAVESTONE_MAX_FILES = 6

LIVE, GRAVESTONE, RETIRED_FULL = "live", "gravestone", "retired-but-full"
GRAVEYARD = "graveyard"
HINT_BURIED = "BURIED"
HINT_RETIRED_FULL = "RETIRED, CLONE NOT A GRAVESTONE"
HINT_LIBRARY = "LIBRARY or higher"
HINT_ARCHIVE = "ARCHIVE candidate"
HINT_LAB = "LAB or PRODUCT (not pinned; your call)"
HINT_GRAVEYARD = "GRAVEYARD (the record, not counted)"


@dataclass
class Row:
    facts: RepoFacts
    state: str
    retired_on: str
    pinned_by: List[str]
    pins: List[Pin]
    hint: str
    flags: List[str] = field(default_factory=list)


@dataclass
class External:
    """A repo that others pin but that has no clone here."""
    consumers: List[str]
    retired_on: str


@dataclass
class Census:
    parent: str
    today: str
    graveyard_read: bool
    rows: List[Row]
    external: Dict[str, External]


def find_repos(parent: Path) -> List[Path]:
    return sorted((p for p in parent.iterdir() if (p / ".git").exists()),
                  key=lambda p: p.name.casefold())


def _age_days(last_commit: str, today: date) -> int:
    try:
        return (today - date.fromisoformat(last_commit)).days
    except ValueError:
        return 0


def _state(facts: RepoFacts, retired_on: str, is_graveyard: bool) -> str:
    if is_graveyard:
        return GRAVEYARD
    if not retired_on:
        return LIVE
    return GRAVESTONE if facts.top_level_files <= GRAVESTONE_MAX_FILES else RETIRED_FULL


def _hint(state: str, pinned_by: List[str], facts: RepoFacts, today: date) -> str:
    if state == GRAVEYARD:
        return HINT_GRAVEYARD
    if state == GRAVESTONE:
        return HINT_BURIED
    if state == RETIRED_FULL:
        return HINT_RETIRED_FULL
    if pinned_by:
        return HINT_LIBRARY
    stale = facts.last_commit and _age_days(facts.last_commit, today) > STALE_DAYS
    return HINT_ARCHIVE if stale else HINT_LAB


def _inbound(all_pins: Dict[str, List[Pin]], names: Dict[str, str], burials: Burials):
    """Pins grouped by the clone they point at, plus the targets with no clone."""
    by_target: Dict[str, List[Pin]] = defaultdict(list)
    seen: Dict[str, tuple] = {}
    for pins in all_pins.values():
        for pin in pins:
            clone = names.get(pin.target.casefold())
            if clone:
                by_target[clone].append(pin)
            else:
                label, who = seen.setdefault(pin.target.casefold(), (pin.target, set()))
                who.add(pin.consumer)
    external = {label: External(sorted(who), burials.retired_on(label))
                for label, who in sorted(seen.values(), key=lambda v: v[0].casefold())}
    return by_target, external


def _retired_pin_flags(pins: List[Pin], burials: Burials) -> List[str]:
    """One flag per retired target, with every file and version that pins it."""
    grouped: Dict[str, dict] = {}
    for pin in pins:
        when = burials.retired_on(pin.target)
        if when:
            entry = grouped.setdefault(pin.target.casefold(), {
                "name": pin.target, "when": when, "files": set(), "refs": set()})
            entry["files"].add(pin.file)
            entry["refs"].add(pin.ref[:7] if pin.ref else "no version")
    return [f"pins {e['name']}, retired {e['when']} "
            f"({', '.join(sorted(e['files']))} @ {', '.join(sorted(e['refs']))})"
            for _, e in sorted(grouped.items())]


def _pin_flags(row: Row, inbound: List[Pin], burials: Burials) -> List[str]:
    flags = _retired_pin_flags(row.pins, burials)
    refs = sorted({p.ref[:7] if p.kind == "commit" else p.ref for p in inbound})
    if len(refs) > 1:
        flags.append(f"pinned at {len(refs)} different versions: {', '.join(r or 'none' for r in refs)}")
    if inbound and not any(p.kind == TAG for p in inbound):
        kinds = ", ".join(sorted({p.kind for p in inbound}))
        flags.append(f"never pinned by a tag (pinned by {kinds})")
    if any(p.kind == NONE for p in inbound):
        flags.append("pinned by at least one repo with no version")
    return flags


def _fact_flags(facts: RepoFacts, state: str) -> List[str]:
    flags = []
    if facts.branch and facts.branch.startswith("claude/"):
        flags.append(f"checked-out branch is {facts.branch}")
    if state == RETIRED_FULL:
        flags.append("listed as retired in the Graveyard but the clone still holds the repo")
    if state == LIVE and not facts.has_license:
        flags.append("no license file")
    return flags


def build(parent: Path, owner: str, graveyard_name: str, today: date) -> Census:
    repos = find_repos(parent)
    burials = read_graveyard(parent / graveyard_name)
    skip = graveyard_name.casefold()
    all_pins = scan_all([r for r in repos if r.name.casefold() != skip], owner)
    names = {r.name.casefold(): r.name for r in repos}
    by_target, external = _inbound(all_pins, names, burials)
    rows = []
    for repo in repos:
        facts = gather(repo)
        retired_on = burials.retired_on(repo.name)
        state = _state(facts, retired_on, repo.name.casefold() == skip)
        inbound = by_target.get(repo.name, [])
        pinned_by = sorted({p.consumer for p in inbound})
        row = Row(facts, state, retired_on, pinned_by, all_pins.get(repo.name, []),
                  _hint(state, pinned_by, facts, today))
        row.flags = _fact_flags(facts, state) + _pin_flags(row, inbound, burials)
        rows.append(row)
    return Census(str(parent), today.isoformat(), burials.read, rows, external)
