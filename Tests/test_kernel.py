"""--kernel PATH: the classes a repository carries that a shared kernel
already provides (ghost_buster/kernel.py)."""
from __future__ import annotations

import textwrap
from pathlib import Path

from ghost_buster.kernel import (
    DRIFTED_CONTRACT, KERNEL_SHADOW, check_kernel, load_kernel, render_report,
)

KERNEL = '''
class Node:
    """A vertex."""
    def __init__(self, name):
        self.name = name
    def key(self):
        return self.name

class Level:
    LOW = 1
    HIGH = 2

class Graph:
    def __init__(self):
        self.nodes = []
    def add(self, node):
        self.nodes.append(node)
    def count(self):
        return len(self.nodes)
'''


def _tree(tmp_path: Path, files: dict, kernel: str = KERNEL) -> tuple:
    kdir = tmp_path / "kernel" / "kern"
    kdir.mkdir(parents=True)
    (kdir / "core.py").write_text(textwrap.dedent(kernel))
    repo = tmp_path / "repo"
    repo.mkdir()
    out = []
    for name, src in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(src))
        out.append(p)
    return out, tmp_path / "kernel"


def test_an_identical_class_is_a_shadow_and_a_docstring_does_not_count(tmp_path):
    files, kernel = _tree(tmp_path, {"mine.py": '''
        class Node:
            """A different docstring entirely, and no other change."""
            def __init__(self, name):
                self.name = name
            def key(self):
                return self.name
    '''})
    findings, report = check_kernel(files, [kernel])
    assert [f.detector for f in findings] == [KERNEL_SHADOW]
    assert "import it instead" in findings[0].summary
    assert findings[0].attributes["class"] == "Node"
    assert report.shadows == 1 and report.drifted == 0 and report.collisions == 0


def test_a_changed_body_with_the_same_methods_is_a_drifted_contract(tmp_path):
    files, kernel = _tree(tmp_path, {"mine.py": '''
        class Graph:
            def __init__(self):
                self.nodes = []
            def add(self, node):
                if node not in self.nodes:
                    self.nodes.append(node)
            def count(self):
                return len(self.nodes)
    '''})
    findings, report = check_kernel(files, [kernel])
    assert [f.detector for f in findings] == [DRIFTED_CONTRACT]
    assert "3 of 3 kernel methods shared" in findings[0].summary
    assert "same members, different bodies" in findings[0].summary
    assert report.drifted == 1


def test_a_missing_method_is_named(tmp_path):
    files, kernel = _tree(tmp_path, {"mine.py": '''
        class Graph:
            def __init__(self):
                self.nodes = []
            def add(self, node):
                self.nodes.append(node)
            def total_row_count(self):
                return 0
    '''})
    findings, _ = check_kernel(files, [kernel])
    assert findings[0].detector == DRIFTED_CONTRACT
    assert "2 of 3 kernel methods shared" in findings[0].summary
    assert "count" in findings[0].summary and "total_row_count" in findings[0].summary


def test_an_enum_with_a_member_added_is_a_drifted_contract(tmp_path):
    files, kernel = _tree(tmp_path, {"mine.py": '''
        class Level:
            LOW = 1
            HIGH = 2
            CRITICAL = 3
    '''})
    findings, _ = check_kernel(files, [kernel])
    assert [f.detector for f in findings] == [DRIFTED_CONTRACT]
    assert "2 of 2 kernel members shared" in findings[0].summary


def test_a_same_name_class_unrelated_by_shape_is_silent_and_counted(tmp_path):
    files, kernel = _tree(tmp_path, {"mine.py": '''
        class Node:
            def render(self, canvas):
                canvas.draw(self)
            def bounds(self):
                return (0, 0, 1, 1)
    '''})
    findings, report = check_kernel(files, [kernel])
    assert findings == []
    assert report.collisions == 1
    assert "1 same-name class(es) unrelated by shape" in render_report(report)


def test_the_kernel_inside_the_scanned_tree_is_not_a_patient(tmp_path):
    files, kernel = _tree(tmp_path, {"mine.py": "x = 1\n"})
    vendored = tmp_path / "repo" / "vendor" / "kern"
    vendored.mkdir(parents=True)
    (vendored / "core.py").write_text((kernel / "kern" / "core.py").read_text())
    files.append(vendored / "core.py")
    findings, report = check_kernel(files, [tmp_path / "repo" / "vendor"])
    assert findings == []
    assert report.skipped_inside_kernel == 1
    assert "inside the kernel skipped" in render_report(report)


def test_test_files_are_left_alone(tmp_path):
    files, kernel = _tree(tmp_path, {"test_mine.py": KERNEL})
    findings, report = check_kernel(files, [kernel])
    assert findings == [] and report.shadows == 0


def test_a_kernel_name_defined_twice_has_no_one_shape(tmp_path):
    files, kernel = _tree(tmp_path, {"mine.py": '''
        class Node:
            def __init__(self, name):
                self.name = name
            def key(self):
                return self.name
    '''})
    (kernel / "kern" / "other.py").write_text("class Node:\n    pass\n")
    assert "Node" not in load_kernel(kernel)
    findings, _ = check_kernel(files, [kernel])
    assert findings == []


def test_a_kernel_path_that_is_not_a_directory_does_not_run(tmp_path):
    files, kernel = _tree(tmp_path, {"mine.py": "x = 1\n"})
    findings, report = check_kernel(files, [tmp_path / "nowhere"])
    assert findings == [] and report.ran is False
    assert "did not run" in render_report(report) and "nowhere" in report.reason


def test_the_finding_names_both_sides(tmp_path):
    files, kernel = _tree(tmp_path, {"mine.py": '''
        class Node:
            def __init__(self, name):
                self.name = name
            def key(self):
                return self.name
    '''})
    findings, _ = check_kernel(files, [kernel])
    f = findings[0]
    assert f.severity.value == "major" and f.status.value == "confirmed"
    assert f.evidence.file.endswith("mine.py")
    assert any(r.endswith("core.py") for r in f.evidence.related_files)
    assert "core.py" in f.detail


def test_the_cli_runs_it_only_when_asked(tmp_path, capsys):
    from ghost_buster.cli import main
    files, kernel = _tree(tmp_path, {"mine.py": '''
        class Node:
            def __init__(self, name):
                self.name = name
            def key(self):
                return self.name
    '''})
    quiet = ["--no-branches", "--no-tests", "--no-secrets", "--no-project", "--no-correlate",
             "--no-ledger", "--single-repo", "--json", "--baseline", str(tmp_path / "b.json")]
    main([str(tmp_path / "repo"), *quiet])
    out, err = capsys.readouterr()
    assert "kernel check NOT RUN (opt-in: --kernel PATH)" in err
    assert KERNEL_SHADOW not in out
    main([str(tmp_path / "repo"), *quiet, "--kernel", str(kernel)])
    out, err = capsys.readouterr()
    assert "kernel check against kernel (3 class(es)): 1 shadow(s)" in err
    assert KERNEL_SHADOW in out
