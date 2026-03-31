from __future__ import annotations

import os
from pathlib import Path

from .._version import __version__
from ..release_version import parse_python_release_version
from .constants import _REPL_EXTRA


def _binary_dir(env_dir: Path) -> Path:
    return env_dir / ("Scripts" if os.name == "nt" else "bin")


def _binary_path(env_dir: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return _binary_dir(env_dir) / f"{name}{suffix}"


def _python_path(env_dir: Path) -> Path:
    return _binary_path(env_dir, "python")


def _activate_path(env_dir: Path) -> Path:
    if os.name == "nt":
        return _binary_dir(env_dir) / "activate.bat"
    return _binary_dir(env_dir) / "activate"


def _env_root_for_python(python_path: Path) -> Path | None:
    # Do not resolve symlinks here: venv/bin/python commonly points at a base
    # interpreter, and resolving it would lose the virtualenv bin/Scripts parent.
    candidate = python_path.expanduser().absolute()
    if candidate.parent.name.lower() not in {"bin", "scripts"}:
        return None
    env_dir = candidate.parent.parent
    if (env_dir / "pyvenv.cfg").exists():
        return env_dir
    return None


def _repo_storage_root(repo_root: Path) -> Path:
    return repo_root / ".frida-analykit"


def _global_storage_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "frida-analykit"


def _repo_install_source(repo_root: Path | None) -> str:
    if repo_root is not None and (repo_root / "pyproject.toml").exists():
        return str(repo_root)
    package_root = Path(__file__).resolve().parents[3]
    if (package_root / "pyproject.toml").exists():
        return str(package_root)
    release = parse_python_release_version(__version__)
    return f"git+https://github.com/ZSA233/frida-analykit@{release.tag}"


def _install_requirement(source: str, *, with_repl: bool) -> str:
    if not with_repl:
        return source
    if Path(source).exists():
        return f"{source}[{_REPL_EXTRA}]"
    return f"frida-analykit[{_REPL_EXTRA}] @ {source}"
