"""Poison files, size limits, named skips, git hardening, JSON hygiene, NFC ids."""
from __future__ import annotations

import json
import os
import subprocess
import unicodedata

import pytest

from ghost_buster import cli as buster_cli
from ghost_buster import corpus

BASE = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
        "--no-correlate", "--no-structure", "--single-repo"]


def _run(args, capsys):
    rc = buster_cli.main(args)
    out, err = capsys.readouterr()
    return rc, out, err


def _scan(root, capsys, *extra):
    rc, out, err = _run([str(root), *BASE, "--json", *extra], capsys)
    return rc, json.loads(out), err


# -- 4. one poison file ----------------------------------------------------

def test_a_deeply_nested_file_is_unassessable_and_the_scan_continues(tmp_path, capsys):
    (tmp_path / "ok.py").write_text("def orphan_ok():\n    return 1\n")
    poison = "x = 1" + "+1" * 300000 + "\n"
    try:
        import ast
        ast.parse(poison)
        pytest.skip("this Python parses the poison file")
    except RecursionError:
        pass
    (tmp_path / "poison.py").write_text(poison)
    rc, env, _ = _scan(tmp_path, capsys)
    assert env["status"] == "incomplete"
    bad = {u["file"]: u["reason"] for u in env["scan"]["unparsable"]}
    assert "poison.py" in bad
    assert any(f["summary"].startswith("'orphan_ok'") for f in env["findings"])


def test_a_recursion_error_from_the_parser_is_a_reason_not_a_crash(tmp_path, monkeypatch):
    p = tmp_path / "m.py"
    p.write_text("x = 1\n")

    def boom(*a, **k):
        raise RecursionError("maximum recursion depth exceeded")
    monkeypatch.setattr(corpus.ast, "parse", boom)
    src = corpus._read(p)
    assert src.tree is None and src.failure.startswith("RecursionError")


def test_a_memory_error_from_the_parser_is_a_reason_not_a_crash(tmp_path, monkeypatch):
    p = tmp_path / "m.py"
    p.write_text("x = 1\n")

    def boom(*a, **k):
        raise MemoryError()
    monkeypatch.setattr(corpus.ast, "parse", boom)
    assert corpus._read(p).failure.startswith("MemoryError")


def test_a_file_over_the_limit_is_not_read(tmp_path, capsys, monkeypatch):
    (tmp_path / "ok.py").write_text("def orphan_ok():\n    return 1\n")
    (tmp_path / "big.py").write_text("x = 1\n" + "# pad\n" * 5000)
    reads = []
    real = type(tmp_path / "big.py").read_bytes

    def spy(self):
        reads.append(self.name)
        return real(self)
    monkeypatch.setattr(type(tmp_path), "read_bytes", spy)
    rc, env, _ = _scan(tmp_path, capsys, "--max-file-size", "10K")
    assert "big.py" not in reads
    row = next(u for u in env["scan"]["unparsable"] if u["file"] == "big.py")
    assert row["reason"].startswith("too large")
    assert env["scan"]["max_file_bytes"] == 10 * 1024
    assert env["status"] == "incomplete"


def test_the_default_limit_is_five_megabytes():
    assert getattr(corpus, 'DEFAULT_MAX_FILE_BYTES', None) == 5 * 1024 * 1024


# -- 5. named skips --------------------------------------------------------

