"""Consent before a scan runs somebody else's code.

A default run executes the target's test suite, and `--mutate` runs it
hundreds of times. Both are the right default for your own repositories
and the wrong one for a stranger's clone, where the only guard used to be
remembering `--no-tests`. The tool that refuses to hang a CI build should
refuse to run a stranger's code by accident.

So consent is recorded once, per repository, in a store that belongs to
the user rather than to the repository (a file inside the tree would be
the stranger's to write). A repository is identified by its `origin`
remote, normalised, so a fresh clone of a trusted repository is trusted;
a tree with no remote is identified by its resolved path.

    ghost-buster PATH --trust      records consent and proceeds
    ghost-buster PATH              runs code only if consent is on record
    GHOST_TOOLS_TRUST=-            trusts everything, for a test harness
                                   that scans its own fixtures; printed on
                                   the receipt line, never silent

An untrusted repository is not scanned less quietly: the test and
mutation scans are DECLINED with a receipt naming the store and the flag,
readiness reads the tests criterion as unknown, and the ledger ages the
gap like any other declined check.

WHAT IS TRUSTED, EXACTLY

A NAME, not a tree. Consent is recorded against the normalised origin
remote, so it covers every checkout of that remote, at any commit, with
any contents, forever. That is deliberate and it is the useful half: a
fresh clone of your own repository does not ask again, and a pull does
not invalidate a decision you already made.

The consequences follow from the same fact and are stated here rather
than discovered later:

  * A trusted repository whose contents change is still trusted. Pulling
    a commit, checking out a pull request, or editing the tree does not
    re-prompt.
  * A DIFFERENT checkout of the same remote inherits the grant, including
    one prepared by somebody else and handed to you.
  * An attacker who can change what a trusted remote's checkout contains
    -- push access, a merged pull request, a tarball you unpack over it
    -- gets their code executed by the next `--tests` or `--mutate` run.
    They need neither the trust store nor local privilege.
  * A tree with no remote is identified by its resolved path, so moving
    it revokes consent. That direction fails closed, which is why it is
    left as it is.

The model this assumes is "do I trust this project", the same question a
CI configuration answers when it runs a suite. It is NOT "do I trust this
exact code", which would require re-consent per commit and would make the
prompt worthless through repetition. If you need the stronger property,
the honest way to get it today is a scan with `--no-tests`, which
executes nothing regardless of consent.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

ENV = "GHOST_TOOLS_TRUST"
TRUST_ALL = "-"


def store_path() -> Path:
    """The trust store: $GHOST_TOOLS_TRUST if set (and not `-`), else
    ~/.config/ghost_tools/trust.json."""
    env = os.environ.get(ENV)
    if env and env != TRUST_ALL:
        return Path(env)
    return Path.home() / ".config" / "ghost_tools" / "trust.json"


def _normalise_remote(url: str) -> str:
    u = url.strip()
    if u.startswith("git@") and ":" in u:            # git@github.com:owner/repo.git
        host, _, rest = u[4:].partition(":")
        u = f"{host}/{rest}"
    for prefix in ("https://", "http://", "ssh://git@", "ssh://", "git://"):
        if u.startswith(prefix):
            u = u[len(prefix):]
            break
    if u.endswith(".git"):
        u = u[:-4]
    return u.rstrip("/").lower()


def identity(root: Path) -> str:
    """What consent is recorded against: the origin remote, normalised, or
    the resolved path when there is none."""
    try:
        r = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return _normalise_remote(r.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    return str(Path(root).resolve())


@dataclass(frozen=True)
class Trust:
    """The verdict, with the reason on it so the receipt can say why."""
    trusted: bool
    identity: str
    store: Optional[Path]
    reason: str


def _load(store: Path) -> Dict[str, dict]:
    try:
        data = json.loads(store.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def check(root: Path) -> Trust:
    if os.environ.get(ENV) == TRUST_ALL:
        return Trust(True, identity(root), None, f"everything ({ENV}={TRUST_ALL})")
    store = store_path()
    ident = identity(root)
    entry = _load(store).get(ident)
    if entry:
        when = str(entry.get("granted", ""))[:10]
        return Trust(True, ident, store, f"consent recorded {when}" if when else "consent recorded")
    return Trust(False, ident, store, f"{ident} is not in {store}")


def grant(root: Path) -> Trust:
    """Record consent for this repository and return the verdict."""
    store = store_path()
    ident = identity(root)
    data = _load(store)
    data[ident] = {"granted": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "path": str(Path(root).resolve())}
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_suffix(store.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, store)
    return Trust(True, ident, store, "consent recorded now (--trust)")


def declined_receipt(what: str, trust: Trust) -> str:
    return (f"ghost_buster: {what} DECLINED: it would execute this repository's code and "
            f"{trust.reason}. --trust records consent once; --no-tests declines on purpose.")
