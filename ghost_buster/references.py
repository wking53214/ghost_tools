"""references.py -- facts about names that code outside the Python call graph can reach.

The dead_code detector only sees names used by other Python code. A function
can also be reached by:

  - a console script or plugin entry point (pyproject.toml, setup.cfg, setup.py),
  - a string, such as getattr(mod, "handle_x") or a settings.yaml value,
  - a computed lookup (importlib.import_module(name)), which no static
    scan can resolve.

Everything here only READS. Ghost measures; a fixer decides. Each helper returns
plain facts, and says what it could not see.
"""

from __future__ import annotations

import ast
import configparser
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

_ROOT_MARKERS = ("pyproject.toml", "setup.cfg", "setup.py", ".git")
_CONFIG_EXTS = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".txt", ".conf", ".env"}
_CONFIG_DIRS = {"config", "configs", "conf", "settings", "etc", "deploy", "deployment",
                ".github", "ci", "resources", "data"}
#: Read structurally (entry points) instead of by word, so a same-named function in a
#: different module is not flagged just because the entry point line mentions the name.
_STRUCTURED = {"pyproject.toml", "setup.cfg"}
_MAX_BYTES = 1_000_000
_MAX_DEPTH = 3
_SKIP_DIRS = {".git", "venv", ".venv", "node_modules", "site-packages", "__pycache__", "build", "dist"}
_TARGET = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*:\s*([A-Za-z_][\w.]*)")
_SETUP_PY = re.compile(r"""["']\s*[\w.\-]+\s*=\s*([A-Za-z_][\w.]*)\s*:\s*([A-Za-z_][\w.]*)""")


#: Calls that read a namespace table by key: globals().get(name), sys.modules.get(name).
_TABLE_GETTERS = {"get", "pop", "setdefault", "__getitem__"}
_NAMESPACE_CALLS = {"globals", "vars", "locals"}


def _is_namespace(node) -> bool:
    """globals(), vars(...), locals(), sys.modules, anything.__dict__."""
    if isinstance(node, ast.Call):
        fn = node.func
        return isinstance(fn, ast.Name) and fn.id in _NAMESPACE_CALLS
    if isinstance(node, ast.Attribute):
        if node.attr == "__dict__":
            return True
        return node.attr == "modules" and isinstance(node.value, ast.Name) and node.value.id == "sys"
    return False


def _constant_prefix(key) -> str:
    """The literal text a computed key starts with, or ''."""
    if isinstance(key, ast.BinOp) and isinstance(key.op, (ast.Add, ast.Mod)):
        left = key.left
        if isinstance(left, ast.Constant) and isinstance(left.value, str):
            return left.value.split("%")[0]
        return _constant_prefix(left)
    if isinstance(key, ast.JoinedStr) and key.values:
        first = key.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    if isinstance(key, ast.Call) and isinstance(key.func, ast.Attribute) and key.func.attr == "format":
        base = key.func.value
        if isinstance(base, ast.Constant) and isinstance(base.value, str):
            return base.value.split("{")[0]
    return ""


def find_repo_root(files: Iterable[Path]) -> Optional[Path]:
    """Nearest folder at or above the scanned files holding a project marker, else None."""
    paths = [os.path.abspath(str(p)) for p in files]
    if not paths:
        return None
    try:
        common = os.path.commonpath([os.path.dirname(p) for p in paths])
    except ValueError:
        return None
    cur = Path(common)
    for candidate in (cur, *cur.parents):
        if any((candidate / m).exists() for m in _ROOT_MARKERS):
            return candidate
    return None


def _split_target(value: str) -> Optional[Tuple[str, str]]:
    m = _TARGET.match(value)
    if not m:
        return None
    return m.group(1), m.group(2).split(".")[0]  # 'Class.attr' names the class


