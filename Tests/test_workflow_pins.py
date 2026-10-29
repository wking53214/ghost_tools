"""The workflows are reproducible: what they run is named by content, not by a moving name.

`tests.yml` used to check out the default branch of SWIZZLE and ASSAY, so a
push to either of them could turn this repository's CI red (or green) with
no change here. Every GitHub Action and every sibling the blocking jobs fetch
is now a full commit SHA with a comment naming what it is and how to bump it.
CNS is the one exception, by the owner's decision: it is installed from the tag
`v2.1.0`, spelled the same in every circuit repository, because pip treats a
tag URL and a commit URL as two different sources. The one place that
deliberately follows the siblings' latest is a separate job leg that is
named "non-blocking" and cannot fail the build.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SHA = re.compile(r"^[0-9a-f]{40}$")

# Text, not YAML: the package has no dependencies and the test environment
# should not need one to read a workflow.


def _text(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _gate():
    """The swizzle-gate job, as text: from its key to the end of the file (it is the last job)."""
    text = _text("tests.yml")
    return text[text.index("\n  swizzle-gate:"):]


def _legs():
    """[(label, blocking, swizzle_ref, assay_ref)] for the matrix legs."""
    pattern = re.compile(
        r"- label: (?P<label>.+)\n\s+blocking: (?P<blocking>true|false)\n"
        r"\s+swizzle_ref: (?P<swizzle>\"\"|[0-9a-f]{40})[^\n]*\n"
        r"\s+assay_ref: (?P<assay>\"\"|[0-9a-f]{40})")
    return [(m["label"], m["blocking"] == "true", m["swizzle"].strip('"'), m["assay"].strip('"'))
            for m in pattern.finditer(_gate())]


@pytest.mark.parametrize("name", ["tests.yml", "publish.yml"])
def test_every_action_is_pinned_to_a_full_commit_sha_with_its_tag_in_a_comment(name):
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", _text(name), re.M)
    assert uses
    for target, rest in uses:
        ref = target.split("@", 1)[1]
        assert SHA.match(ref), f"{name}: {target} is not pinned to a full SHA"
        assert re.search(r"#\s*\S", rest), f"{name}: {target} has no comment saying which release the SHA is"
        assert re.search(r"#\s*v\d+\.\d+\.\d+\b", rest), f"{name}: {target} comment is not a full release (vX.Y.Z)"


def test_the_siblings_in_the_blocking_gate_are_pinned_to_full_shas():
    blocking = [leg for leg in _legs() if leg[1]]
    assert len(blocking) == 1, _legs()
    _, _, swizzle, assay = blocking[0]
    assert SHA.match(swizzle) and SHA.match(assay)
    gate = _gate()
    assert "ref: ${{ matrix.swizzle_ref }}" in gate and "ref: ${{ matrix.assay_ref }}" in gate


def test_each_sibling_pin_has_a_bump_comment_and_the_job_says_how_to_bump():
    text = _text("tests.yml")
    lines = re.findall(r"^\s*(?:swizzle|assay)_ref: [0-9a-f]{40}.*$", text, re.M)
    assert len(lines) == 2
    for line in lines:
        assert "#" in line, f"a sibling pin without a comment: {line.strip()}"
    assert "TO BUMP A PIN" in text and "git ls-remote" in text


def test_the_latest_siblings_leg_is_named_non_blocking_and_cannot_fail_the_build():
    latest = [leg for leg in _legs() if not leg[1]]
    assert len(latest) == 1 and "non-blocking" in latest[0][0]
    assert latest[0][2] == "" and latest[0][3] == ""
    gate = _gate()
    assert "continue-on-error: ${{ !matrix.blocking }}" in gate
    assert "fail-fast: false" in gate
    assert "name: swizzle-gate (${{ matrix.label }})" in gate


def test_no_sibling_checkout_follows_a_branch_outside_the_matrix():
    checkouts = re.findall(r"repository: wking53214/(SWIZZLE|ASSAY)\n\s+ref: (.+)", _gate())
    assert sorted(name for name, _ in checkouts) == ["ASSAY", "SWIZZLE"]
    assert all(ref.startswith("${{ matrix.") for _, ref in checkouts), checkouts
    # and no checkout of either sibling exists without a ref line at all
    assert _gate().count("repository: wking53214/") == 2


def test_cns_is_installed_from_the_tag_in_the_workflow_and_the_extra():
    text = _text("tests.yml")
    pins = re.findall(r"CNS\.git@(\S+?)\"", text)
    assert pins and all(p == "v2.1.0" for p in pins), pins
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    extra = re.findall(r"CNS\.git@([0-9a-zA-Z.]+)\"", pyproject)
    assert extra and all(p == "v2.1.0" for p in extra), extra
    assert set(pins) == set(extra)
    assert "# v2.1.0" in pyproject and "# v2.1.0" in text


def test_publish_triggers_on_both_v_and_capital_v_tags_and_strips_either():
    text = _text("publish.yml")
    assert re.search(r'tags: \["v\*", "V\*"\]', text)
    assert "#[vV]}" in text, "the version check must accept either prefix"


def test_ci_installs_the_same_ruff_and_mypy_as_the_dev_extra():
    import tomllib
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"]["optional-dependencies"]["dev"]
    pinned = {d.split("==")[0]: d.split("==")[1] for d in dev if "==" in d}
    assert set(pinned) == {"ruff", "mypy"}, dev
    text = _text("tests.yml")
    for name, version in pinned.items():
        assert f"{name}=={version}" in text, f"tests.yml does not install {name}=={version}"


def test_the_sibling_pins_are_labelled_as_the_tested_set():
    text = _text("tests.yml")
    lines = re.findall(r"^\s*(?:swizzle|assay)_ref: [0-9a-f]{40}.*$", text, re.M)
    assert len(lines) == 2 and all("tested set" in line for line in lines), lines
    prose = re.sub(r"\s*\n\s*#?\s*", " ", _gate())   # comment lines joined into sentences
    assert "tested set" in prose and "behind a sibling's branch head is expected" in prose


def test_the_workflow_runs_on_main_pushes_pull_requests_and_the_horsemen_branches():
    text = _text("tests.yml")
    on = text[text.index("\non:"):text.index("\njobs:")]
    assert re.search(r'push:\n(?:\s*#.*\n)*\s*branches: \[main, "claude/\*\*"\]', on), on
    assert re.search(r"^  pull_request:", on, re.M), on


def test_the_gate_installs_the_numpy_and_matplotlib_that_assays_verifier_needs():
    # ASSAY 0.11.1 exits 1 on a skipped claim, and the claims that need numpy
    # or matplotlib skip without them. numpy 2.5.4 needs Python 3.12 or newer.
    gate = _gate()
    assert "sys.version_info >= (3, 12)" in gate
    assert "numpy=2.5.4" in gate and "numpy=2.4.6" in gate
    assert '"numpy==$numpy"' in gate and "matplotlib==3.11.2" in gate
    # installed into the interpreter that runs swizzle, before the gate runs
    assert gate.index("matplotlib==3.11.2") < gate.index("python -m swizzle assay")


def test_the_blocking_gate_pins_the_recorded_tested_set_with_true_version_comments():
    # SWIZZLE 0.8.5 (head of its main) and ASSAY 0.11.3 (a commit on its main).
    text = _text("tests.yml")
    swizzle = re.search(r"^\s*swizzle_ref: ([0-9a-f]{40})\s+# (.*)$", text, re.M)
    assay = re.search(r"^\s*assay_ref: ([0-9a-f]{40})\s+# (.*)$", text, re.M)
    assert swizzle and assay
    assert swizzle[1] == "522658415b026ac3211d3fc130ba7da7c77cc400" and "SWIZZLE 0.8.5" in swizzle[2]
    assert assay[1] == "a1732f2bf3748235661f65b96e590a6d44ace71c" and "ASSAY 0.11.3" in assay[2]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert swizzle[1] in readme and assay[1] in readme


@pytest.mark.parametrize("name", ["tests.yml", "publish.yml"])
def test_every_workflow_declares_its_permissions(name):
    text = _text(name)
    assert re.search(r"^\s*permissions:\s*$", text, re.M), f"{name} has no permissions block"


def test_the_tests_workflow_is_read_only_at_the_top_and_no_job_widens_it():
    text = _text("tests.yml")
    # A top-level key (column 0), before the jobs, granting contents: read and nothing else.
    top = text[:text.index("\njobs:")]
    assert re.search(r"^permissions:\n  contents: read\n(?!  )", top, re.M), top
    # No job-level block, and nothing anywhere asks for a write scope.
    assert not re.search(r"^\s{2,}permissions:", text, re.M)
    assert not re.search(r":\s*write\b", text)


def test_no_pin_is_called_the_head_of_a_siblings_main():
    """The SWIZZLE pin was described as the head of SWIZZLE's main and ASSAY's main as having added only
    `recovered-originals/`. Neither was true. The pins are the last set this repository's CI tested on its own."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    current = readme[:readme.index("## 4c.")] + readme[readme.index("## 4d."):]   # 4c tells the history
    for name, text in (("README.md", current), ("tests.yml", _text("tests.yml"))):
        assert not re.search(r"head of (SWIZZLE's|its|ASSAY's) `?main", text), name
        assert "recovered-originals" not in text, name
    assert "last SWIZZLE and ASSAY commits this repository's CI tested on its own" in readme
