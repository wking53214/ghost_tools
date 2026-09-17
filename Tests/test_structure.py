"""The structural model: evidence, and the refusal to exceed it.

Every test here is one of two kinds. Either the model records something
that is observably true, or it declines to state something it cannot
establish and says so in `unresolved` instead. The second kind is the
harder discipline and most of the bugs found while building this module
were failures of it.
"""
from __future__ import annotations

import json

import pytest

from ghost_buster.cli import main
from ghost_buster.pipeline import _collect_files
from ghost_buster.schema import Severity
from ghost_buster.structure import (
    build_model, derive_findings, render_model, render_report, requirement_name,
)

PYPROJECT = '''[project]
name = "demo"
version = "0.1.0"
dependencies = ["requests>=2"]

[project.optional-dependencies]
test = ["pytest"]

[project.scripts]
demo = "demo.cli:main"
'''


def _repo(tmp_path, *, pyproject=PYPROJECT, files=None):
    root = tmp_path / "repo"
    (root / "demo").mkdir(parents=True)
    (root / "demo" / "__init__.py").write_text("")
    (root / "demo" / "cli.py").write_text(
        "import sys\n\n\ndef main():\n    return 0\n\n\n"
        'if __name__ == "__main__":\n    sys.exit(main())\n'
    )
    if pyproject is not None:
        (root / "pyproject.toml").write_text(pyproject)
    for name, text in (files or {}).items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _model(root):
    return build_model(root, _collect_files(root))


def _kinds(findings):
    return {f.attributes["kind"] for f in findings}


# ------------------------------------------------------------- it observes

def test_packaging_evidence_is_recorded(tmp_path):
    m = _model(_repo(tmp_path))
    assert m.distribution == "demo"
    assert m.packages == ["demo"]
    assert "requests" in m.declared_dependencies


def test_optional_dependencies_are_declarations_too(tmp_path):
    """Reading only project.dependencies reported six packages as
    undeclared on a real repository that declares every one under an
    extra."""
    assert "pytest" in _model(_repo(tmp_path)).declared_dependencies


def test_entry_points_are_found_in_every_form(tmp_path):
    eps = _model(_repo(tmp_path)).entry_points
    assert any("console_script demo -> demo.cli:main" in e for e in eps)
    assert any(e.endswith("demo.cli:main") for e in eps)
    assert any("__main__ guard" in e for e in eps)


def test_imports_are_split_into_internal_and_external(tmp_path):
    root = _repo(tmp_path, files={"demo/work.py": "import requests\nfrom demo import cli\n"})
    facts = next(m for m in _model(root).modules if m.dotted == "demo.work")
    assert "requests" in facts.imports_external
    assert "demo" in facts.imports_internal


def test_module_level_mutable_state_is_recorded(tmp_path):
    root = _repo(tmp_path, files={"demo/reg.py": "REGISTRY = {}\nNAME = 'x'\n"})
    facts = next(m for m in _model(root).modules if m.dotted == "demo.reg")
    assert facts.module_state == ["REGISTRY"], "a str binding is a constant, not state"


def test_data_representations_are_recorded(tmp_path):
    src = ("from dataclasses import dataclass\n\n\n"
           "@dataclass\nclass Point:\n    x: int\n")
    root = _repo(tmp_path, files={"demo/model.py": src})
    facts = next(m for m in _model(root).modules if m.dotted == "demo.model")
    assert facts.data_models == ["Point"]


def test_declared_public_surface_is_read_from_dunder_all(tmp_path):
    root = _repo(tmp_path, files={"demo/api.py": "__all__ = ['go']\n\n\ndef go():\n    pass\n"})
    facts = next(m for m in _model(root).modules if m.dotted == "demo.api")
    assert facts.public_names == ["go"]


# ------------------------------------------ boundaries: the call, not the import

def test_importing_pathlib_alone_is_not_a_filesystem_boundary(tmp_path):
    """Measured: 37 of this project's 68 modules import pathlib, and most
    only manipulate paths. A model claiming all 37 touch disk is not so
    much wrong as useless."""
    src = "from pathlib import Path\n\n\ndef join(a, b):\n    return Path(a) / b\n"
    root = _repo(tmp_path, files={"demo/paths.py": src})
    facts = next(m for m in _model(root).modules if m.dotted == "demo.paths")
    assert "filesystem" not in facts.boundaries