def _read(path: Path) -> Optional[str]:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def entry_points(root: Path) -> Tuple[Dict[Tuple[str, str], str], List[str]]:
    """{(module, name): description} for every entry point target, plus notes on what was not read."""
    found: Dict[Tuple[str, str], str] = {}
    notes: List[str] = []

    def add(value, label):
        if isinstance(value, str) and (t := _split_target(value)):
            found.setdefault(t, label)

    pp = root / "pyproject.toml"
    if pp.is_file():
        try:
            import tomllib
        except ImportError:
            tomllib = None
            notes.append("pyproject.toml entry points not read: tomllib is missing on this Python (3.10)")
        if tomllib is not None:
            try:
                with pp.open("rb") as fh:
                    data = tomllib.load(fh)
            except (OSError, tomllib.TOMLDecodeError):
                data = {}
                notes.append("pyproject.toml could not be parsed, so its entry points were not read")
            project = data.get("project", {}) or {}
            poetry = (data.get("tool", {}) or {}).get("poetry", {}) or {}
            for key, kind in (("scripts", "console script"), ("gui-scripts", "gui script")):
                for k, v in (project.get(key) or {}).items():
                    add(v, f"pyproject.toml {kind} '{k}'")
            for group, table in (project.get("entry-points") or {}).items():
                for k, v in (table or {}).items():
                    add(v, f"pyproject.toml plugin entry point '{k}' in group '{group}'")
            for k, v in (poetry.get("scripts") or {}).items():
                add(v, f"pyproject.toml poetry script '{k}'")
            for group, table in (poetry.get("plugins") or {}).items():
                for k, v in (table or {}).items():
                    add(v, f"pyproject.toml poetry plugin '{k}' in group '{group}'")

    cfg = root / "setup.cfg"
    if cfg.is_file() and (text := _read(cfg)) is not None:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read_string(text)
            if parser.has_section("options.entry_points"):
                for group, block in parser.items("options.entry_points"):
                    for line in block.splitlines():
                        if "=" in line:
                            k, v = line.split("=", 1)
                            add(v, f"setup.cfg entry point '{k.strip()}' in group '{group}'")
        except configparser.Error:
            notes.append("setup.cfg could not be parsed, so its entry points were not read")

    sp = root / "setup.py"
    if sp.is_file() and (text := _read(sp)) is not None:
        # A regex over the text, not a run of setup.py: only literal 'name = mod:func' strings
        # are seen. Entry points built in code are not.
        for m in _SETUP_PY.finditer(text):
            found.setdefault((m.group(1), m.group(2).split(".")[0]), "setup.py entry point")
    return found, notes


def module_names_for(rel: Path, root: Path) -> Set[str]:
    """Dotted module names a file can be imported as: dropping leading folders that are
    not packages (src/, lib/) is allowed, dropping a package folder is not."""
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    out: Set[str] = set()
    for k in range(len(parts) + 1):
        if k and not all(not (root.joinpath(*parts[:i + 1], "__init__.py")).exists() for i in range(k)):
            break
        if parts[k:]:
            out.add(".".join(parts[k:]))
    return out


