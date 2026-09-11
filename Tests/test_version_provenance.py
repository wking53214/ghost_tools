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
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    probe = tmp_path / "probe.py"
    probe.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(site)!r})
        sys.path.insert(0, {str(ROOT)!r})
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

    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "PYTHONPATH": f"{site}:{ROOT}", "GHOST_TOOLS_TRUST": "-"}
    subprocess.run(
        [sys.executable, "-m", "ghost_buster.cli", str(target), "--no-tests", "--no-branches",
         "--single-repo", "--no-correlate", "--no-secrets"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=300)

    ledger = json.loads((target / ".ghost_ledger.json").read_text())
    assert ledger["runs"], "the scan recorded no run"
    assert ledger["runs"][-1]["tool_version"] == _declared()