def test_actually_reading_a_file_is_a_filesystem_boundary(tmp_path):
    src = "from pathlib import Path\n\n\ndef load(p):\n    return Path(p).read_text()\n"
    root = _repo(tmp_path, files={"demo/io.py": src})
    facts = next(m for m in _model(root).modules if m.dotted == "demo.io")
    assert "filesystem" in facts.boundaries


@pytest.mark.parametrize("src,boundary", [
    ("import subprocess\n\n\ndef r():\n    subprocess.run(['ls'])\n", "subprocess"),
    ("import socket\n\n\ndef c():\n    return socket.socket()\n", "network"),
    ("import sqlite3\n\n\ndef c():\n    return sqlite3.connect(':memory:')\n", "database"),
    ("import os\n\n\ndef e():\n    return os.environ['X']\n", "environment"),
])
def test_unambiguous_boundaries_are_recorded(tmp_path, src, boundary):
    root = _repo(tmp_path, files={"demo/b.py": src})
    facts = next(m for m in _model(root).modules if m.dotted == "demo.b")
    assert boundary in facts.boundaries


# ------------------------------------------------- it declines to overreach

def test_dynamic_resolution_is_recorded_as_unresolved(tmp_path):
    root = _repo(tmp_path, files={
        "demo/dyn.py": "def load(name):\n    return __import__(name)\n",
    })
    m = _model(root)
    assert any("__import__" in u for u in m.unresolved)


def test_computed_getattr_is_recorded_as_unresolved(tmp_path):
    root = _repo(tmp_path, files={
        "demo/dyn.py": "def get(o, n):\n    return getattr(o, n)\n",
    })
    assert any("getattr" in u for u in _model(root).unresolved)


def test_the_model_never_claims_an_architectural_role(tmp_path):
    """The spec this implements forbids inferring a boundary from a
    conventional directory name, which forbids the only mechanical route
    to one. The report says so rather than quietly not doing it."""
    root = _repo(tmp_path, files={
        "demo/services/__init__.py": "", "demo/services/thing.py": "def go():\n    pass\n",
        "demo/adapters/__init__.py": "", "demo/adapters/thing.py": "def go():\n    pass\n",
    })
    text = render_model(_model(root))
    assert "NOT ANSWERED HERE, ON PURPOSE" in text
    for word in ("domain logic", "orchestration", "adapters"):
        assert word in text
    assert "demo.services is domain" not in text


def test_an_unmappable_import_is_unresolved_not_a_finding(tmp_path):
    """An import name is not a distribution name: yaml ships in PyYAML,
    PIL in pillow. When the mapping cannot be established, a missing
    declaration and an ordinary alias look identical."""
    root = _repo(tmp_path, files={
        "demo/uses.py": "import definitely_not_installed_anywhere\n"})
    m = _model(root)
    findings = derive_findings(m)
    assert "undeclared dependency" not in _kinds(findings)
    assert any("could not be mapped" in u for u in m.unresolved)


# -------------------------------------------- the slopsquat surface (v0.17)

def test_an_invented_package_is_reported(tmp_path):
    """The 2026 attack. A model asked for working code emits an import for a
    package that does not exist; 38% of such names are conflations of two
    real packages, and `express_mongoose` is the canonical example."""
    root = _repo(tmp_path, files={"demo/uses.py": "import express_mongoose\n"})
    findings = derive_findings(_model(root))
    unresolvable = [f for f in findings if f.attributes["kind"] == "unresolvable dependency"]
    assert len(unresolvable) == 1
    assert unresolvable[0].severity == Severity.MAJOR
    assert "express-mongoose" in unresolvable[0].summary


def test_a_guarded_import_is_not_an_invented_package(tmp_path):
    """The discriminator. A hallucinated package is imported UNGUARDED,
    because the model believes it is real. An optional dependency is wrapped
    in try/except ImportError by an author who knew it might be absent.
    boundary.py already reports those; repeating them here at MAJOR would be
    the same fact twice, louder.

    Measured: without this, three of observe-perceive's sibling packages
    were reported as invented names."""
    src = ("try:\n    import express_mongoose\n"
           "except ImportError:\n    express_mongoose = None\n")
    root = _repo(tmp_path, files={"demo/uses.py": src})
    assert "unresolvable dependency" not in _kinds(derive_findings(_model(root)))


