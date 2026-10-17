"""CI installs gitleaks only if the download is the one the workflow names.

`.github/scripts/install-gitleaks.sh VERSION SHA256` used to be two inline curl
and tar lines with no check at all. A replaced release asset would have been
run by the job. These tests build a fake release on disk (curl reads file://)
and hold the three outcomes: the right digest installs, a wrong one exits 1 and
installs nothing, a malformed digest is refused before any download.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import subprocess
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "install-gitleaks.sh"
WORKFLOW = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
VERSION = "9.9.9"


def _release(tmp_path):
    """A release folder laid out like GitHub's: <base>/v<version>/gitleaks_<version>_linux_x64.tar.gz."""
    payload = tmp_path / "payload"
    payload.mkdir()
    binary = payload / "gitleaks"
    binary.write_text("#!/bin/sh\necho fake-gitleaks\n", encoding="utf-8")
    binary.chmod(0o755)
    folder = tmp_path / "release" / f"v{VERSION}"
    folder.mkdir(parents=True)
    archive = folder / f"gitleaks_{VERSION}_linux_x64.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(binary, arcname="gitleaks")
    return tmp_path / "release", hashlib.sha256(archive.read_bytes()).hexdigest()


def _install(tmp_path, base, digest):
    dest = tmp_path / "bin"
    dest.mkdir(exist_ok=True)
    env = {**os.environ, "GITLEAKS_BASE_URL": base.as_uri()}
    result = subprocess.run(["bash", str(SCRIPT), VERSION, digest, str(dest)], env=env, capture_output=True, text=True)
    return result, dest / "gitleaks"


def test_the_published_digest_installs(tmp_path):
    base, digest = _release(tmp_path)
    result, installed = _install(tmp_path, base, digest)
    assert result.returncode == 0, result.stderr
    assert installed.is_file() and "fake-gitleaks" in result.stdout


def test_a_different_digest_fails_the_job_and_installs_nothing(tmp_path):
    base, digest = _release(tmp_path)
    wrong = ("0" if digest[0] != "0" else "1") + digest[1:]
    result, installed = _install(tmp_path, base, wrong)
    assert result.returncode == 1
    assert "sha256 mismatch" in result.stderr and "Nothing was installed" in result.stderr
    assert not installed.exists()


def test_a_malformed_digest_is_refused(tmp_path):
    base, _ = _release(tmp_path)
    result, installed = _install(tmp_path, base, "not-a-digest")
    assert result.returncode == 1 and not installed.exists()


def test_a_tampered_asset_with_the_old_digest_fails(tmp_path):
    base, digest = _release(tmp_path)
    archive = base / f"v{VERSION}" / f"gitleaks_{VERSION}_linux_x64.tar.gz"
    archive.write_bytes(archive.read_bytes() + b"tampered")
    result, installed = _install(tmp_path, base, digest)
    assert result.returncode == 1 and not installed.exists()


def test_both_workflow_jobs_install_through_the_script_with_one_published_digest():
    calls = re.findall(r"install-gitleaks\.sh (\d+\.\d+\.\d+) ([0-9a-f]{64})\b", WORKFLOW)
    assert len(calls) == 2 and len(set(calls)) == 1, calls
    assert "gitleaks/releases/download" not in WORKFLOW, "a raw download of gitleaks bypasses the checksum"
    assert os.access(SCRIPT, os.X_OK)
