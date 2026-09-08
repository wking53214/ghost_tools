"""Defects found on the first full-library run (18 checkouts, 2026-09-08)."""
from __future__ import annotations

import textwrap
from pathlib import Path

from blackhole_extrapolator import EvidenceKind, scan
from blackhole_extrapolator.detect import _declared_dependencies, detect_dangling_in_debris


def _write(root: Path, files: dict) -> None:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))


def test_namespace_package_holding_only_subpackages_is_importable(tmp_path):
    """ecology's `src/` has no .py files of its own and no __init__; it holds
    `src/rag/...`. `import src.rag` was reported missing 38 times."""
    _write(tmp_path, {"src/rag/pipeline.py": "X = 1\n", "run.py": "from src.rag.pipeline import X\n"})
    assert [e for e in scan(tmp_path) if e.kind is EvidenceKind.MISSING_MODULE] == []


def test_requirements_are_found_below_the_root_and_includes_are_followed(tmp_path):
    _write(tmp_path, {
        "pkg/requirements.txt": "fastapi>=0.100\n-r extra/more.txt\n",
        "pkg/extra/more.txt": "psycopg2-binary\n--requirement ../../missing.txt\n",
    })
    names = _declared_dependencies(tmp_path)
    assert {"fastapi", "psycopg2_binary"} <= names


def test_requirement_include_cycles_terminate(tmp_path):
    _write(tmp_path, {"requirements.txt": "-r requirements.txt\nredis\n"})
    assert "redis" in _declared_dependencies(tmp_path)


def test_dict_literal_booleans_in_debris_are_not_dangling_types(tmp_path):
    flat = tmp_path / "flat.py"
    flat.write_text('def f(x: Foo, ok: bool = True): return {"ok": True, "bad": False, "n": None} class A: pass')
    names = {e.detail.split("`")[1] for e in detect_dangling_in_debris(flat)}
    assert "Foo" in names
    assert not names & {"True", "False", "None"}


def test_declared_distribution_provides_its_import_name(tmp_path):
    """psycopg2-binary provides `psycopg2`, opentelemetry-api provides
    `opentelemetry`, PyYAML provides `yaml`. sentinel_os declared all of its
    dependencies and still showed three of them as voids."""
    _write(tmp_path, {"requirements.txt": "psycopg2-binary\nopentelemetry-api\nPyYAML\nscikit-learn\n"})
    names = _declared_dependencies(tmp_path)
    assert {"psycopg2", "opentelemetry", "yaml", "sklearn"} <= names


def test_httpx_is_a_distribution_not_a_url(tmp_path):
    _write(tmp_path, {"requirements.txt": "httpx<0.28  # pinned\nhttps://example.invalid/wheel.whl\n"})
    names = _declared_dependencies(tmp_path)
    assert "httpx" in names and not any(n.startswith("https") for n in names)