@pytest.mark.parametrize("guard", ["ImportError", "ModuleNotFoundError"])
def test_every_guard_spelling_excludes_it(tmp_path, guard):
    src = (f"try:\n    from express_mongoose import thing\n"
           f"except {guard}:\n    thing = None\n")
    root = _repo(tmp_path, files={f"demo/u_{guard}.py": src})
    assert "unresolvable dependency" not in _kinds(derive_findings(_model(root)))


@pytest.mark.parametrize("src,why", [
    ("import json\n", "standard library"),
    ("from demo import cli\n", "provided by this repository"),
    ("import pytest\n", "installed here"),
])
def test_a_resolvable_import_is_not_reported(tmp_path, src, why):
    root = _repo(tmp_path, files={"demo/uses.py": src})
    assert "unresolvable dependency" not in _kinds(derive_findings(_model(root))), why


@pytest.mark.parametrize("parent", ["src", "lib", "python"])
def test_a_src_layout_package_is_recognised_as_this_repos_own(tmp_path, parent):
    """The src layout is mainstream and `src` itself is not a package, so a
    scan that only looks at the repository root never sees the package
    inside it -- and then reports the repository as reaching for an
    outside package named after itself.

    Measured across a 37-repository library: TIE holds src/tie/__init__.py
    and GEMS holds src/gems/__init__.py, and both were reported as having
    an unresolvable dependency on 'tie' and 'gems'. A repository importing
    itself is the clearest false positive there is.
    """
    root = tmp_path / f"repo_{parent}"
    pkg = root / parent / "thing"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("def go():\n    pass\n")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "thing"\nversion = "0.1.0"\ndependencies = []\n')
    (root / "run.py").write_text("import thing\n")

    m = build_model(root, _collect_files(root))
    assert "thing" in m.packages, f"{parent}/thing is a package this repo provides"
    assert "unresolvable dependency" not in _kinds(derive_findings(m))


def test_a_src_directory_that_is_itself_a_package_is_not_descended_into(tmp_path):
    """If src/__init__.py exists then `src` IS the package and its
    children are submodules, not top-level names."""
    root = tmp_path / "repo_srcpkg"
    (root / "src" / "inner").mkdir(parents=True)
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "inner" / "__init__.py").write_text("")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "s"\nversion = "0.1.0"\ndependencies = []\n')
    m = build_model(root, _collect_files(root))
    assert "src" in m.packages
    assert "inner" not in m.packages


def test_a_module_in_a_directory_without_an_init_is_not_invented(tmp_path):
    """A plain directory of modules with no __init__.py is not a package, so
    its name is absent from the importable roots and an import of it reads as
    EXTERNAL. This repository's own Tests/ is laid out exactly that way, and
    without the local-module check every such import is reported as a name
    somebody invented."""
    root = _repo(tmp_path, files={
        "helpers/util.py": "def go():\n    pass\n",
        "demo/uses.py": "from helpers import util\n",
    })
    m = _model(root)
    assert "helpers" not in m.packages, "the fixture only means something while this holds"
    assert "unresolvable dependency" not in _kinds(derive_findings(m))


def test_a_declared_package_is_not_invented_even_if_absent(tmp_path):
    """Declaring it is a claim that it is real, made by a person."""
    pyproject = PYPROJECT.replace('dependencies = ["requests>=2"]',
                                  'dependencies = ["express-mongoose"]')
    root = _repo(tmp_path, pyproject=pyproject,
                 files={"demo/uses.py": "import express_mongoose\n"})
    assert "unresolvable dependency" not in _kinds(derive_findings(_model(root)))


def test_nothing_scanned_produces_no_findings(tmp_path):
    """With no modules, "this symbol does not exist" and "this symbol was
    not looked at" are indistinguishable. Reporting the first would be
    inventing evidence -- and this was a real bug: relative vs resolved
    paths silently skipped every module and produced four false entry
    point findings."""
    m = build_model(_repo(tmp_path), [])
    findings = derive_findings(m)
    assert findings == []
    assert any("no modules were scanned" in u for u in m.unresolved)


# ---------------------------------------------------------------- findings

def test_a_console_script_pointing_at_nothing_is_reported(tmp_path):
    bad = PYPROJECT.replace('demo = "demo.cli:main"', 'demo = "demo.cli:nonexistent"')
    findings = derive_findings(_model(_repo(tmp_path, pyproject=bad)))
    assert _kinds(findings) == {"entry point target missing"}
    assert findings[0].severity == Severity.MAJOR
    assert "nonexistent" in findings[0].summary


