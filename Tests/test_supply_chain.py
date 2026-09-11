"""The build that produces the evidence is pinned like the evidence.

A tag is a pointer somebody else can move. `actions/checkout@v4` today and
`actions/checkout@v4` next week can be different code, which means the
environment that runs this repository's tests, and the one that publishes
its releases, can change without any change to this repository. For most
projects that is an accepted convenience. For the one whose argument is
that a claim should be checkable, it was the loudest inconsistency in the
tree: the Python was held to mutation testing and the build was held to a
tag.

Every action is pinned to a commit digest now, with the moving ref it came
from in a comment beside it so a person can still tell what they are
upgrading. These tests hold that, and hold the comment honest.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<action>[^@\s]+)@(?P<ref>\S+)(?:\s+#\s*(?P<note>.+))?$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def _uses(path: Path):
    for n, line in enumerate(path.read_text().splitlines(), start=1):
        found = USES.match(line)
        if found:
            yield n, found


def test_there_are_workflows_to_check():
    assert WORKFLOWS, "this test guards nothing if the workflows moved"


@pytest.mark.parametrize("path", WORKFLOWS, ids=[p.name for p in WORKFLOWS])
def test_every_action_is_pinned_to_a_commit(path):
    floating = [f"{path.name}:{n} {m.group('action')}@{m.group('ref')}"
                for n, m in _uses(path) if not SHA.match(m.group("ref"))]
    assert not floating, (
        "a tag is a pointer somebody else can move, so these steps can change "
        "without this repository changing: " + ", ".join(floating)
    )


@pytest.mark.parametrize("path", WORKFLOWS, ids=[p.name for p in WORKFLOWS])
def test_every_pin_says_which_ref_it_came_from(path):
    """A bare digest is unreadable and nobody upgrades what they cannot
    read. The comment is how a human knows what they are looking at."""
    unlabelled = [f"{path.name}:{n}" for n, m in _uses(path) if not (m.group("note") or "").strip()]
    assert not unlabelled, f"pinned but unlabelled: {', '.join(unlabelled)}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=[p.name for p in WORKFLOWS])
def test_third_party_downloads_are_pinned_to_a_version(path):
    """The same argument reaches past `uses:`. gitleaks arrives by curl, and
    a URL without a version is a moving target too."""
    text = path.read_text()
    for line in text.splitlines():
        if "https://github.com/" in line and "releases/download" in line:
            assert re.search(r"/v?\d+\.\d+\.\d+/", line), f"unversioned download: {line.strip()}"
