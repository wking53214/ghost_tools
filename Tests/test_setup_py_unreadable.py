"""A setup.py that cannot be parsed is recorded in the model, not silently
skipped. Before this change the packaging comparison treated a broken setup.py
the same as a missing one, so it reported nothing about the disagreement it
could not check."""
from __future__ import annotations

from ghost_buster.pipeline import _collect_files
from ghost_buster.structure import build_model

from test_structure import PYPROJECT, _repo


def _model(root):
    return build_model(root, _collect_files(root))


def _setup_notes(model):
    return [u for u in model.unresolved if "setup.py" in u]


def test_unparseable_setup_py_is_recorded_in_unresolved(tmp_path):
    root = _repo(tmp_path, files={"setup.py": "from setuptools import setup\nsetup(name='demo',\n"})
    m = _model(root)
    notes = _setup_notes(m)
    assert notes, "a broken setup.py must leave a note in the model"
    assert "could not be parsed" in notes[0]
    assert "setup.py" not in m.packaging_declarations


def test_readable_setup_py_leaves_no_note(tmp_path):
    root = _repo(tmp_path, files={
        "setup.py": "from setuptools import setup\nsetup(name='demo', version='0.1.0')\n",
    })
    m = _model(root)
    assert _setup_notes(m) == []
    assert "setup.py" in m.packaging_declarations


def test_missing_setup_py_leaves_no_note(tmp_path):
    root = _repo(tmp_path, pyproject=PYPROJECT)
    assert _setup_notes(_model(root)) == []
