"""A baseline file that exists and is empty, for tests that need `--baseline` to point somewhere harmless.

Until 1.10.9 a `--baseline` path that did not exist was read as an empty baseline, so tests passed
`tmp_path / "b.json"` without creating it, only to keep the scan from reading a baseline found in the
scanned folder. A named baseline that is missing is now a usage error (exit 2), so those tests name a file
that exists and holds `[]`: the same empty baseline, written beside the test's folder and not inside it, so
a scan that starts at `tmp_path` does not see an extra file.
"""
from __future__ import annotations

from pathlib import Path


def empty_baseline(tmp_path: Path) -> str:
    path = tmp_path.parent / f"{tmp_path.name}-empty-baseline.json"
    path.write_text("[]", encoding="utf-8")
    return str(path)
