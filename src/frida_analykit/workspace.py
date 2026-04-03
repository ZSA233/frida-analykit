from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

from .config import AppConfig

DEFAULT_WORKSPACE_DATADIR = "./data/"
DEFAULT_WORKSPACE_STDOUT = "./logs/outerr.log"
DEFAULT_WORKSPACE_DEXTOOLS_OUTPUT_DIR = "./data/dextools/"
DEFAULT_WORKSPACE_ELFTOOLS_OUTPUT_DIR = "./data/elftools/"
DEFAULT_WORKSPACE_SSL_LOG_SECRET = "./data/nettools/sslkey/"


@dataclass(frozen=True, slots=True)
class WorkspaceBuildResources:
    lock_path: Path
    npm_cache_dir: Path


class WorkspaceBuildLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: object | None = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a+", encoding="utf-8")
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX only
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX only
            pass
        else:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


def workspace_build_resources(
    root: str | Path,
    *,
    lock_filename: str = "workspace-build.lock",
    npm_cache_dirname: str = "npm-cache",
) -> WorkspaceBuildResources:
    base_dir = Path(root).expanduser().resolve()
    return WorkspaceBuildResources(
        lock_path=base_dir / lock_filename,
        npm_cache_dir=base_dir / npm_cache_dirname,
    )


def prepare_workspace_npm_env(
    base_env: Mapping[str, str] | None,
    resources: WorkspaceBuildResources,
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    _ensure_workspace_build_directory(resources.npm_cache_dir)
    env["npm_config_cache"] = str(resources.npm_cache_dir)
    return env


def acquire_workspace_build_lock(resources: WorkspaceBuildResources) -> WorkspaceBuildLock:
    lock = WorkspaceBuildLock(resources.lock_path)
    lock.acquire()
    return lock


def _ensure_workspace_build_directory(path: Path) -> None:
    if path.exists() and not path.is_dir():
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def write_workspace_config(
    config_path: str | Path,
    *,
    app: str | None,
    jsfile: str | Path,
    host: str,
    path: str = "frida-server",
    version: str | None = None,
    device: str | None = None,
    datadir: str | Path = DEFAULT_WORKSPACE_DATADIR,
    stdout: str | Path = DEFAULT_WORKSPACE_STDOUT,
    stderr: str | Path | None = None,
    dextools_output_dir: str | Path = DEFAULT_WORKSPACE_DEXTOOLS_OUTPUT_DIR,
    elftools_output_dir: str | Path = DEFAULT_WORKSPACE_ELFTOOLS_OUTPUT_DIR,
    ssl_log_secret: str | Path = DEFAULT_WORKSPACE_SSL_LOG_SECRET,
) -> AppConfig:
    config_file = Path(config_path).expanduser().resolve()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config = AppConfig.model_validate(
        {
            "app": app,
            "jsfile": str(jsfile),
            "server": {
                "host": host,
                "path": path,
                "version": version,
                "device": device,
            },
            "agent": {
                "datadir": str(datadir),
                "stdout": str(stdout),
                "stderr": str(stdout if stderr is None else stderr),
            },
            "script": {
                "dextools": {"output_dir": str(dextools_output_dir)},
                "elftools": {"output_dir": str(elftools_output_dir)},
                "nettools": {"ssl_log_secret": str(ssl_log_secret)},
            },
        }
    )
    if config_file.suffix.lower() == ".toml":
        config_file.write_text(config.to_toml_text(), encoding="utf-8")
    else:
        yaml = YAML()
        yaml.default_flow_style = False
        with config_file.open("w", encoding="utf-8") as handle:
            yaml.dump(config.to_yaml_data(), handle)
    return config.resolve_paths(config_file.parent, source_path=config_file)