def test_a_console_script_pointing_at_a_missing_module_is_reported(tmp_path):
    bad = PYPROJECT.replace('demo = "demo.cli:main"', 'demo = "demo.gone:main"')
    findings = derive_findings(_model(_repo(tmp_path, pyproject=bad)))
    assert _kinds(findings) == {"entry point target missing"}


def test_a_valid_console_script_is_not_reported(tmp_path):
    assert derive_findings(_model(_repo(tmp_path))) == []


def test_a_repo_with_no_declaration_mechanism_is_not_nagged(tmp_path):
    """Nothing to contradict. A repo with no pyproject and no requirements
    is not declaring anything wrongly."""
    # The import must be a package CERTAINLY installed wherever this runs:
    # the check only reaches a verdict for an import it can map to a
    # distribution. This used `requests`, installed on a developer machine
    # and not on the CI runner, so the mutant that removes the
    # declaration-source guard died locally and survived in CI.
    root = _repo(tmp_path, pyproject=None,
                 files={"demo/uses.py": "import pytest\n"})
    assert derive_findings(_model(root)) == []


@pytest.mark.parametrize("spec,expected", [
    ("ruff==0.15.22", "ruff"), ("Ruff", "ruff"), ("scikit_learn>=1", "scikit-learn"),
    ("pkg[extra]>=2", "pkg"), ("thing @ git+https://x/y", "thing"),
])
def test_requirement_names_normalise(spec, expected):
    assert requirement_name(spec) == expected


# ------------------------------------------------------------------- plumbing

def test_a_missing_directory_reports_that_it_could_not_run(tmp_path):
    m = build_model(tmp_path / "nope", [])
    assert m.ran is False
    assert "did not run" in render_report(m, [])


def test_the_model_serialises_to_json(tmp_path):
    payload = json.loads(_model(_repo(tmp_path)).to_json())
    assert payload["distribution"] == "demo"
    assert isinstance(payload["modules"], list)


def test_the_cli_runs_it_by_default(tmp_path, capsys):
    root = _repo(tmp_path)
    main([str(root), "--no-tests", "--no-secrets", "--no-branches", "--no-ledger",
          "--no-project", "--baseline", str(tmp_path / "b.json")])
    assert "structure scan mapped" in capsys.readouterr().err


def test_no_structure_leaves_a_receipt(tmp_path, capsys):
    root = _repo(tmp_path)
    main([str(root), "--no-structure", "--no-tests", "--no-secrets", "--no-branches",
          "--no-ledger", "--no-project", "--baseline", str(tmp_path / "b.json")])
    err = capsys.readouterr().err
    assert "structure scan SKIPPED at your request (--no-structure)" in err
    assert "structure scan mapped" not in err


def test_structure_out_writes_the_model(tmp_path, capsys):
    root = _repo(tmp_path)
    out = tmp_path / "model.json"
    main([str(root), "--structure-out", str(out), "--no-tests", "--no-secrets",
          "--no-branches", "--no-ledger", "--no-project",
          "--baseline", str(tmp_path / "b.json")])
    capsys.readouterr()
    assert json.loads(out.read_text())["distribution"] == "demo"


# ------------------------------- build-time imports and parallel packaging

SETUP_PY = '''from setuptools import setup

setup(
    name="demo",
    version="0.1.0",
    description="{description}",
    install_requires=["requests>=2"],
    python_requires=">=3.11",
)
'''


def _kinds(findings):
    return {f.attributes["kind"] for f in findings}


def _scan(root):
    return derive_findings(build_model(root, _collect_files(root)))


def test_setup_py_importing_setuptools_is_not_an_undeclared_dependency(tmp_path):
    """The false positive this check shipped with. `[build-system].requires`
    is the ONLY correct place to declare setuptools for a setup.py, because
    a PEP 517 frontend installs that list into an isolated environment
    before setup.py is imported. Reading only `[project]` made the right
    answer look like the defect."""
    pyproject = (
        '[build-system]\nrequires = ["setuptools>=68"]\n\n' + PYPROJECT
    )
    root = _repo(tmp_path, pyproject=pyproject,
                 files={"setup.py": SETUP_PY.format(description="demo")})
    summaries = " ".join(f.summary for f in _scan(root))
    assert "setuptools" not in summaries


