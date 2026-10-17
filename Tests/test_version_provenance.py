"""The version on a piece of evidence is the version that produced it.

`__version__` is stamped into every ledger run as `tool_version`, so it is
not a cosmetic string: it is the claim a later reader uses to decide which
implementation produced a finding. It used to read installed distribution
metadata first, which describes whatever was installed once -- not the code
the interpreter imported. Measured: with a fake `ghost-tools 9.9.9`
distribution on the path and the 1.2.4 source imported, the package
reported 9.9.9, and a ledger written from that run would have said so.

The source checkout now answers first. An installed wheel has no
pyproject.toml beside the package, so metadata still answers there, and it
is the right answer: nothing else is running.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _clean_source(tmp_path, root=ROOT):
    """A copy of the code under test with nothing built beside it.

    These tests put a fake `ghost-tools 9.9.9` distribution on the path and
    then import the real source in front of it. `importlib.metadata` finds a
    distribution by scanning every path entry, and the source tree is a path
    entry: after `pip install .` it holds a `ghost_tools.egg-info` (and
    `build/`) describing the real, installed version, which then answers
    "what is installed?" before the fake one does. The test then failed
    with `1.9.1 != 9.9.9`, in a tree where nothing was wrong.

    So the tests import a copy that contains exactly the package and
    pyproject.toml, which is what they mean by "the running source", and
    never any build output. Whether the checkout has been built or not no
    longer matters to them.
    """
    src = tmp_path / "source_copy"
    shutil.copytree(root / "ghost_buster", src / "ghost_buster",
                    ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    shutil.copy(root / "pyproject.toml", src / "pyproject.toml")
    return src


def _fake_distribution(tmp_path, version="9.9.9"):
    """Metadata for a ghost-tools that is not the code under test."""
    site = tmp_path / "site"
    dist = site / f"ghost_tools-{version}.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: ghost-tools\nVersion: {version}\n")
    (dist / "RECORD").write_text("")
    (dist / "INSTALLER").write_text("test\n")
    return site


def _declared() -> str:
    import tomllib
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def test_the_running_source_wins_over_installed_metadata(tmp_path):
    site = _fake_distribution(tmp_path)
    source = _clean_source(tmp_path)
    probe = tmp_path / "probe.py"
    probe.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(site)!r})
        sys.path.insert(0, {str(source)!r})
        from importlib.metadata import version
        import ghost_buster
        print(version("ghost-tools"), ghost_buster.__version__)
    """))
    out = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    metadata_says, package_says = out.stdout.split()
    assert metadata_says == "9.9.9", "the fixture is meant to install a different version"
    assert package_says == _declared(), (
        "the package reported the installed distribution's version while running this source; "
        "a ledger written from such a run names an implementation that did not produce it"
    )


def test_the_ledger_records_the_version_of_the_code_that_ran(tmp_path):
    """End to end, through the CLI, which is where the stamp is written."""
    target = tmp_path / "repo"
    target.mkdir()
    (target / "m.py").write_text("def f():\n    return 1\n")
    site = _fake_distribution(tmp_path)
    source = _clean_source(tmp_path)

    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "PYTHONPATH": f"{site}:{source}", "GHOST_TOOLS_TRUST": "-"}
    subprocess.run(
        [sys.executable, "-m", "ghost_buster.cli", str(target), "--no-tests", "--no-branches",
         "--single-repo", "--no-correlate", "--no-secrets", "--ledger"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=300)

    ledger = json.loads((target / ".ghost_ledger.json").read_text())
    assert ledger["runs"], "the scan recorded no run"
    assert ledger["runs"][-1]["tool_version"] == _declared()


def test_these_tests_do_not_depend_on_a_built_tree(tmp_path):
    """Plant exactly what `pip install .` leaves in a source tree (an
    `*.egg-info` that names a different version, and `build/`) and show that
    the copy the tests import carries none of it, and that the package still
    reports the source's own version beside a fake distribution.

    Before `_clean_source`, the two tests above failed whenever the checkout
    had been installed non-editably, because the planted egg-info answered
    `importlib.metadata.version("ghost-tools")` ahead of the fake."""
    built = tmp_path / "built_tree"
    shutil.copytree(ROOT / "ghost_buster", built / "ghost_buster",
                    ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    shutil.copy(ROOT / "pyproject.toml", built / "pyproject.toml")
    egg = built / "ghost_tools.egg-info"
    egg.mkdir()
    (egg / "PKG-INFO").write_text("Metadata-Version: 2.1\nName: ghost-tools\nVersion: 0.0.1\n")
    (built / "build" / "lib").mkdir(parents=True)

    clean = _clean_source(tmp_path / "scratch", root=built)

    assert not list(clean.glob("*.egg-info")) and not (clean / "build").exists()
    site = _fake_distribution(tmp_path)
    probe = tmp_path / "probe.py"
    probe.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(site)!r})
        sys.path.insert(0, {str(clean)!r})
        from importlib.metadata import version
        import ghost_buster
        print(version("ghost-tools"), ghost_buster.__version__)
    """))
    out = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    metadata_says, package_says = out.stdout.split()
    assert metadata_says == "9.9.9" and package_says == _declared()


def test_the_two_tests_above_pass_in_a_tree_that_has_been_built(tmp_path):
    """The same file, run for real in a copy of the checkout that carries
    `ghost_tools.egg-info` and `build/` at its root, as it does after
    `pip install .` from the source tree. This is the situation that used to
    fail; it is exercised, not argued."""
    tree = tmp_path / "built"
    (tree / "Tests").mkdir(parents=True)
    shutil.copytree(ROOT / "ghost_buster", tree / "ghost_buster",
                    ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    shutil.copy(ROOT / "pyproject.toml", tree / "pyproject.toml")
    shutil.copy(ROOT / "Tests" / "test_version_provenance.py", tree / "Tests" / "test_version_provenance.py")
    egg = tree / "ghost_tools.egg-info"
    egg.mkdir()
    declared = _declared()
    (egg / "PKG-INFO").write_text(f"Metadata-Version: 2.1\nName: ghost-tools\nVersion: {declared}\n")
    (tree / "build" / "lib").mkdir(parents=True)

    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n0",
         "-k", "not built", "Tests/test_version_provenance.py"],
        cwd=tree, capture_output=True, text=True, timeout=300,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-500:]
    assert "2 passed" in done.stdout, done.stdout[-500:]
