"""Ecosystem awareness: an import something else provides is wiring, not a void.

The failure this guards against was measured on 2026-09-08: scanned one repo
at a time, an 18-repository ecosystem reported ninety-odd voids, nearly all
of them sibling checkouts, declared dependencies and an uninitialised
submodule. Every one was true and none was a loss. The reader could not tell
"not here" from "not anywhere".
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from blackhole_extrapolator import EvidenceKind, resolve_providers, scan
from blackhole_extrapolator.cli import main


def _repo(parent: Path, name: str, files: dict) -> Path:
    root = parent / name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))
    return root


def test_sibling_provider_turns_a_missing_module_into_wiring(tmp_path):
    spine = _repo(tmp_path, "spine", {"adapter.py": "from ccc import CCCSystem\n"})
    ccc = _repo(tmp_path, "CCC", {"ccc/__init__.py": "class CCCSystem: ...\n"})
    alone = scan(spine)
    assert [e.kind for e in alone] == [EvidenceKind.MISSING_MODULE]
    with_sibling = scan(spine, siblings=[ccc])
    assert [e.kind for e in with_sibling] == [EvidenceKind.WIRING]
    assert "sibling checkout `CCC`" in with_sibling[0].detail


def test_declared_dependency_not_installed_is_wiring_not_a_void(tmp_path):
    repo = _repo(tmp_path, "svc", {
        "app.py": "import definitely_not_installed_xyz\n",
        "requirements.txt": "Definitely-Not-Installed-XYZ>=1.0  # pinned\n",
    })
    kinds = [e.kind for e in scan(repo)]
    assert kinds == [EvidenceKind.WIRING]
    assert "declared dependency" in scan(repo)[0].detail


def test_optional_dependency_in_pyproject_counts_as_declared(tmp_path):
    repo = _repo(tmp_path, "tool", {
        "core.py": "import some_optional_extra_abc\n",
        "pyproject.toml": '[project]\nname = "tool"\ndependencies = []\n\n[project.optional-dependencies]\nsemantic = ["some-optional-extra-abc"]\n',
    })
    assert [e.kind for e in scan(repo)] == [EvidenceKind.WIRING]


def test_undeclared_missing_module_stays_a_void_with_submodule_note(tmp_path):
    repo = _repo(tmp_path, "gsa", {
        "core.py": "from queue_schema import EnqueueResult\n",
        ".gitmodules": '[submodule "vendor/sentinel_os"]\n\tpath = vendor/sentinel_os\n\turl = https://example.invalid/sentinel_os\n',
    })
    (repo / "vendor" / "sentinel_os").mkdir(parents=True)          # declared, empty: not initialised
    evidence = scan(repo)
    assert [e.kind for e in evidence] == [EvidenceKind.MISSING_MODULE]
    assert "submodule `vendor/sentinel_os` is declared but not initialised" in evidence[0].detail


def test_resolve_providers_never_names_the_root_as_its_own_sibling(tmp_path):
    repo = _repo(tmp_path, "self", {"m.py": "x = 1\n"})
    assert resolve_providers(repo, siblings=[repo]) == {}


def test_wiring_never_becomes_a_void_in_the_cli(tmp_path, capsys):
    spine = _repo(tmp_path, "spine", {"adapter.py": "from ccc import CCCSystem\nfrom lost_forever import Thing\n"})
    ccc = _repo(tmp_path, "CCC", {"ccc/__init__.py": "class CCCSystem: ...\n"})
    assert main([str(spine), "--sibling", str(ccc), "--show-wiring"]) == 0
    out = capsys.readouterr().out
    assert "`lost_forever` is reached for" in out
    assert "`ccc` is reached for" not in out
    assert "1 void(s)" in out and "1 import(s) provided elsewhere" in out
    assert "sibling checkout `CCC`" in out


def test_ecosystem_mode_scans_every_checkout_against_the_others(tmp_path, capsys):
    _repo(tmp_path, "a", {"a_mod.py": "from b_mod import B\n"})
    _repo(tmp_path, "b", {"b_mod.py": "class B: ...\nfrom a_mod import A\n"})
    _repo(tmp_path, "c", {"c_mod.py": "from nowhere_at_all import X\n"})
    (tmp_path / "not_a_repo").mkdir()
    assert main([str(tmp_path), "--ecosystem"]) == 0
    out = capsys.readouterr().out
    assert "=== a" in out and "=== b" in out and "=== c" in out and "not_a_repo" not in out
    assert out.count("Nothing is missing") == 2
    assert "`nowhere_at_all` is reached for" in out


def test_json_shape_is_unchanged_unless_wiring_is_requested(tmp_path, capsys):
    spine = _repo(tmp_path, "spine", {"adapter.py": "from ccc import CCCSystem\nfrom lost import Thing\n"})
    ccc = _repo(tmp_path, "CCC", {"ccc/__init__.py": "class CCCSystem: ...\n"})
    assert main([str(spine), "--sibling", str(ccc), "--json"]) == 0
    plain = json.loads(capsys.readouterr().out)
    assert isinstance(plain, list) and len(plain) == 1
    assert main([str(spine), "--sibling", str(ccc), "--json", "--show-wiring"]) == 0
    shaped = json.loads(capsys.readouterr().out)
    assert set(shaped) == {"voids", "wiring"} and len(shaped["wiring"]) == 1
