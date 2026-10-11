"""What the Graveyard says has been retired.

The Graveyard keeps one folder per source repo and one folder per burial
inside it, named `<date>-<what>`. A burial named `...-full-retirement` is a
whole repo retired (snapshot, full history bundle, BURIAL.md). Anything else
is part of a repo buried while the repo lives on.

Names are compared without regard to case, because the Graveyard folder is
`augur` and the repo was `Augur`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

WHOLE_SUFFIX = "full-retirement"


@dataclass(frozen=True)
class Burials:
    read: bool
    whole: Dict[str, str] = field(default_factory=dict)
    partial: Dict[str, int] = field(default_factory=dict)

    def retired_on(self, repo: str) -> str:
        """The date the whole repo was retired, or an empty string."""
        return self.whole.get(repo.casefold(), "")


def read_graveyard(path: Path) -> Burials:
    """A Graveyard folder that is missing reads as `read=False`, not as
    "nothing retired": the census says it could not look."""
    if not path.is_dir():
        return Burials(read=False)
    whole: Dict[str, str] = {}
    partial: Dict[str, int] = {}
    for repo_dir in sorted(p for p in path.iterdir() if p.is_dir() and p.name != ".git"):
        key = repo_dir.name.casefold()
        for burial in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
            if burial.name.endswith(WHOLE_SUFFIX):
                whole[key] = burial.name[:10]
            else:
                partial[key] = partial.get(key, 0) + 1
    return Burials(read=True, whole=whole, partial=partial)
