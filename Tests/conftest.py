"""Every test repository is built in isolation from whoever is running it.

WHY THIS EXISTS (v1.7.3)

Most of this suite builds real git repositories, because most of what the
tool does is about a repository. Those `git init` calls inherit the global
configuration of whatever machine the suite runs on, and that turned out to
include commit signing.

Measured: sixty tests failed at once, across `test_branches.py` and
`test_operate_restores.py`, with `git commit` exiting 128. Nothing in the
tool had changed. An external signer had run out of file descriptors
because an unrelated process on the same machine was holding them, and the
suite reported that as failures in branch scanning and operation recovery.

A test suite whose result depends on the developer's git configuration is
a test suite that cannot be trusted either way: green may mean the code is
right, and red may mean somebody's `~/.gitconfig` has an alias in it.

WHAT IS ISOLATED

`GIT_CONFIG_GLOBAL` points at an empty file and `GIT_CONFIG_NOSYSTEM`
turns off the system config, so a test repository sees only what the test
sets on it. That covers signing, but also hooks, aliases, `diff.renames`,
`init.defaultBranch`, autocrlf and everything else a person might have set
-- each of which could change a result here without anybody noticing which.

Identity is supplied because git refuses to commit without one. It is the
only thing put back.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _git_config_isolated(tmp_path_factory):
    empty = tmp_path_factory.mktemp("gitconfig") / "config"
    empty.write_text(
        "[user]\n\tname = ghost_buster tests\n\temail = tests@invalid\n"
        "[commit]\n\tgpgsign = false\n"
        "[tag]\n\tgpgsign = false\n",
        encoding="utf-8")
    previous = {key: os.environ.get(key) for key in
                ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
    os.environ["GIT_CONFIG_GLOBAL"] = str(empty)
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
