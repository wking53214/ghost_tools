"""gitsafe.py -- every git command ghost_buster runs goes through here.

WHY THIS EXISTS

A scan points git at a folder somebody else wrote. A repository's own
`.git/config` is part of that folder, and git will run programs named in
it: `diff.external`, `core.fsmonitor`, `core.hooksPath`, textconv and
filter drivers, `core.sshCommand`, `ext::` transports. A read-only audit
that runs `git diff` in such a repository runs the repository's command.
Red team case: `diff.external` in `.git/config` wrote a marker file during
a branch scan.

WHAT IS DONE

  * Config that names a program is overridden on the command line, which
    wins over the repository's config: `diff.external=`,
    `core.fsmonitor=false`, `core.hooksPath=/dev/null`,
    `core.pager=cat`, `core.sshCommand=false`, `core.askPass=`,
    `protocol.ext.allow=never`, `protocol.allow=never` (nothing here ever
    needs the network).
  * Sub-commands that can apply a diff driver get `--no-ext-diff
    --no-textconv` (diff, show, log).
  * The environment is scrubbed of the variables that do the same thing
    from outside (`GIT_EXTERNAL_DIFF`, `GIT_SSH_COMMAND`, ...), the system
    config file is ignored (`GIT_CONFIG_NOSYSTEM=1`), no pager is started,
    no prompt is shown.
  * `GIT_OPTIONAL_LOCKS=0` and `--no-optional-locks`: git otherwise
    refreshes `.git/index` as a side effect of read-only commands, which
    is a write into the folder under audit.

WHAT IS NOT DONE

The user's own global git config (`~/.gitconfig`) is still read: it
belongs to the person running the scan, not to the target. Filter
drivers run by checkout (`filter.*.smudge`) cannot occur because no
command here checks anything out. gitleaks (secrets.py) is a separate
program that runs git itself; it gets the same scrubbed environment but
its own command line is not ours to harden.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

#: Global options, placed before the sub-command. `-c` beats the repo's config.
HARDENING: List[str] = [
    "--no-optional-locks",
    "--no-pager",
    "-c", "diff.external=",
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.pager=cat",
    "-c", "core.sshCommand=false",
    "-c", "core.askPass=",
    "-c", "protocol.ext.allow=never",
    "-c", "protocol.allow=never",
    "-c", "credential.helper=",
]

#: Sub-commands that take the diff-driver switches.
_DIFF_LIKE = frozenset({"diff", "show", "log"})

_DROP_ENV = (
    "GIT_EXTERNAL_DIFF", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND",
    "GIT_ASKPASS", "GIT_PAGER", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR",
    "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_WORK_TREE",
    "GIT_INDEX_FILE", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """`base` (default: os.environ) with the program-naming variables removed."""
    out = {k: v for k, v in (os.environ if base is None else base).items()
           if k not in _DROP_ENV}
    # The same overrides as environment config, for programs that run git
    # themselves (gitleaks) and so never see our command-line `-c` flags.
    pairs = [HARDENING[i + 1].split("=", 1) for i in range(len(HARDENING) - 1)
             if HARDENING[i] == "-c"]
    out["GIT_CONFIG_COUNT"] = str(len(pairs))
    for n, (key, value) in enumerate(pairs):
        out[f"GIT_CONFIG_KEY_{n}"] = key
        out[f"GIT_CONFIG_VALUE_{n}"] = value
    out["GIT_CONFIG_NOSYSTEM"] = "1"
    out["GIT_OPTIONAL_LOCKS"] = "0"
    out["GIT_TERMINAL_PROMPT"] = "0"
    out["GIT_PAGER"] = "cat"
    out["PAGER"] = "cat"
    return out


def command(*args: str, root: Optional[Path] = None) -> List[str]:
    """The full argv for `git <args>`, hardened. With `root`, `-C root` is
    added. Diff-capable sub-commands get --no-ext-diff and --no-textconv."""
    argv = ["git", *HARDENING]
    if root is not None:
        argv += ["-C", str(root)]
    args = list(args)
    if args and args[0] in _DIFF_LIKE:
        args[1:1] = ["--no-ext-diff", "--no-textconv"]
    return argv + args


def run(args, *, root: Optional[Path] = None, cwd=None, **kwargs) -> "subprocess.CompletedProcess":
    """subprocess.run for git. `args` is the sub-command and its arguments
    (no leading "git"). Any `env=` passed is scrubbed the same way."""
    kwargs["env"] = env(kwargs.get("env"))
    return subprocess.run(command(*args, root=root), cwd=cwd, **kwargs)
