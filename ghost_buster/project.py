"""project.py -- repository-shaped facts that no single file can show.

WHY THIS IS NOT A `mechanical.py` DETECTOR

Every detector in mechanical.py is handed a list of .py and .md files.
The facts here are about what is NOT in that list -- a Dockerfile, a
.github/workflows directory, a Jenkinsfile -- so a file-list detector
structurally cannot see them. This module takes the root instead, the
same shape branches.py and secrets.py already use.

WHY "NO CI" IS NOT THE FINDING

"This repository has no continuous integration" is true of a great many
repositories that are fine: a scratch pad, a spike, a corpus of sample
data. Reporting all of them is how a tool teaches you to ignore it.

What is worth saying is narrower and lands harder:

  * You wrote tests and nothing runs them. Somebody spent the effort,
    and the effort only pays on every commit rather than the one
    afternoon it was written. MINOR.
  * This thing deploys and nothing checks it first. A Dockerfile, a
    Procfile, a fly.toml -- an artifact whose whole purpose is to put
    the code somewhere real, with no gate in front of it. MAJOR.

A repository with neither tests nor a deploy artifact gets nothing said
about it, which is the correct amount.

THE SECOND CHECK: A TEST RUNNER POINTED AT NOTHING

`test_config_collects_nothing` is the same shape of defect one level in.
A suite that nobody runs is bad; a suite that a runner is configured to
run, and silently does not, is worse, because the configuration is the
receipt that somebody thought about it.

pytest's `testpaths` names where to look when no path is given on the
command line. When every entry names something that is not there, pytest
does not fail -- it warns once and falls back to searching the working
directory, or, depending on version and invocation, collects nothing and
exits green. Both readings are bad and one of them is silent: a CI job
whose whole purpose is to run the tests passes in four seconds having run
none of them, and the badge is the same colour either way.

This is a static check: it reads configuration and asks whether the paths
exist. It never runs pytest, so it holds for an untrusted repository where
the test scan is declined, which is exactly where nobody is going to
notice by watching the output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "no_ci_configuration"
TEST_CONFIG_DETECTOR = "test_config_collects_nothing"

#: Single files whose presence is a CI configuration.
_CI_FILES = (
    ".gitlab-ci.yml", ".gitlab-ci.yaml", "Jenkinsfile", "azure-pipelines.yml",
    ".travis.yml", "bitbucket-pipelines.yml", ".drone.yml", "appveyor.yml",
    ".woodpecker.yml", "cloudbuild.yaml", "codeship-steps.yml",
)

#: Directories that are a CI configuration only if they actually contain
#: something. An empty .github/workflows looks exactly like CI from the
#: outside and runs nothing, which is worse than having neither.
_CI_DIRS = (
    (".github/workflows", ("*.yml", "*.yaml")),
    (".circleci", ("config.yml", "config.yaml")),
    (".buildkite", ("*.yml", "*.yaml")),
)

#: Artifacts whose entire purpose is to put this code somewhere real.
_DEPLOY_ARTIFACTS = (
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Procfile",
    "fly.toml", "vercel.json", "netlify.toml", "serverless.yml", "app.yaml",
    "render.yaml", "railway.json", "heroku.yml",
)

#: Recursive on purpose. A repository whose tests live at
#: src/thing/tests/test_x.py is a common layout, and a root-anchored
#: glob reports it as having no tests at all -- which would then read
#: as "nothing here needs CI" and say nothing. `_SKIP_PARTS` below is
#: what keeps this from counting a vendored dependency's own suite,
#: and it is load-bearing precisely because the walk is recursive.
_TEST_GLOBS = ("**/test_*.py", "**/*_test.py")

#: Never descended into when looking for tests: a vendored dependency's
#: own suite is not this repository's tests.
_SKIP_PARTS = frozenset({
    ".git", ".venv", "venv", "node_modules", "site-packages", "build", "dist",
    ".tox", ".nox", "__pycache__", ".mypy_cache", ".pytest_cache", "legacy",
})


#: Where pytest reads `testpaths` from, and how to get at it. pytest
#: itself reads the FIRST of these that exists and contains a `[pytest]`
#: section (or the tool table, for pyproject.toml), so the order matters
#: and is pytest's, not ours.
_PYTEST_CONFIG_FILES = ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")


@dataclass
class TestConfig:
    """`testpaths` as configured, and which of them exist on disk."""
    source: str = ""                                    # the file it came from
    paths: List[str] = field(default_factory=list)      # as written
    missing: List[str] = field(default_factory=list)    # of those, not on disk

    @property
    def collects_nothing(self) -> bool:
        """Every configured path is absent, so the configuration points at
        no test at all. A partially missing path is a different, smaller
        problem and is reported at a lower severity, not here."""
        return bool(self.paths) and len(self.missing) == len(self.paths)


@dataclass
class ProjectReport:
    ran: bool = False
    reason: str = ""
    ci_config: Optional[str] = None     # the file/dir that counts as CI, if any
    deploy_artifacts: List[str] = field(default_factory=list)
    test_files: int = 0
    test_config: Optional[TestConfig] = None

    @property
    def has_ci(self) -> bool:
        return self.ci_config is not None


def _clean(path: Path) -> bool:
    return _SKIP_PARTS.isdisjoint(path.parts)


def find_ci_config(root: Path) -> Optional[str]:
    """The first thing that genuinely configures CI, or None.

    A directory only counts when it holds at least one config file: an
    empty .github/workflows is the shape of CI with none of the substance,
    and treating it as configured would hide exactly the repository most
    likely to need this finding.
    """
    for name in _CI_FILES:
        if (root / name).is_file():
            return name
    for rel, patterns in _CI_DIRS:
        d = root / rel
        if not d.is_dir():
            continue
        for pattern in patterns:
            if any(d.glob(pattern)):
                return rel
    return None


def find_deploy_artifacts(root: Path) -> List[str]:
    return [name for name in _DEPLOY_ARTIFACTS if (root / name).is_file()]


def count_test_files(root: Path) -> int:
    seen = set()
    for pattern in _TEST_GLOBS:
        for p in root.glob(pattern):
            if p.is_file() and p.suffix == ".py" and _clean(p.relative_to(root)):
                seen.add(p.resolve())
    return len(seen)


def _testpaths_from_ini(text: str, section: str) -> Optional[List[str]]:
    """`testpaths` out of an ini-style file, or None when the section is
    absent. None and [] are different answers: no section means pytest
    reads no testpaths from this file at all, an empty value means it was
    configured to look nowhere."""
    import configparser

    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    if not parser.has_option(section, "testpaths"):
        return None
    return parser.get(section, "testpaths").split()


def read_test_config(root: Path) -> Optional[TestConfig]:
    """pytest's `testpaths`, from the first file that declares it.

    Returns None when no file configures testpaths, which is the common
    and correct case: pytest then searches from the invocation directory
    and there is nothing to be wrong about.
    """
    for name in _PYTEST_CONFIG_FILES:
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        paths: Optional[List[str]] = None
        if name == "pyproject.toml":
            import tomllib
            try:
                data = tomllib.loads(text)
            except (tomllib.TOMLDecodeError, ValueError):
                continue
            table = ((data.get("tool") or {}).get("pytest") or {}).get("ini_options")
            if isinstance(table, dict) and "testpaths" in table:
                value = table["testpaths"]
                paths = [str(v) for v in value] if isinstance(value, list) \
                    else str(value).split()
        else:
            paths = _testpaths_from_ini(
                text, "tool:pytest" if name == "setup.cfg" else "pytest")
        if paths is None:
            continue
        missing = [entry for entry in paths if not (root / entry).exists()]
        return TestConfig(source=name, paths=paths, missing=missing)
    return None


def _finding(root: Path, kind: str, severity: Severity, summary: str, detail: str,
             attributes: dict, detector: str = DETECTOR) -> Finding:
    return Finding(
        detector=detector, category=Category.ARCHITECTURE, layer=Layer.MECHANICAL,
        severity=severity, status=Status.CONFIRMED,
        summary=f"{kind}: {summary}",
        evidence=Evidence(file=str(root)),
        detail=detail,
        attributes=dict(attributes, kind=kind),
        # A project finding is about a property of the repository: it has no
        # CI, or it has no packaging. The summary then counts what is
        # affected ("3 test file(s) exist and nothing runs them"), and that
        # number moves whenever anybody adds a file. The KIND is the defect.
        # See `Finding.identity_key`.
        identity_key=kind,
    )


def _test_config_findings(root: Path, report: ProjectReport) -> List[Finding]:
    config = report.test_config
    if config is None or not config.missing:
        return []
    if not report.test_files:
        # No tests anywhere, so `testpaths` naming a directory that does
        # not exist yet is a plan, not a defect. Reporting it would be
        # reporting an empty repository for being empty.
        return []
    written = ", ".join(config.paths)
    absent = ", ".join(config.missing)
    if config.collects_nothing:
        return [_finding(
            root, "tests nobody can collect", Severity.MAJOR,
            f"{config.source} sets testpaths to {written}, none of which "
            f"exists, while {report.test_files} test file(s) are in the tree",
            "A bare `pytest` in this repository does not run these tests. "
            "pytest reads `testpaths` when no path is given on the command "
            "line, finds nothing at any of them, and -- depending on version "
            "and invocation -- either warns once and falls back to searching "
            "the working directory, or collects nothing and exits 0.\n\n"
            "The second outcome is the one that costs money. A CI job whose "
            "whole purpose is to run the suite passes in seconds having run "
            "none of it, and a green check for zero tests is indistinguishable "
            "from a green check for all of them. The fallback is not a "
            "safety net either: it makes the suite pass locally, where "
            "somebody is watching, and not in CI, where nobody is.\n\n"
            "The fix is to point `testpaths` at where the tests actually "
            "are, or to delete the setting, which restores the search pytest "
            "does by default.",
            {"source": config.source, "testpaths": written, "missing": absent,
             "test_files": str(report.test_files)},
            detector=TEST_CONFIG_DETECTOR,
        )]
    return [_finding(
        root, "a configured test path is missing", Severity.MINOR,
        f"{config.source} sets testpaths to {written}, and {absent} "
        f"does not exist",
        "The suite still runs: the remaining paths exist and pytest "
        "collects from them. What is gone is whatever used to be at the "
        "missing entry -- either it moved and nobody updated the "
        "configuration, in which case those tests are now running only by "
        "the accident of living under another entry, or it was deleted and "
        "the configuration still claims it.\n\nThis is MINOR because "
        "nothing silently passes. It is reported because a stale path is "
        "how a configuration ends up naming nothing at all, one rename at "
        "a time.",
        {"source": config.source, "testpaths": written, "missing": absent,
         "test_files": str(report.test_files)},
        detector=TEST_CONFIG_DETECTOR,
    )]


def scan(root) -> Tuple[List[Finding], ProjectReport]:
    root = Path(root).resolve()
    report = ProjectReport()
    if not root.is_dir():
        report.reason = f"{root} is not a directory"
        return [], report

    report.ran = True
    report.ci_config = find_ci_config(root)
    report.deploy_artifacts = find_deploy_artifacts(root)
    report.test_files = count_test_files(root)
    report.test_config = read_test_config(root)

    findings: List[Finding] = _test_config_findings(root, report)

    if report.has_ci:
        # Whether the pipeline is any good is a different question and not
        # one a file listing can answer. Configured is configured.
        #
        # The test-configuration finding above is NOT subject to this: a
        # runner pointed at nothing is worse with CI than without, because
        # CI is what turns "collected no tests" into a green badge nobody
        # reads twice.
        return findings, report

    if report.deploy_artifacts:
        named = ", ".join(report.deploy_artifacts)
        findings.append(_finding(
            root, "deployable without CI", Severity.MAJOR,
            f"{named} ships this code somewhere, and no CI configuration runs "
            f"before it does",
            "An artifact whose entire purpose is to put the code somewhere real, "
            "with no automated gate in front of it. Every deploy is then as good "
            "as whatever was on the branch at the time, checked by whoever "
            "remembered to check. This is the cheapest finding in this tool to "
            "fix and among the most expensive to leave: a workflow that runs the "
            "existing tests on pull requests is usually a dozen lines.\n\n"
            "Not reported when any CI configuration exists, whatever it does -- "
            "judging a pipeline's quality is beyond what a file listing can say.",
            {"deploy_artifacts": named, "test_files": str(report.test_files)},
        ))

    if report.test_files:
        findings.append(_finding(
            root, "tests nobody runs", Severity.MINOR,
            f"{report.test_files} test file(s) exist and no CI configuration "
            f"runs them",
            "Somebody wrote these. Tests pay off on every commit rather than on "
            "the afternoon they were written, and without CI they only run when "
            "a person remembers -- which is exactly when the code is least "
            "likely to be broken, because they were already thinking about it.\n\n"
            "This is deliberately NOT reported as 'this repository has no CI'. "
            "Plenty of repositories are fine without it: a scratch pad, a spike, "
            "a corpus. The claim here is narrower and it is about wasted work "
            "already done, not about process for its own sake.",
            {"test_files": str(report.test_files)},
        ))

    return findings, report


def _render_test_config(report: ProjectReport) -> str:
    """The test-configuration check's own line. It prints on every run,
    including the runs where it found nothing: a reader cannot tell a
    configuration that was checked and is fine from one that was never
    looked at, and only one of those is information."""
    config = report.test_config
    if config is None:
        return ("ghost_buster: test configuration: no testpaths configured "
                "(pytest searches from where it is invoked)")
    written = ", ".join(config.paths) or "nothing"
    if not config.missing:
        return (f"ghost_buster: test configuration: {config.source} testpaths "
                f"({written}) all exist")
    absent = ", ".join(config.missing)
    return (f"ghost_buster: test configuration: {config.source} testpaths "
            f"({written}) -- {absent} does not exist")


def render_report(report: ProjectReport) -> str:
    if not report.ran:
        return f"ghost_buster: project scan did not run: {report.reason}"
    test_config = "\n" + _render_test_config(report)
    if report.has_ci:
        return (f"ghost_buster: project scan found CI configured "
                f"({report.ci_config}){test_config}")
    bits = []
    if report.deploy_artifacts:
        bits.append(f"{len(report.deploy_artifacts)} deploy artifact(s)")
    if report.test_files:
        bits.append(f"{report.test_files} test file(s)")
    if not bits:
        return ("ghost_buster: project scan found no CI, and nothing that "
                "needs it" + test_config)
    return (f"ghost_buster: project scan found no CI configuration, with "
            f"{' and '.join(bits)}{test_config}")
