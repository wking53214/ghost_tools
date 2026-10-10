"""Input the blackhole tools set aside now leaves a record.

Before this: an unreadable file or a bad JSONL line vanished from the corpus,
a directory such as `build` was never read and said nothing about it, a
wildcard import silently switched off a check for its module, and duplicate
candidates were detected with the builtin hash(), which is randomised per
process.
"""

import json
import subprocess
import sys
from pathlib import Path

from blackhole_extrapolator import scan, scan_with_report
from blackhole_extrapolator.recover import harvest
from blackhole_extrapolator.skips import BAD_JSONL_LINE, UNREADABLE_FILE, SkipLog

CODE = "def keep_me(a, b):\n    total = a + b\n    return total * 2\n\n\nclass Holder:\n    def go(self):\n        return keep_me(1, 2)\n"


def test_scan_with_report_returns_exactly_the_scan_evidence(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return missing_name\n")
    ev, _ = scan_with_report(tmp_path)
    assert [(e.kind, e.detail, e.line) for e in ev] == [(e.kind, e.detail, e.line) for e in scan(tmp_path)]


def test_report_counts_files_and_names_excluded_directories(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "b.py").write_text("y = 2\n")
    (tmp_path / "build" / "c.py").write_text("z = 3\n")
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "d.py").write_text("w = 4\n")
    _, report = scan_with_report(tmp_path)
    assert report.files_scanned == 1
    assert report.excluded == {"build": 2, "env": 1}


def test_report_names_modules_a_wildcard_import_switched_off(tmp_path):
    (tmp_path / "wild.py").write_text("from os.path import *\n\ndef f():\n    return undefined_thing\n")
    (tmp_path / "plain.py").write_text("def g():\n    return other_undefined\n")
    ev, report = scan_with_report(tmp_path)
    assert report.wildcard_modules == (str(tmp_path / "wild.py"),)
    # The skip is real: the wildcard module yields no dangling-name evidence.
    assert not any(e.file.endswith("wild.py") and "undefined_thing" in e.detail for e in ev)


def test_an_unparsable_file_is_not_called_a_wildcard_module(tmp_path):
    (tmp_path / "broken.py").write_text("def f(:\n")
    assert scan_with_report(tmp_path)[1].wildcard_modules == ()


def test_a_bad_jsonl_line_is_recorded_not_just_dropped(tmp_path):
    good = json.dumps({"text": CODE})
    (tmp_path / "chat.jsonl").write_text(f"{good}\nnot json at all\n\n{good}\n")
    log = SkipLog()
    sources = harvest([tmp_path], log)
    assert log.counts() == {BAD_JSONL_LINE: 1}
    assert log.skips[0].where.endswith("chat.jsonl:2")
    assert [s.text for s in sources] == [s.text for s in harvest([tmp_path])]


def test_an_unreadable_file_is_recorded(tmp_path, monkeypatch):
    (tmp_path / "ok.txt").write_text(CODE)
    (tmp_path / "locked.txt").write_text(CODE + "# different\n")
    real = Path.read_text

    def fake(self, *a, **kw):
        if self.name == "locked.txt":
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", fake)
    log = SkipLog()
    with_log = harvest([tmp_path], log)
    assert log.counts() == {UNREADABLE_FILE: 1}
    assert log.skips[0].where.endswith("locked.txt")
    assert with_log == harvest([tmp_path])


def test_duplicate_candidates_are_collapsed_the_same_way_in_every_process(tmp_path):
    (tmp_path / "one.txt").write_text(CODE)
    (tmp_path / "two.txt").write_text(CODE)
    script = (
        "import sys; from pathlib import Path; "
        "from blackhole_extrapolator.recover import harvest; "
        "print(len(harvest([Path(sys.argv[1])])))"
    )
    root = Path(__file__).resolve().parent.parent
    counts = {
        subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=root, env={"PYTHONHASHSEED": seed, "PATH": ""},
                       capture_output=True, text=True, check=False).stdout.strip()
        for seed in ("1", "2", "3")
    }
    assert counts == {"1"}


def test_lone_surrogates_in_json_do_not_crash_dedup(tmp_path):
    (tmp_path / "s.json").write_text('{"text": "def f():\\n    return \\ud800\\n    x = 1\\n    y = 2\\n"}')
    harvest([tmp_path])  # must not raise
