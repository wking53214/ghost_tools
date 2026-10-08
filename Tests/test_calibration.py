"""Every detector carries a calibration record, and every record names
something that exists (ghost_buster/calibration.json)."""
from __future__ import annotations

import re

import json

from ghost_buster.calibration import PATH, REPRODUCE_FIELDS, REQUIRED, records, render, reproducible
from ghost_buster.mechanical import registered_detectors

CHECKS = {"test_status", "committed_secret", "unmerged_branch", "structure", "boundary",
          "no_ci_configuration", "kernel"}


def test_every_registered_detector_has_a_record():
    missing = set(registered_detectors()) - set(records())
    assert not missing, f"detectors with no calibration record: {sorted(missing)}"


def test_every_detector_record_names_a_registered_detector():
    phantom = {n for n, r in records().items() if r["kind"] == "detector"} - set(registered_detectors())
    assert not phantom, f"records for detectors that do not exist: {sorted(phantom)}"


def test_every_record_has_every_field():
    for name, r in records().items():
        missing = [k for k in REQUIRED if k not in r]
        assert not missing, f"{name} lacks {missing}"
        assert isinstance(r["exclusions"], list) and isinstance(r["disclosed"], list)


def test_a_record_without_a_corpus_says_why():
    """A threshold set by convention is not a measurement, and the record
    has to admit it rather than leave the field blank."""
    for name, r in records().items():
        if r["corpus"] is None:
            assert r["date"] is None, f"{name}: a date with no corpus"
            assert r["disclosed"], f"{name}: no corpus and no word about why"


def test_a_record_with_a_date_has_a_corpus_and_a_source():
    for name, r in records().items():
        if r["date"] is not None:
            assert r["corpus"], f"{name}: dated but no corpus"
            assert r["source"], f"{name}: no prose account to check against"


def test_the_repository_checks_are_recorded_too():
    assert CHECKS <= set(records()), sorted(CHECKS - set(records()))


def test_the_file_is_the_one_the_module_reads():
    data = json.loads(PATH.read_text())
    assert data["schema"] == 1
    assert {r["name"] for r in data["records"]} == set(records())


def test_render_shows_the_numbers_and_the_admissions():
    text = render("dead_end_call")
    assert "24 live repositories" in text and '"findings": 1' in text and "cannot say never" in text
    text = render("long_function")
    assert "measured never on no corpus" in text and "set by convention" in text


# ------------------------------------------- recorded, or actually reproducible

def test_every_record_carries_a_reproduce_block():
    for name, r in records().items():
        assert "reproduce" in r, f"{name}: no reproduce block"
        for field in REPRODUCE_FIELDS:
            assert field in r["reproduce"], f"{name}: reproduce block has no {field}"


def test_a_record_that_cannot_be_reproduced_says_why():
    """The distinction this draws: "the repository records that this
    measurement occurred" is a weaker claim than "somebody else could redo
    it", and the word calibration invites the stronger reading."""
    for name, r in records().items():
        if not reproducible(r):
            assert (r["reproduce"].get("note") or "").strip(), (
                f"{name}: not reproducible and no reason recorded"
            )


def test_a_reproducible_record_names_a_command_a_version_and_pinned_commits():
    reproducibles = {n: r for n, r in records().items() if reproducible(r)}
    assert reproducibles, (
        "no record is reproducible, so this test guards nothing; if the "
        "reproducible one was removed, remove this test with it"
    )
    for name, r in reproducibles.items():
        block = r["reproduce"]
        assert block["command"].strip()
        assert block["tool_version"].strip()
        manifest = block["corpus_manifest"]
        assert isinstance(manifest, dict) and manifest, f"{name}: empty manifest"
        for repo, pin in manifest.items():
            assert re.fullmatch(r"[0-9a-f]{7,40}", str(pin.get("commit", ""))), (
                f"{name}: {repo} is not pinned to a commit"
            )


def test_the_renderer_says_which_kind_of_record_it_is():
    reproducible_name = next(n for n, r in records().items() if reproducible(r))
    assert "pinned by commit" in render(reproducible_name)
    unreproducible = next(n for n, r in records().items() if not reproducible(r))
    assert "not reproducible from this repository" in render(unreproducible)
