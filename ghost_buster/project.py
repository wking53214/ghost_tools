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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .schema import Category, Evidence, Finding, Layer, Severity, Status

DETECTOR = "no_ci_configuration"

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


@dataclass
class ProjectReport:
    ran: bool = False
    reason: str = ""
    ci_config: Optional[str] = None     # the file/dir that counts as CI, if any
    deploy_artifacts: List[str] = field(default_factory=list)
    test_files: int = 0

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


def _finding(root: Path, kind: str, severity: Severity, summary: str, detail: str,
             attributes: dict) -> Finding:
    return Finding(
        detector=DETECTOR, category=Category.ARCHITECTURE, layer=Layer.MECHANICAL,
        severity=severity, status=Status.CONFIRMED,
        summary=f"{kind}: {summary}",
        evidence=Evidence(file=str(root)),
        detail=detail,
        attributes=dict(attributes, kind=kind),
    )


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

    if report.has_ci:
        # Whether the pipeline is any good is a different question and not
        # one a file listing can answer. Configured is configured.
        return [], report

    findings: List[Finding] = []

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


def render_report(report: ProjectReport) -> str:
    if not report.ran:
        return f"ghost_buster: project scan did not run: {report.reason}"
    if report.has_ci:
        return f"ghost_buster: project scan found CI configured ({report.ci_config})"
    bits = []
    if report.deploy_artifacts:
        bits.append(f"{len(report.deploy_artifacts)} deploy artifact(s)")
    if report.test_files:
        bits.append(f"{report.test_files} test file(s)")
    if not bits:
        return "ghost_buster: project scan found no CI, and nothing that needs it"
    return f"ghost_buster: project scan found no CI configuration, with {' and '.join(bits)}"
