"""Status labels a reader will trust are surfaced for re-verification, and honest sentences are not."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ghost_buster.mechanical import registered_detectors
from ghost_buster.schema import Category, Severity, Status
from ghost_buster.statusclaim import DETECTOR, detect_status_claims


def _doc(tmp_path: Path, body: str, name: str = "README.md", extra: dict | None = None) -> list:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body))
    for rel, text in (extra or {}).items():
        q = tmp_path / rel
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text(text)
    return sorted(tmp_path.rglob("*"))


def _kinds(tmp_path, body, **kw):
    return [(f.attributes["kind"], f.attributes["phrase"], f.evidence.line_start)
            for f in detect_status_claims(_doc(tmp_path, body, **kw))]


def test_it_is_registered():
    assert DETECTOR in registered_detectors()


@pytest.mark.parametrize("line, kind, phrase", [
    ("This service is production-ready.", "production_ready", "production-ready"),
    ("Production ready and enterprise grade.", "production_ready", "Production ready"),
    ("A battle-tested kernel.", "battle_tested", "battle-tested"),
    ("Fully tested on three platforms.", "fully_tested", "Fully tested"),
    ("We have 100% test coverage.", "full_coverage", "100% test coverage"),
    ("- RL Ready", "ready_badge", "RL Ready"),
    ("- Multi-AI Orchestration Ready", "ready_badge", "Multi-AI Orchestration Ready"),
])
def test_each_kind_of_label_is_found(tmp_path, line, kind, phrase):
    found = _kinds(tmp_path, f"# T\n\n{line}\n")
    assert found == [(kind, phrase, 3)]


@pytest.mark.parametrize("line", [
    "- 'Production-ready': claim not backed by any measurement in this run",
    "- `Battle-tested`: claim not backed by any measurement [unknown]",
    "The label RL Ready is unsupported and should be re-verified.",
    "The badge reads 'Production-ready' in green.",
    "This is not production ready.",
    "It is far from battle-tested.",
    "Nowhere near 100% coverage, and we say so.",
    "The old README claimed it was production ready.",
    'Marketing called it "enterprise grade".',
    "Run `make production-ready` to build.",
    "Get ready for the next step.",
    "The feature is ready.",
])
def test_honest_quoted_and_code_sentences_are_not_claims(tmp_path, line):
    assert _kinds(tmp_path, f"# T\n\n{line}\n") == []


@pytest.mark.parametrize("line", [
    "Produc­tion ready.",            # soft hyphen
    "Production ready.",             # non-breaking space
    "Production‑ready.",             # non-breaking hyphen
    "**Production** ready.",              # emphasis markers
    "__Battle__-_tested_.",
    "Pro​duction ready.",            # zero-width space
    "Ｐｒｏｄｕｃｔｉｏｎ ready.",   # full-width letters
])
def test_a_claim_dressed_up_for_a_scanner_still_reads_as_a_claim(tmp_path, line):
    assert len(_kinds(tmp_path, f"# T\n\n{line}\n")) == 1


def test_a_fenced_block_is_not_prose(tmp_path):
    assert _kinds(tmp_path, "# T\n\n```\nstatus: production ready\n```\n\nAfter the fence: battle-tested.\n") == \
        [("battle_tested", "battle-tested", 7)]


def test_changelogs_are_history_not_claims(tmp_path):
    assert _kinds(tmp_path, "## 1.0\n\nNow production ready.\n", name="CHANGELOG.md") == []
    assert _kinds(tmp_path, "Now production ready.\n", name="docs/HISTORY.md") == []


def test_the_finding_says_how_many_test_files_it_saw(tmp_path):
    files = _doc(tmp_path, "Production ready.\n", extra={"tests/test_a.py": "def test_a():\n    assert 1\n",
                                                        "pkg/mod.py": "x = 1\n"})
    (f,) = detect_status_claims(files)
    assert f.detector == DETECTOR and f.category is Category.DOC_DRIFT and f.severity is Severity.MINOR
    assert f.status is Status.CONFIRMED and f.attributes["test_files_seen"] == "1"
    assert "1 test file(s)" in f.detail and "re-verified" in f.detail
    assert f.evidence.file.endswith("README.md") and f.evidence.snippet == "Production ready."


def test_the_identity_survives_an_edit_above_the_claim(tmp_path):
    (before,) = detect_status_claims(_doc(tmp_path, "# T\n\nProduction ready.\n"))
    (after,) = detect_status_claims(_doc(tmp_path, "# T\n\nA new paragraph.\n\nAnother.\n\nProduction ready.\n"))
    assert before.id == after.id and before.evidence.line_start == 3 and after.evidence.line_start == 7


def test_one_finding_per_line_and_no_crash_on_bad_bytes(tmp_path):
    _doc(tmp_path, "Production ready and battle-tested, on one line.\n")
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe production ready")
    found = detect_status_claims(sorted(tmp_path.rglob("*.md")))
    assert [f.attributes["kind"] for f in found] == ["production_ready"]
