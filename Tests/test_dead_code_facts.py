"""dead_code findings carry the facts a fixer needs, measured by Ghost."""

from ghost_buster.mechanical import detect_dead_code


def test_dead_code_reports_name_span_and_hook_flag(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "def pytest_sessionstart(s):\n    pass\n\n\ndef helper():\n    return 1\n", encoding="utf-8")
    found = {f.attributes["name"]: f for f in detect_dead_code([tmp_path / "conftest.py"])}
    helper, hook = found["helper"], found["pytest_sessionstart"]
    assert helper.attributes == {"name": "helper", "kind": "function", "line_start": "5",
                                 "line_end": "6", "framework_hook": "no"}
    assert (helper.evidence.line_start, helper.evidence.line_end) == (5, 6)
    assert hook.attributes["framework_hook"] == "yes"


def test_a_pytest_name_outside_conftest_is_not_flagged_as_a_hook(tmp_path):
    (tmp_path / "util.py").write_text("def pytest_helper():\n    return 1\n", encoding="utf-8")
    (finding,) = detect_dead_code([tmp_path / "util.py"])
    assert finding.attributes["framework_hook"] == "no"


def test_a_class_is_reported_as_a_class(tmp_path):
    (tmp_path / "m.py").write_text("class Thing:\n    x = 1\n", encoding="utf-8")
    (finding,) = detect_dead_code([tmp_path / "m.py"])
    assert finding.attributes["kind"] == "class"