class ReferenceIndex:
    """Built once per scan. Only answers for names asked about."""

    def __init__(self, files: List[Path], parsed: Dict[Path, ast.AST], candidates: Set[str]):
        self.root = find_repo_root(files)
        self.candidates = candidates
        self.notes: List[str] = []
        self.entries: Dict[Tuple[str, str], str] = {}
        self.string_refs: Dict[str, str] = {}
        self.dynamic = 0
        #: Constant prefixes of computed names ("_cmd_" in globals()["_cmd_" + x]),
        #: {prefix: file}. A name starting with one is probably reached by it.
        self.prefix_refs: Dict[str, str] = {}
        self._file_modules: Dict[str, Set[str]] = {}
        if self.root is not None:
            self.entries, self.notes = entry_points(self.root)
            for p in files:
                self._file_modules[os.path.abspath(str(p))] = self._modules(Path(p))
        self._scan_python(parsed)
        if self.root is not None:
            self._scan_config()

    def _rel(self, path: Path) -> str:
        if self.root is not None:
            try:
                return Path(os.path.abspath(str(path))).relative_to(self.root).as_posix()
            except ValueError:
                pass
        return Path(path).name

    def _modules(self, path: Path) -> Set[str]:
        try:
            rel = Path(os.path.abspath(str(path))).relative_to(self.root)
        except ValueError:
            return set()
        return module_names_for(rel, self.root)

    def _scan_python(self, parsed: Dict[Path, ast.AST]) -> None:
        for path, tree in sorted(parsed.items(), key=lambda kv: str(kv[0])):
            rel = self._rel(path)

            def note(value):
                if isinstance(value, str) and value in self.candidates:
                    self.string_refs.setdefault(value, rel)

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    fname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
                    if fname in ("getattr", "hasattr", "setattr") and isinstance(fn, ast.Name) and len(node.args) >= 2:
                        arg = node.args[1]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            note(arg.value)
                        else:
                            self._computed(arg, rel)
                    elif fname in ("import_module", "__import__") and node.args:
                        arg = node.args[0]
                        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                            self.dynamic += 1
                    elif fname in _TABLE_GETTERS and isinstance(fn, ast.Attribute) \
                            and _is_namespace(fn.value) and node.args:
                        self._computed(node.args[0], rel)
                elif isinstance(node, ast.Subscript) and _is_namespace(node.value):
                    self._computed(node.slice, rel)
                elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                    for e in node.elts:
                        if isinstance(e, ast.Constant):
                            note(e.value)
                elif isinstance(node, ast.Dict):
                    for e in (*node.keys, *node.values):
                        if isinstance(e, ast.Constant):
                            note(e.value)

    def _computed(self, key, rel: str) -> None:
        """A lookup in a namespace table (globals(), vars(), locals(),
        sys.modules, obj.__dict__) by `key`. A literal string is a plain
        reference (the name is spelled out); anything else is a computed
        lookup no scan can resolve, and counts. A constant prefix
        (`"_cmd_" + x`, `f"_cmd_{x}"`) is remembered."""
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            if key.value in self.candidates:
                self.string_refs.setdefault(key.value, rel)
            return
        if isinstance(key, ast.Name) and key.id == "__name__":
            return                  # sys.modules[__name__]: this module, spelled out
        self.dynamic += 1
        prefix = _constant_prefix(key)
        if prefix and len(prefix) >= 2:
            self.prefix_refs.setdefault(prefix, rel)

    def _scan_config(self) -> None:
        for path in self._config_files():
            text = _read(path)
            if text is None:
                continue
            rel = path.relative_to(self.root).as_posix()
            for word in set(re.findall(r"\w+", text)):
                if word in self.candidates:
                    self.string_refs.setdefault(word, f"{rel}")

    def _config_files(self) -> List[Path]:
        out: List[Path] = []

        def wanted(p: Path) -> bool:
            n = p.name.lower()
            if "lock" in n or n in _STRUCTURED or n.startswith("requirements"):
                return False
            return p.suffix.lower() in _CONFIG_EXTS or n == ".env" or n.startswith(".env.")

        for entry in sorted(self.root.iterdir()):
            if entry.is_file() and wanted(entry):
                out.append(entry)
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and d.name.lower() in _CONFIG_DIRS and d.name not in _SKIP_DIRS:
                base = len(d.parts)
                for dirpath, dirs, names in os.walk(d):
                    dirs[:] = sorted(x for x in dirs if x not in _SKIP_DIRS)
                    if len(Path(dirpath).parts) - base >= _MAX_DEPTH:
                        dirs[:] = []
                    out.extend(Path(dirpath) / n for n in sorted(names) if wanted(Path(dirpath) / n))
        return out

    def referenced_by(self, name: str, path: Path) -> List[str]:
        """Every outside reference to this definition, as short plain strings."""
        why: List[str] = []
        if self.root is not None:
            mine = self._file_modules.get(os.path.abspath(str(path)), set())
            known = set().union(*self._file_modules.values()) if self._file_modules else set()
            for (module, target), label in self.entries.items():
                if target != name:
                    continue
                if module in mine:
                    why.append(label)
                elif module not in known and not self._module_on_disk(module):
                    why.append(f"{label} (module '{module}' not found, matched by name only)")
        if name in self.string_refs:
            why.append(f"named as a string in {self.string_refs[name]}")
        for prefix, where in sorted(self.prefix_refs.items()):
            if name.startswith(prefix):
                why.append(f"may be reached by a computed lookup with prefix '{prefix}' in {where}")
                break
        return why

    def _module_on_disk(self, module: str) -> bool:
        rel = Path(*module.split("."))
        for base in (self.root, self.root / "src", self.root / "lib"):
            if (base / rel).with_suffix(".py").is_file() or (base / rel / "__init__.py").is_file():
                return True
        return False