def test_skipped_directories_are_named_with_counts(tmp_path, capsys):
    (tmp_path / "ok.py").write_text("def orphan_ok():\n    return 1\n")
    (tmp_path / "node_modules" / "a").mkdir(parents=True)
    (tmp_path / "node_modules" / "a" / "x.py").write_text("y = 1\n")
    (tmp_path / "node_modules" / "z.md").write_text("hi\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "b.py").write_text("y = 1\n")
    rc, env, err = _scan(tmp_path, capsys)
    rows = {r["name"]: r for r in env["scan"]["skipped_dirs"]}
    assert rows["node_modules"] == {"name": "node_modules", "dirs": 1, "files": 2}
    assert rows["build"]["files"] == 1
    assert "skipped directories" in err and "node_modules" in err


def test_the_skipped_list_is_capped_but_counts_are_not(tmp_path, capsys):
    (tmp_path / "ok.py").write_text("def orphan_ok():\n    return 1\n")
    extras = []
    for i in range(30):
        d = tmp_path / f"vendor{i}"
        d.mkdir()
        (d / "v.py").write_text("y = 1\n")
        extras.append(f"vendor{i}")
    rc, env, _ = _run_json_with_excludes(tmp_path, capsys, extras)
    assert len(env["scan"]["skipped_dirs"]) == 20
    assert env["scan"]["skipped_dirs_more"] == 10


def _run_json_with_excludes(root, capsys, names):
    args = [str(root), *BASE, "--json"]
    for n in names:
        args += ["--exclude", n]
    rc, out, err = _run(args, capsys)
    return rc, json.loads(out), err


def test_files_behind_a_symlinked_directory_are_counted_as_skipped(tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o1.py").write_text("y = 1\n")
    (outside / "o2.py").write_text("y = 2\n")
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ok.py").write_text("def orphan_ok():\n    return 1\n")
    os.symlink(outside, root / "linked")
    from ghost_buster.pipeline import _collect_detail
    found = _collect_detail(root)
    assert found.symlinked_dirs == [("linked", 2)]
    rc, env, _ = _scan(root, capsys)
    assert env["scan"]["symlinked_dirs"] == [{"path": "linked", "files": 2}]


def test_a_symlink_to_a_directory_inside_the_tree_is_not_a_skip(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "r.py").write_text("y = 1\n")
    os.symlink(tmp_path / "real", tmp_path / "alias")
    from ghost_buster.pipeline import _collect_detail
    found = _collect_detail(tmp_path)
    assert found.symlinked_dirs == []
    assert [p.name for p in found.files] == ["r.py"]


def test_a_scan_that_analysed_no_python_is_not_ok(tmp_path, capsys):
    (tmp_path / "README.md").write_text("# hi\n")
    rc, env, _ = _scan(tmp_path, capsys)
    assert env["status"] == "incomplete"
    row = next(u for u in env["unmeasured"] if u["check"] == "python")
    assert "no Python file was analysed" in row["reason"] and row["by_request"] is False
    assert env["scan"]["python_files_analysed"] == 0


def test_a_scan_where_every_python_file_is_unparsable_is_not_ok(tmp_path, capsys):
    (tmp_path / "bad.py").write_text("def (:\n")
    rc, env, _ = _scan(tmp_path, capsys)
    assert env["status"] == "incomplete"
    assert any(u["check"] == "python" for u in env["unmeasured"])


# -- 3. git hardening ------------------------------------------------------

def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_every_git_command_is_hardened():
    from ghost_buster import gitsafe
    argv = gitsafe.command("diff", "a", "b", root="/x")
    for token in ("--no-optional-locks", "--no-pager", "diff.external=", "core.fsmonitor=false",
                  "core.hooksPath=/dev/null", "protocol.ext.allow=never",
                  "--no-ext-diff", "--no-textconv"):
        assert token in argv
    e = gitsafe.env({"GIT_EXTERNAL_DIFF": "evil", "GIT_SSH_COMMAND": "evil", "X": "1"})
    assert "GIT_EXTERNAL_DIFF" not in e and "GIT_SSH_COMMAND" not in e and e["X"] == "1"
    assert e["GIT_CONFIG_NOSYSTEM"] == "1" and e["GIT_OPTIONAL_LOCKS"] == "0"


def test_a_target_diff_external_does_not_run_during_a_branch_scan(tmp_path, capsys):
    root = tmp_path / "tgt"
    root.mkdir()
    marker = tmp_path / "PWNED"
    _git(root, "init", "-q", "-b", "main")
    (root / "m.py").write_text("def a():\n    return 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "one")
    _git(root, "checkout", "-q", "-b", "feature")
    (root / "m.py").write_text("def a():\n    return 2\n")
    _git(root, "commit", "-qam", "two")
    _git(root, "checkout", "-q", "main")
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(0o755)
    _git(root, "config", "diff.external", str(script))
    _git(root, "config", "core.fsmonitor", f"touch {marker}; echo")
    _git(root, "config", "core.hooksPath", str(tmp_path / "hooks"))
    (root / ".gitattributes").write_text("*.py diff=evil\n")
    _git(root, "config", "diff.evil.textconv", str(script))
    rc, out, err = _run([str(root), "--no-tests", "--no-secrets", "--no-project", "--no-correlate",
                         "--no-structure", "--single-repo", "--json"], capsys)
    env = json.loads(out)
    assert any(f["detector"] == "unmerged_branch" for f in env["findings"]), err
    assert not marker.exists()


# -- 6. JSON hygiene -------------------------------------------------------

def test_ctrl_c_gives_130_and_an_error_envelope(tmp_path, capsys, monkeypatch):
    (tmp_path / "m.py").write_text("x = 1\n")

    def interrupt(args):
        raise KeyboardInterrupt
    monkeypatch.setattr(buster_cli, "gather", interrupt)
    rc, out, err = _run([str(tmp_path), *BASE, "--json"], capsys)
    env = json.loads(out)
    assert rc == 130 and env["status"] == "error" and env["exit_code"] == 130
    assert env["error"]["kind"] == "interrupted" and "interrupted" in err


def test_stray_prints_during_a_json_scan_do_not_reach_stdout(tmp_path, capsys, monkeypatch):
    (tmp_path / "m.py").write_text("def orphan():\n    return 1\n")
    real = buster_cli.gather

    def noisy(args):
        print("some library chatter")
        return real(args)
    monkeypatch.setattr(buster_cli, "gather", noisy)
    rc, out, err = _run([str(tmp_path), *BASE, "--json"], capsys)
    json.loads(out)
    assert "chatter" in err and "chatter" not in out


def test_verify_chain_under_json_uses_the_envelope(tmp_path, capsys):
    (tmp_path / "m.py").write_text("def orphan():\n    return 1\n")
    buster_cli.main([str(tmp_path), *BASE, "--ledger"])
    capsys.readouterr()
    rc, out, err = _run([str(tmp_path), "--verify-chain", "--json"], capsys)
    env = json.loads(out)
    assert rc == 0 and env["status"] == "ok" and env["chain"]["broken"] is False
    assert env["chain"]["runs"] == 1


def test_verify_chain_with_no_ledger_under_json_is_an_error_envelope(tmp_path, capsys):
    (tmp_path / "m.py").write_text("x = 1\n")
    rc, out, err = _run([str(tmp_path), "--verify-chain", "--json"], capsys)
    env = json.loads(out)
    assert rc == 2 and env["status"] == "error"


def test_verify_chain_does_not_scan(tmp_path, capsys):
    (tmp_path / "m.py").write_text("x = 1\n")
    rc, out, err = _run([str(tmp_path), "--verify-chain", "--json"], capsys)
    assert "scanning" not in err


def test_priors_json_stays_a_bare_list_and_is_valid(tmp_path, capsys):
    (tmp_path / "m.py").write_text("x = 1\n")
    rc, out, err = _run([str(tmp_path), "--priors", "--json"], capsys)
    assert rc == 0 and json.loads(out) == []


# -- 7. NFC ids ------------------------------------------------------------

def _finding(path):
    from ghost_buster.schema import Category, Evidence, Finding, Layer, Severity, Status
    return Finding(detector="dead_code", category=Category.DEAD_CODE, layer=Layer.MECHANICAL,
                   severity=Severity.MINOR, status=Status.CONFIRMED, summary="'f' is dead",
                   evidence=Evidence(file=path))


def test_the_same_file_in_nfc_and_nfd_has_one_id():
    nfc = unicodedata.normalize("NFC", "café/m.py")
    nfd = unicodedata.normalize("NFD", "café/m.py")
    assert nfc != nfd
    assert _finding(nfc).id == _finding(nfd).id


def test_the_id_an_nfd_path_had_before_is_still_recognised():
    from ghost_buster.schema import _stable_id
    nfd = unicodedata.normalize("NFD", "café/m.py")
    f = _finding(nfd)
    old = _stable_id("dead_code", nfd, "'f' is dead")
    assert old != f.id and old in f.previous_ids


def test_a_baseline_written_under_the_old_nfd_id_still_matches(tmp_path):
    from ghost_buster.baseline import Baseline
    from ghost_buster.schema import _stable_id, FindingSet
    nfd = unicodedata.normalize("NFD", "café/m.py")
    f = _finding(nfd)
    old = _stable_id("dead_code", nfd, "'f' is dead")
    stale = _finding(nfd)
    stale.id = old
    fs = FindingSet()
    fs.add(stale)
    path = tmp_path / "b.json"
    path.write_text(fs.to_json())
    new, known = Baseline(path).diff([f])
    assert known == [f] and new == []


# -- 3b. gitleaks gets the same hardening ----------------------------------

def test_gitleaks_runs_with_hardened_git_settings(tmp_path):
    from ghost_buster import secrets
    root = tmp_path / "tgt"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "m.py").write_text("x = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "one")
    log = tmp_path / "gitleaks.log"
    fake = tmp_path / "gitleaks"
    fake.write_text(
        "#!/bin/sh\n"
        f"echo \"$@\" >> {log}\n"
        f"echo \"CFG=$GIT_CONFIG_COUNT $GIT_CONFIG_KEY_0=$GIT_CONFIG_VALUE_0 EXT=$GIT_EXTERNAL_DIFF\" >> {log}\n"
        "if [ \"$1\" = version ]; then echo 8.28.0; exit 0; fi\n"
        "while [ $# -gt 0 ]; do if [ \"$1\" = --report-path ]; then echo '[]' > \"$2\"; fi; shift; done\n"
        "exit 0\n")
    fake.chmod(0o755)
    os.environ["GIT_EXTERNAL_DIFF"] = "/bin/evil"
    try:
        secrets.scan(root, gitleaks_path=str(fake), timeout=30)
    finally:
        del os.environ["GIT_EXTERNAL_DIFF"]
    text = log.read_text()
    assert "--no-ext-diff --no-textconv" in text and "--full-history --all" in text
    assert "diff.external=" in text and "EXT=\n" in text
