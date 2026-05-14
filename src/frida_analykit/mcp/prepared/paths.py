from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from .constants import OUTPUT_TAIL_LINES


def default_prepared_cache_root() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return (base / "frida-analykit" / "mcp-prepared").expanduser().resolve()


def package_install_path(node_modules: Path, package_name: str) -> Path:
    if package_name.startswith("@"):
        scope, name = package_name.split("/", 1)
        return node_modules / scope / name
    return node_modules / package_name


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def tail_text(output: str) -> str:
    return "\n".join(output.splitlines()[-OUTPUT_TAIL_LINES:])
