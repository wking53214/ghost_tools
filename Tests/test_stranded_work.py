"""Tests for tools/stranded_work.sh.

The script's whole value is that it is quiet. If it reports commits that are
in fact safely on GitHub, it becomes a daily false alarm and someone stops
reading it -- at which point it is worse than not existing, because it looks
like coverage.

So the property under test is not "does it find stranded commits" but "does it
stay silent about commits that are not stranded".
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "stranded_work.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not SCRIPT.exists(),
    reason="needs git and the script",
)


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def run_check(root: Path, report: Path):
    """Returns (exit_code, output). Exit 1 means something was reported."""
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(root),
             "STRANDED_ROOT": str(root), "STRANDED_REPORT": str(report)},
    )
    return proc.returncode, proc.stdout


def make_clone(root: Path, name: str) -> Path:
    origin = root / f"{name}-origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work = root / name
    subprocess.run(["git", "clone", "-q", str(origin), str(work)],
                   capture_output=True, check=True)
    git("config", "user.email", "t@example.com", cwd=work)
    git("config", "user.name", "t", cwd=work)
    (work / "a.txt").write_text("base\n")
    git("add", ".", cwd=work)
    git("commit", "-qm", "base", cwd=work)
    git("push", "-q", "origin", "HEAD:main", cwd=work)
    git("branch", "--set-upstream-to=origin/main", cwd=work)
    return work


def test_silent_when_everything_is_pushed(tmp_path):
    make_clone(tmp_path, "clean")
    code, out = run_check(tmp_path, tmp_path / "report.txt")
    assert code == 0, f"reported something about a fully-pushed repo:\n{out}"
    assert not (tmp_path / "report.txt").exists()


def test_reports_a_commit_that_is_on_no_remote(tmp_path):
    work = make_clone(tmp_path, "stranded")
    (work / "b.txt").write_text("unpushed\n")
    git("add", ".", cwd=work)
    git("commit", "-qm", "UNPUSHED work", cwd=work)

    code, out = run_check(tmp_path, tmp_path / "report.txt")
    assert code == 1
    assert "stranded" in out
    # Naming the commit is the difference between a warning and an action.
    assert "UNPUSHED work" in out


def test_a_commit_reachable_only_from_a_pushed_tag_is_not_stranded(tmp_path):
    """The false positive that would have made this unreadable.

    `git rev-list --not --remotes` compares against remote BRANCHES only, so a
    commit that lives off-branch but carries a pushed tag looks stranded and is
    not. During the audit that prompted this script, that misreported three
    repositories -- including 66 commits in one -- all of them safely on
    GitHub the whole time.
    """
    work = make_clone(tmp_path, "tagged")
    (work / "c.txt").write_text("tagged\n")
    git("add", ".", cwd=work)
    git("commit", "-qm", "only a tag points here", cwd=work)
    git("tag", "v1", cwd=work)
    git("push", "-q", "origin", "v1", cwd=work)
    git("reset", "-q", "--hard", "HEAD~1", cwd=work)   # off-branch now

    code, out = run_check(tmp_path, tmp_path / "report.txt")
    assert code == 0, (
        "a commit whose tag is pushed was reported as stranded -- this is the "
        f"false positive the --tags flag exists to prevent:\n{out}"
    )


def test_a_repo_with_no_remote_is_reported(tmp_path):
    """Everything in a remoteless repo is a single copy, which is the worst
    case of all and the cheapest to detect."""
    work = tmp_path / "orphan"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    git("config", "user.email", "t@example.com", cwd=work)
    git("config", "user.name", "t", cwd=work)
    (work / "a.txt").write_text("x\n")
    git("add", ".", cwd=work)
    git("commit", "-qm", "solo", cwd=work)

    code, out = run_check(tmp_path, tmp_path / "report.txt")
    assert code == 1
    assert "NO REMOTE" in out


def test_claude_checkpoint_refs_are_not_reported(tmp_path):
    """Claude Code writes refs/claude/* rate-limit checkpoints. They are
    tool-internal, recreated constantly, and were the only thing this script
    reported on its first real run across 37 repositories."""
    work = make_clone(tmp_path, "checkpointed")
    (work / "d.txt").write_text("wip\n")
    git("add", ".", cwd=work)
    git("commit", "-qm", "WIP: Claude Code rate-limit checkpoint", cwd=work)
    sha = git("rev-parse", "HEAD", cwd=work).stdout.strip()
    git("update-ref", "refs/claude/checkpoint-abc123", sha, cwd=work)
    git("reset", "-q", "--hard", "HEAD~1", cwd=work)

    code, out = run_check(tmp_path, tmp_path / "report.txt")
    assert code == 0, f"a Claude Code checkpoint ref was reported:\n{out}"
