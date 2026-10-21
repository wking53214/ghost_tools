"""A findings file or baseline that cannot be read is a usage error, not a crash.

`ghost-writer` and `ghost-triage --list` on an empty file, on text that is not
JSON or on `[1]` printed a raw traceback (JSONDecodeError, TypeError) and exited
1; `{}` was accepted as an empty result; `ghost-buster --baseline` on valid JSON
of the wrong shape (`[1,2]`) crashed with exit 3 ("internal error") where the
README says an unreadable baseline exits 2. `FindingSet.from_json` now accepts
exactly two shapes, a list of findings or an object whose `findings` member is
a list (`{"findings": []}` is valid, `{}` is not), and raises FindingSetError
(a ValueError) for everything else; each command reports it as exit 2.

ghost-writer and ghost-triage have no `--json` option, so for them the message
is one line on stderr; the `--json` error envelope is held for `ghost-buster`.
"""
from __future__ import annotations

import json

import pytest

from ghost_buster import cli as buster_cli
from ghost_buster.schema import Category, Evidence, Finding, FindingSet, FindingSetError, Layer, Severity, Status
from ghost_writer import cli as writer_cli
from ghost_writer import triage

QUIET = ["--no-branches", "--no-tests", "--no-secrets", "--no-project",
         "--no-correlate", "--no-ledger", "--no-structure", "--single-repo"]

BAD = {
    "empty file": "",
    "not json": "this is not json",
    "truncated json": '[{"detector": ',
    "a list of numbers": "[1]",
    "a list of numbers, two": "[1, 2]",
    "an empty object": "{}",
    "an object whose findings is not a list": '{"findings": 5}',
    "a number": "7",
    "a string": '"findings"',
    "a finding missing its members": "[{}]",
    "a finding with an unknown severity": json.dumps([{
        "detector": "d", "category": "dead_code", "layer": "mechanical", "severity": "enormous",
        "status": "confirmed", "summary": "s", "evidence": {"file": "f.py"}}]),
}


def _finding():
    return Finding(detector="d", category=Category.DEAD_CODE, layer=Layer.MECHANICAL, severity=Severity.MAJOR,
                   status=Status.CONFIRMED, summary="s", evidence=Evidence(file="f.py", line_start=1))


def _tree(tmp_path):
    root = tmp_path / "tgt"
    root.mkdir()
    (root / "m.py").write_text("def used():\n    return 1\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("contents", BAD.values(), ids=BAD.keys())
def test_from_json_raises_one_error_type_for_every_bad_payload(contents):
    with pytest.raises(FindingSetError):
        FindingSet.from_json(contents)


def test_the_two_accepted_shapes_still_load():
    one = FindingSet([_finding()])
    assert len(FindingSet.from_json(one.to_json())) == 1
    assert len(FindingSet.from_json(json.dumps({"findings": json.loads(one.to_json())}))) == 1
    assert len(FindingSet.from_json("[]")) == 0
    assert len(FindingSet.from_json('{"findings": []}')) == 0


@pytest.mark.parametrize("contents", BAD.values(), ids=BAD.keys())
def test_ghost_writer_refuses_a_bad_findings_file_with_exit_2_and_one_line(tmp_path, capsys, contents):
    path = tmp_path / "f.json"
    path.write_text(contents, encoding="utf-8")
    assert writer_cli.main([str(path)]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "Traceback" not in err
    assert err.count("\n") == 1 and f"{path} is not a findings file" in err


@pytest.mark.parametrize("contents", BAD.values(), ids=BAD.keys())
@pytest.mark.parametrize("flags", [["--list"], []], ids=["list", "plain"])
def test_ghost_triage_refuses_a_bad_findings_file_with_exit_2_and_one_line(tmp_path, capsys, contents, flags):
    path = tmp_path / "f.json"
    path.write_text(contents, encoding="utf-8")
    assert triage.main([str(path), *flags]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "Traceback" not in err
    assert err.count("\n") == 1 and f"{path} is not a findings file" in err
    assert path.read_text(encoding="utf-8") == contents   # nothing was rewritten


def test_ghost_triage_set_on_a_bad_file_leaves_it_untouched(tmp_path, capsys):
    path = tmp_path / "f.json"
    path.write_text("{}", encoding="utf-8")
    assert triage.main([str(path), "--set", "abc=fix"]) == 2
    assert path.read_text(encoding="utf-8") == "{}"


def test_an_explicit_empty_findings_list_is_valid_for_both_commands(tmp_path, capsys):
    path = tmp_path / "f.json"
    path.write_text('{"findings": []}', encoding="utf-8")
    assert writer_cli.main([str(path)]) == 0
    assert triage.main([str(path), "--list"]) == 0
    assert "0 of 0 finding(s) awaiting a decision" in capsys.readouterr().out


def test_a_findings_file_that_is_not_utf8_is_also_a_usage_error(tmp_path, capsys):
    path = tmp_path / "f.json"
    path.write_bytes(b"\xff\xfe\x00bad")
    assert writer_cli.main([str(path)]) == 2
    assert triage.main([str(path), "--list"]) == 2
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("contents", BAD.values(), ids=BAD.keys())
def test_ghost_buster_refuses_a_baseline_of_the_wrong_shape_with_exit_2(tmp_path, capsys, contents):
    base = tmp_path / "b.json"
    base.write_text(contents, encoding="utf-8")
    rc = buster_cli.main([str(_tree(tmp_path)), *QUIET, "--baseline", str(base)])
    out, err = capsys.readouterr()
    assert rc == buster_cli.EXIT_USAGE == 2
    assert f"baseline {base} could not be read" in err
    assert "Traceback" not in err and "internal error" not in err
    assert out == ""


@pytest.mark.parametrize("contents", BAD.values(), ids=BAD.keys())
def test_under_json_a_bad_baseline_is_the_error_envelope(tmp_path, capsys, contents):
    base = tmp_path / "b.json"
    base.write_text(contents, encoding="utf-8")
    rc = buster_cli.main([str(_tree(tmp_path)), *QUIET, "--json", "--baseline", str(base)])
    out, err = capsys.readouterr()
    payload = json.loads(out)
    assert rc == 2
    assert payload["status"] == "error" and payload["exit_code"] == 2
    assert payload["error"]["kind"] == "usage" and "could not be read" in payload["error"]["message"]
    assert payload["findings"] == []
    assert "Traceback" not in err
