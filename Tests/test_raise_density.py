"""The maturity measure: raise sites and lines, per module.

A raise site is a `raise X` statement. A bare `raise` re-raises the current
exception and is not a site of its own. The numbers are evidence about how
much of a module fails loudly; they are reported, never judged.
"""

from __future__ import annotations

import json

from ghost_buster.pipeline import _collect_files
from ghost_buster.structure import build_model, render_model


def _model_for(tmp_path, source: str):
    root = tmp_path / "repo"
    (root / "demo").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = []\n'
    )
    (root / "demo" / "__init__.py").write_text("")
    (root / "demo" / "core.py").write_text(source)
    return build_model(root, _collect_files(root))


def _module(model, dotted):
    return next(m for m in model.modules if m.dotted == dotted)


def test_each_raise_statement_is_one_site(tmp_path):
    model = _model_for(
        tmp_path,
        "def f(x):\n"
        "    if x < 0:\n"
        "        raise ValueError('negative')\n"
        "    if x > 9:\n"
        "        raise ValueError('large')\n"
        "    raise KeyError\n",
    )

    assert _module(model, "demo.core").raise_sites == 3


def test_a_bare_reraise_is_not_a_site(tmp_path):
    model = _model_for(
        tmp_path,
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except OSError:\n"
        "        raise\n",
    )

    assert _module(model, "demo.core").raise_sites == 0


def test_lines_count_the_physical_lines_of_the_file(tmp_path):
    model = _model_for(tmp_path, "x = 1\ny = 2\nz = 3\n")

    assert _module(model, "demo.core").lines == 3


def test_the_counts_are_serialised_per_module(tmp_path):
    model = _model_for(tmp_path, "def f():\n    raise RuntimeError('boom')\n")

    payload = json.loads(model.to_json())
    core = next(m for m in payload["modules"] if m["dotted"] == "demo.core")

    assert core["raise_sites"] == 1
    assert core["lines"] == 2


def test_the_report_states_lines_per_raise(tmp_path):
    model = _model_for(tmp_path, "def f():\n    raise RuntimeError('boom')\n")

    assert "lines per raise     : 2" in render_model(model)


def test_a_repo_without_raises_says_none_rather_than_dividing(tmp_path):
    model = _model_for(tmp_path, "x = 1\n")

    assert "lines per raise     : none (no raise sites)" in render_model(model)
