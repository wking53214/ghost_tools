"""ghost_tools is independent of CNS, and these tests hold whether or not CNS is installed.

The checks that need a fresh interpreter block ``cns`` outright
(``sys.modules['cns'] = None`` makes any import of it fail), so the result does not
depend on what the test environment happens to contain.
"""
from __future__ import annotations

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

#: Written exactly as Warden writes its pin, so pip never sees two differing direct URLs.
CNS_PIN = "cns @ git+https://github.com/wking53214/CNS.git@v1.8.0"


def test_the_package_declares_no_runtime_dependency():
    assert CONFIG["project"]["dependencies"] == []


def test_the_cns_extra_is_the_shared_pin_and_nothing_else():
    assert CONFIG["project"]["optional-dependencies"]["cns"] == [CNS_PIN]


def test_the_extra_is_pinned_to_a_tag_or_a_full_commit():
    ref = CNS_PIN.rsplit("@", 1)[1]
    is_tag = ref.startswith("v") and ref[1:].replace(".", "").isdigit()
    is_commit = len(ref) == 40 and all(c in "0123456789abcdef" for c in ref)
    assert is_tag or is_commit, f"cns is pinned to {ref!r}, which can move"


def test_the_tests_workflow_installs_the_same_pin():
    text = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert f'python -m pip install "{CNS_PIN}"' in text


def test_the_publish_workflow_installs_no_extra():
    text = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "cns" not in text
