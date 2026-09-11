"""README.md makes two mechanical claims about itself, and both are checked
here rather than promised:

  * the table under "What it checks" lists every registered detector, by
    name, and nothing that is not one;
  * every `--flag` the ghost_buster half of the README mentions exists in
    ghost_buster/cli.py's parser, so a flag cannot be documented after it is
    removed, or invented in prose (a `--semantic` flag was, for four
    versions).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import pathlib
import re

from ghost_buster.mechanical import registered_detectors

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()


def _section(title: str, until: str) -> str:
    start = README.index(f"## {title}")
    return README[start:README.index(f"## {until}", start)]


def test_the_inventory_table_names_every_registered_detector_and_no_other():
    table = _section("What it checks", "What it remembers")
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", table, re.M))
    registered = set(registered_detectors())
    assert documented == registered, (
        f"undocumented: {sorted(registered - documented)}; "
        f"documented but not registered: {sorted(documented - registered)}"
    )


def _cli_flags() -> set:
    """Every option string the real parser accepts, --no-X forms included."""
    from ghost_buster import cli
    captured = {}
    real = argparse.ArgumentParser.add_argument

    def spy(self, *names, **kw):
        for n in names:
            if n.startswith("--"):
                captured[n] = kw
        return real(self, *names, **kw)

    argparse.ArgumentParser.add_argument = spy
    try:
        # the parser is built inside main(); --help exits after building it
        with contextlib.suppress(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            cli.main(["--help"])
    finally:
        argparse.ArgumentParser.add_argument = real
    flags = set(captured)
    for n, kw in captured.items():
        if kw.get("action") is argparse.BooleanOptionalAction:
            flags.add("--no-" + n[2:])
    flags.add("--help")
    return flags


# flags of other programs the ghost_buster section quotes in prose
_FOREIGN = {
    "--prune", "--redact", "--source",                 # git, gitleaks
    "--reconstruct-into", "--recover-from", "--recover-into",  # blackhole-extrapolator, in the tree table
}


def test_every_flag_the_ghost_buster_section_mentions_exists():
    section = README[: README.index("## ghost_writer")]
    mentioned = set(re.findall(r"`(--[a-z][a-z0-9-]*)", section))
    unknown = mentioned - _cli_flags() - _FOREIGN
    assert not unknown, f"README mentions flags the CLI does not have: {sorted(unknown)}"


def test_the_defaults_table_agrees_with_the_parser():
    """Each 'on' row's decline flag must be a real --no-X; the parser's own
    ON BY DEFAULT help text is the second witness."""
    table = _section("What runs by default", "What it checks")
    declines = set(re.findall(r"\| on \| `(--no-[a-z-]+)` \|", table))
    assert declines, "the defaults table lost its shape"
    assert declines <= _cli_flags(), sorted(declines - _cli_flags())
