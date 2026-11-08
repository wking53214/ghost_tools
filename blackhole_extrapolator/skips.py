"""Records of input the blackhole tools saw but did not use.

Both ends of the tool read a lot of files and quietly set some aside: an
unreadable file, a bad line in a JSONL export, a directory that is never
descended into, a module whose dangling-name check is switched off by a
wildcard import. Each is a reasonable choice. None left a trace, so a result
could not be told apart from a result with an unknown amount of input missing.

These types carry that trace. They are passed in or returned alongside the
existing results and change none of them. Standard library only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

UNREADABLE_FILE = "unreadable_file"
BAD_JSONL_LINE = "bad_jsonl_line"


@dataclass(frozen=True)
class Skip:
    kind: str
    where: str
    reason: str = ""


@dataclass
class SkipLog:
    skips: list[Skip] = field(default_factory=list)

    def note(self, kind: str, where: str, reason: str = "") -> None:
        self.skips.append(Skip(kind, where, reason))

    def counts(self) -> dict[str, int]:
        return dict(Counter(s.kind for s in self.skips))

    def __len__(self) -> int:
        return len(self.skips)

    def __bool__(self) -> bool:  # an empty log is still a log
        return True


@dataclass(frozen=True)
class ScanReport:
    """What a scan read and what it left out.

    files_scanned: Python files analysed.
    excluded: directory name -> number of .py files under it that were never
        read, for the directories scans never descend into (build, dist, env,
        and so on). Nothing here is an error; it is the part of the tree the
        result says nothing about.
    wildcard_modules: files that were read but skipped by the dangling-name
        check because a wildcard import means any name might be bound.
    """

    files_scanned: int = 0
    excluded: dict[str, int] = field(default_factory=dict)
    wildcard_modules: tuple[str, ...] = ()