def test_a_runtime_module_importing_a_build_requirement_is_still_undeclared(tmp_path):
    """The exemption is for build-time files only. Consent to install a
    package before the build is not a declaration that it will be there at
    import time, and treating it as one would hide a real ImportError."""
    pyproject = (
        '[build-system]\nrequires = ["setuptools>=68"]\n\n' + PYPROJECT
    )
    root = _repo(tmp_path, pyproject=pyproject,
                 files={"demo/uses.py": "import setuptools\n"})
    undeclared = [f for f in _scan(root)
                  if f.attributes["kind"] == "undeclared dependency"]
    assert [f for f in undeclared if f.attributes["package"] == "setuptools"]


def test_setup_py_and_pyproject_disagreeing_is_major(tmp_path):
    """fortress-kernel's actual defect: two files declaring one package,
    with descriptions that had already drifted apart."""
    pyproject = (
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        'description = "a governance kernel"\n'
        'dependencies = ["requests>=2"]\n'
    )
    root = _repo(tmp_path, pyproject=pyproject, files={
        "setup.py": SETUP_PY.format(description="something else entirely")})
    hits = [f for f in _scan(root)
            if f.attributes["kind"] == "parallel packaging metadata"]
    assert len(hits) == 1
    assert hits[0].severity is Severity.MAJOR
    assert "description" in hits[0].attributes["drifted"]


def test_setup_py_and_pyproject_agreeing_is_minor_not_silent(tmp_path):
    """Agreement today is not a guarantee about tomorrow, and nothing in
    the repository checks that it holds. That is worth a MINOR and is not
    worth a MAJOR."""
    pyproject = (
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        'description = "d"\nrequires-python = ">=3.11"\n'
        'dependencies = ["requests>=2"]\n'
    )
    root = _repo(tmp_path, pyproject=pyproject,
                 files={"setup.py": SETUP_PY.format(description="d")})
    hits = [f for f in _scan(root)
            if f.attributes["kind"] == "parallel packaging metadata"]
    assert len(hits) == 1
    assert hits[0].severity is Severity.MINOR


def test_a_name_spelled_differently_is_not_drift(tmp_path):
    """PEP 503 says `Fortress_Kernel` and `fortress-kernel` are one
    package. Reporting that as disagreement would be reporting a spelling
    as a defect."""
    pyproject = '[project]\nname = "demo-pkg"\nversion = "0.1.0"\n'
    setup = 'from setuptools import setup\n\nsetup(name="Demo_Pkg", version="0.1.0")\n'
    root = _repo(tmp_path, pyproject=pyproject, files={"setup.py": setup})
    hits = [f for f in _scan(root)
            if f.attributes["kind"] == "parallel packaging metadata"]
    assert len(hits) == 1
    assert hits[0].severity is Severity.MINOR, hits[0].summary


def test_a_computed_value_is_not_compared_because_it_is_not_a_declaration(tmp_path):
    """A version read at import time is not something this scan can read.
    Comparing it against anything would manufacture the disagreement."""
    setup = ('from setuptools import setup\n\n'
             'setup(name="demo", version=open("VERSION").read())\n')
    root = _repo(tmp_path, files={"setup.py": setup})
    hits = [f for f in _scan(root)
            if f.attributes["kind"] == "parallel packaging metadata"]
    assert len(hits) == 1
    assert hits[0].attributes["fields"] == "name"


def test_no_setup_py_means_nothing_to_compare(tmp_path):
    root = _repo(tmp_path)
    assert "parallel packaging metadata" not in _kinds(_scan(root))


def test_packaging_drift_is_reported_even_when_no_module_was_scanned(tmp_path):
    """The check reads two files, so it is knowable when nothing parsed.
    Behind the no-modules guard it would be an unreported blind spot in a
    repository whose every source file is unassessable."""
    pyproject = (
        '[project]\nname = "demo"\nversion = "0.1.0"\ndescription = "a"\n'
    )
    root = _repo(tmp_path, pyproject=pyproject, files={
        "setup.py": SETUP_PY.format(description="b")})
    model = build_model(root, [])
    assert not model.modules
    kinds = _kinds(derive_findings(model))
    assert "parallel packaging metadata" in kinds
