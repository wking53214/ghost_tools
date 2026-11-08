"""A trusted scan runs the target's tests; it must not make them write into the target.

Red team: a trusted scan left `.benchmarks/` (pytest-benchmark) and a rewritten
`.git/index` in the target. Both are now prevented where we can: the benchmark
plugin is blocked, and git is told not to refresh the index. What the target's
own test code writes on purpose is its own business and is documented.
"""
from __future__ import annotations

import os
import subprocess
import sys

from ghost_buster import cli as buster_cli


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _target(tmp_path):
    root = tmp_path / "tgt"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "m.py").write_text("def f():\n    return 1\n")
    (root / "test_m.py").write_text(
        "import subprocess\nfrom m import f\n\n"
        "def test_f():\n"
        "    subprocess.run(['git', 'status'], capture_output=True)\n"
        "    assert f() == 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "one")
    return root


def _listing(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if ".git" not in p.parts)


def test_a_trusted_scan_leaves_no_benchmarks_dir_and_the_index_alone(tmp_path, monkeypatch, capsys):
    root = _target(tmp_path)
    # A stand-in for pytest-benchmark: registered under the name "benchmark",
    # creating `.benchmarks/` beside the tests the moment pytest starts.
    plug = tmp_path / "plug"
    plug.mkdir()
    (plug / "benchmark.py").write_text(
        "import os\n\ndef pytest_configure(config):\n    os.makedirs('.benchmarks', exist_ok=True)\n")
    monkeypatch.setenv("PYTHONPATH", str(plug) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setenv("PYTEST_PLUGINS", "benchmark")
    monkeypatch.setenv("GHOST_TOOLS_TRUST", "-")
    for name in ("m.py", "test_m.py"):
        os.utime(root / name, (1, 1))          # the index's stat data is now stale
    index = root / ".git" / "index"
    before_index = (index.read_bytes(), os.stat(index).st_mtime_ns)
    before = _listing(root)
    buster_cli.main([str(root), "--no-secrets", "--no-branches", "--single-repo",
                          "--tests-python", sys.executable])
    err = capsys.readouterr().err
    assert "test scan ran" in err, err
    assert _listing(root) == before
    assert not (root / ".benchmarks").exists()
    assert (index.read_bytes(), os.stat(index).st_mtime_ns) == before_index
