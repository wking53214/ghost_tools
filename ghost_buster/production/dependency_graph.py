"""Dependency graph. Zero static refs → DEAD_CANDIDATE."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DeadCandidate:
    path: str
    static_refs: int
    dynamic_hints: list[str] = field(default_factory=list)
    reason: str = "zero static references"

class DependencyGraph:
    def __init__(self):
        self.file_imports: dict[str, set[str]] = {}
        self.referenced_by: dict[str, set[str]] = {}
        self.files: set[str] = set()
    def analyze_file(self, path: Path):
        key = str(path)
        self.files.add(key)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.file_imports[key] = imported
        for mod in imported:
            self.referenced_by.setdefault(mod, set()).add(key)
    def analyze_tree(self, root: Path, pattern="**/*.py"):
        for p in root.glob(pattern):
            if ".git" not in p.parts:
                self.analyze_file(p)
    def static_ref_count(self, name: str) -> int:
        return len(self.referenced_by.get(name, set()))
    def dead_candidates(self, module_names: list[str]):
        out = []
        for name in module_names:
            if self.static_ref_count(name) == 0:
                out.append(DeadCandidate(name, 0,
                    ["reflection", "plugin", "string import", "entry point"],
                    "zero static references — DEAD_CANDIDATE not DEAD"))
        return out
