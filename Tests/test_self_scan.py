"""The repository scans itself in CI against a committed baseline. Two
things keep that baseline a set of decisions rather than a place findings
go to be forgotten:

  * only MAJOR and CRITICAL findings are ever baselined here, each with a
    reason recorded in .ghost_casefile.json; MINOR findings are reported on
    every run and gate nothing;
  * every baseline entry still matches a finding the current tree
    produces. A stale entry is a decision about something that no longer
    exists, and it comes out.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = ROOT / ".ghost_baseline.json"
CASEFILE = ROOT / ".ghost_casefile.json"


def test_only_major_and_critical_findings_are_baselined():
    entries = json.loads(BASELINE.read_text())
    assert entries, "the self-scan baseline is empty; CI would gate on nothing"
    minor = [e["id"] for e in entries if e["severity"] not in ("major", "critical")]
    assert not minor, f"MINOR findings are reported, never baselined, here: {minor}"


def test_every_baselined_finding_has_a_recorded_reason():
    entries = json.loads(BASELINE.read_text())
    cases = json.loads(CASEFILE.read_text())["cases"]
    for e in entries:
        matching = [c for c in cases if c["detector"] == e["detector"] and c["note"]]
        assert matching, f"{e['id']} ({e['detector']}) is baselined with no reason in the case file"


def test_no_baseline_entry_is_stale():
    from ghost_buster.baseline import Baseline
    from ghost_buster.pipeline import _collect_files
    from ghost_buster.mechanical import run_all

    current = run_all(_collect_files(ROOT))
    stale = Baseline(BASELINE).stale(current)
    assert not stale, "baselined findings the tree no longer produces: " + ", ".join(f.id for f in stale)
