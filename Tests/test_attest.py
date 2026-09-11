"""A digest chain detects an edited record. It does not defeat an adversary.

The baseline, the case file and the ledger are three files anyone who can
write the repository can edit, and two of them are MEANT to be edited: a
baseline is a suppression policy and a case file is where a human writes a
decision. What was missing is any way for a later reader to tell whether
the record they hold is the record the tool wrote.

Each run now records a digest of the baseline and case file as it read
them, and a link binding it to the run before. These tests hold both the
property and its limit: the last test proves an editor who recomputes the
chain leaves no trace, because a test suite that only demonstrated the
happy case would be advertising, not evidence.
"""
from __future__ import annotations

import json

from ghost_buster.attest import ABSENT, Break, digest, digest_file, link, render, verify
from ghost_buster.ledger import RAN, Ledger
from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status


def _finding(summary="a finding"):
    return Finding(detector="dead_code", category=Category.DEAD_CODE, layer=Layer.MECHANICAL,
                   severity=Severity.MINOR, status=Status.CONFIRMED, summary=summary,
                   detail="", evidence=Evidence(file="src/m.py"))


def _ledger_with_runs(tmp_path, n=3, records=None):
    ledger = Ledger(tmp_path / "ledger.json")
    for i in range(n):
        ledger.record([_finding(f"finding {i}")], checks={"tests": RAN}, commit=f"c{i}",
                      tool_version="test", scanned=10, records=records or {})
    ledger.save()
    return ledger


def _runs_on_disk(tmp_path):
    return json.loads((tmp_path / "ledger.json").read_text())["runs"]


# ---------------------------------------------------------------- digests

def test_a_missing_record_is_a_state_not_a_gap(tmp_path):
    assert digest_file(tmp_path / "nothing.json") == ABSENT
    assert digest_file(None) == ABSENT


def test_a_reformatted_record_is_the_same_record(tmp_path):
    compact = tmp_path / "a.json"
    pretty = tmp_path / "b.json"
    compact.write_text('{"b":2,"a":[1,2]}')
    pretty.write_text('{\n  "a": [\n    1,\n    2\n  ],\n  "b": 2\n}\n')
    assert digest_file(compact) == digest_file(pretty), (
        "a digest over bytes would call a re-indented baseline a tampered one"
    )


def test_a_changed_record_is_a_different_digest(tmp_path):
    one = tmp_path / "a.json"
    one.write_text('{"accepted": ["ghost-1"]}')
    first = digest_file(one)
    one.write_text('{"accepted": ["ghost-1", "ghost-2"]}')
    assert digest_file(one) != first


def test_an_unreadable_record_is_still_in_the_chain(tmp_path):
    broken = tmp_path / "c.json"
    broken.write_text("{not json at all")
    assert digest_file(broken) not in ("", ABSENT)


# ------------------------------------------------------------- the chain

def test_an_untouched_chain_verifies(tmp_path):
    _ledger_with_runs(tmp_path, 4)
    assert verify(_runs_on_disk(tmp_path)) == []
    assert "every link verified" in render([], 4)


def test_an_edited_past_run_breaks_its_own_link_and_every_one_after(tmp_path):
    """The case this exists for: a run's numbers changed after the fact."""
    _ledger_with_runs(tmp_path, 4)
    runs = _runs_on_disk(tmp_path)
    runs[1]["counts"]["found"] = 0

    breaks = verify(runs)
    assert breaks, "an edited run verified clean"
    assert breaks[0].run_index == 1
    assert "does not match" in breaks[0].what


def test_a_removed_run_breaks_the_chain(tmp_path):
    """History with a hole in it is the quieter version of the same edit."""
    _ledger_with_runs(tmp_path, 4)
    runs = _runs_on_disk(tmp_path)
    del runs[1]
    assert verify(runs), "a deleted run left no trace"


def test_a_reordered_history_breaks_the_chain(tmp_path):
    _ledger_with_runs(tmp_path, 4)
    runs = _runs_on_disk(tmp_path)
    runs[1], runs[2] = runs[2], runs[1]
    assert verify(runs)


def test_the_baseline_a_run_read_is_recorded(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"accepted": []}')
    _ledger_with_runs(tmp_path, 2, records={"baseline": digest_file(baseline)})
    runs = _runs_on_disk(tmp_path)
    assert runs[-1]["records"]["baseline"] == digest_file(baseline)

    baseline.write_text('{"accepted": ["ghost-1"]}')
    assert runs[-1]["records"]["baseline"] != digest_file(baseline), (
        "the run's record of what it read must not follow the file's later edits"
    )


def test_runs_written_before_the_chain_are_unchained_not_broken(tmp_path):
    """Reading an old ledger as tampered would be a false accusation."""
    _ledger_with_runs(tmp_path, 3)
    runs = _runs_on_disk(tmp_path)
    for run in runs:
        run["link"] = ""
    breaks = verify(runs)
    assert len(breaks) == 3
    assert all("written before" in b.what for b in breaks)
    assert "0 broken link(s)" in render(breaks, 3)


# ------------------------------------------------------------- the limit

def test_an_editor_who_recomputes_the_chain_leaves_no_trace(tmp_path):
    """The claim boundary, as a test. There is no key, so the chain detects
    an edit and not an adversary; a module that shipped without this test
    would be inviting the stronger reading."""
    _ledger_with_runs(tmp_path, 4)
    runs = _runs_on_disk(tmp_path)

    runs[1]["counts"]["found"] = 0
    previous = runs[0]["link"]
    for run in runs[1:]:
        run["link"] = link(previous, run)
        previous = run["link"]

    assert verify(runs) == [], (
        "if this ever fails, the chain has become something stronger than "
        "the module claims, and attest.py's docstring needs rewriting"
    )


def test_the_render_says_what_a_broken_link_does_and_does_not_mean(tmp_path):
    text = render([Break(2, "r2", "link a does not match b")], 4)
    assert "detects edits, not adversaries" in text


def test_no_runs_is_reported_rather_than_passed(tmp_path):
    assert "no runs to verify" in render([], 0)


def test_the_digest_is_stable_across_key_order():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
