from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from ._version import __version__
from .release_version import parse_python_release_version

COMPAT_PROFILES_PATH = Path("src/frida_analykit/resources/compat_profiles.json")
_ENV_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LEGACY_ENV_GLOB = ".venv-*"
_DEFAULT_PYTHON_VERSION = "3.11"
_FRIDA_TOOLS_REQUIREMENT = "frida-tools"
_REPL_EXTRA = "repl"
_UV_REQUIRED_MESSAGE = (
    "Managed environment commands require `uv`, but it was not found on PATH. "
    "Install `uv`, ensure the `uv` command is available, then retry."
)


class DevEnvError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompatProfile:
    name: str
    tested_version: str


@dataclass(frozen=True)
class ManagedEnv:
    name: str
    path: str
    frida_version: str
    source_kind: str
    source_value: str
    last_updated: str
    frida_analykit_version: str = __version__
    legacy: bool = False

    @property
    def env_dir(self) -> Path:
        return Path(self.path)

    @property
    def python_path(self) -> Path:
        return _python_path(self.env_dir)

    @property
    def activate_path(self) -> Path:
        return _activate_path(self.env_dir)

    @property
    def frida_cli_path(self) -> Path:
        return _binary_path(self.env_dir, "frida")

    @property
    def frida_analykit_path(self) -> Path:
        return _binary_path(self.env_dir, "frida-analykit")

    @property
    def source_label(self) -> str:
        return f"{self.source_kind}:{self.source_value}"

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "frida_version": self.frida_version,
            "frida_analykit_version": self.frida_analykit_version,
            "source_kind": self.source_kind,
            "source_value": self.source_value,
            "last_updated": self.last_updated,
            "legacy": self.legacy,
        }


def load_profiles(repo_root: Path | None = None) -> dict[str, CompatProfile]:
    if repo_root is None or not (repo_root / COMPAT_PROFILES_PATH).exists():
        payload = json.loads(
            files("frida_analykit.resources")
            .joinpath("compat_profiles.json")
            .read_text(encoding="utf-8")
        )
    else:
        payload = json.loads((repo_root / COMPAT_PROFILES_PATH).read_text(encoding="utf-8"))

    profiles: dict[str, CompatProfile] = {}
    for item in payload["profiles"]:
        profiles[item["name"]] = CompatProfile(
            name=item["name"],
            tested_version=item["tested_version"],
        )
    return profiles


def render_env_summary(env: ManagedEnv, *, action: str = "ready") -> str:
    lines = [
        f"{action} managed env `{env.name}`",
        f"path: {env.env_dir}",
        f"python: {env.python_path}",
        f"activate: {env.activate_path}",
        f"frida: {env.frida_version}",
        f"frida-analykit version: {env.frida_analykit_version}",
        f"source: {env.source_label}",
    ]
    if env.frida_cli_path.exists():
        lines.append(f"frida-cli: {env.frida_cli_path}")
    if env.frida_analykit_path.exists():
        lines.append(f"frida-analykit: {env.frida_analykit_path}")
    return "\n".join(lines)


def render_install_summary(*, python_path: Path, env_dir: Path, frida_version: str) -> str:
    lines = [
        f"updated Frida runtime in `{env_dir.name}`",
        f"path: {env_dir}",
        f"python: {python_path}",
        f"activate: {_activate_path(env_dir)}",
        f"frida: {frida_version}",
    ]
    frida_cli = _binary_path(env_dir, "frida")
    if frida_cli.exists():
        lines.append(f"frida-cli: {frida_cli}")
    return "\n".join(lines)


def render_remove_summary(env: ManagedEnv) -> str:
    return "\n".join(
        [
            f"removed managed env `{env.name}`",
            f"path: {env.env_dir}",
            f"frida: {env.frida_version}",
            f"frida-analykit version: {env.frida_analykit_version}",
            f"source: {env.source_label}",
        ]
    )


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
    # Do not resolve symlinks here: venv/bin/python commonly points at a base interpreter,
    # and resolving it would lose the virtualenv bin/Scripts parent that we need to inspect.
    candidate = python_path.expanduser().absolute()
    if candidate.parent.name.lower() not in {"bin", "scripts"}:
        return None
    env_dir = candidate.parent.parent
    if (env_dir / "pyvenv.cfg").exists():
        return env_dir
    return None


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timestamp_for_path(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


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
    package_root = Path(__file__).resolve().parents[2]
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


class DevEnvManager:
    def __init__(
        self,
        *,
        storage_root: Path,
        repo_root: Path | None,
        subprocess_run: Any = subprocess.run,
    ) -> None:
        self._storage_root = storage_root
        self._env_root = storage_root / "envs"
        self._registry_path = storage_root / "envs.json"
        self._repo_root = repo_root
        self._subprocess_run = subprocess_run

    @classmethod
    def for_repo(
        cls,
        repo_root: Path,
        *,
        subprocess_run: Any = subprocess.run,
    ) -> "DevEnvManager":
        return cls(
            storage_root=_repo_storage_root(repo_root),
            repo_root=repo_root,
            subprocess_run=subprocess_run,
        )

    @classmethod
    def for_global(
        cls,
        *,
        subprocess_run: Any = subprocess.run,
    ) -> "DevEnvManager":
        return cls(
            storage_root=_global_storage_root(),
            repo_root=None,
            subprocess_run=subprocess_run,
        )

    @property
    def registry_path(self) -> Path:
        return self._registry_path

    @property
    def env_root(self) -> Path:
        return self._env_root

    def create(
        self,
        *,
        name: str | None,
        profile: str | None = None,
        frida_version: str | None = None,
        with_repl: bool = True,
    ) -> ManagedEnv:
        source_kind, source_value, resolved_version = self._resolve_source(
            profile=profile,
            frida_version=frida_version,
        )
        resolved_name = name or (profile if profile is not None else f"frida-{resolved_version}")
        self._validate_new_env_name(resolved_name)

        env_dir = self._env_root / resolved_name
        if env_dir.exists():
            self._remove_existing_env_dir(env_dir)

        self._run_checked(
            ["uv", "venv", str(env_dir), "--python", _DEFAULT_PYTHON_VERSION],
            cwd=self._repo_root,
            error_message=f"Failed to create {resolved_name}",
            stream_output=True,
        )

        env_python = _python_path(env_dir)
        if self._repo_root is not None:
            env = self._shell_environment(
                ManagedEnv(
                    name=resolved_name,
                    path=str(env_dir),
                    frida_version=resolved_version,
                    source_kind=source_kind,
                    source_value=source_value,
                    last_updated=_utc_now(),
                    legacy=False,
                ),
                os.environ.copy(),
            )
            command = ["uv", "sync", "--active"]
            if with_repl:
                command.extend(["--extra", _REPL_EXTRA])
            command.append("--dev")
            self._run_checked(
                command,
                cwd=self._repo_root,
                env=env,
                error_message=f"Failed to sync project dependencies into {resolved_name}",
                stream_output=True,
            )
        else:
            install_source = _repo_install_source(self._repo_root)
            command = ["uv", "pip", "install", "--python", str(env_python)]
            requirement = _install_requirement(install_source, with_repl=with_repl)
            if Path(install_source).exists():
                command.extend(["--editable", requirement])
            else:
                command.append(requirement)
            self._run_checked(
                command,
                cwd=None,
                error_message=f"Failed to install frida-analykit into {resolved_name}",
                stream_output=True,
            )

        self._run_checked(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(env_python),
                f"frida=={resolved_version}",
                _FRIDA_TOOLS_REQUIREMENT,
            ],
            cwd=self._repo_root,
            error_message=f"Failed to install frida=={resolved_version} into {resolved_name}",
            stream_output=True,
        )

        managed = ManagedEnv(
            name=resolved_name,
            path=str(env_dir),
            frida_version=resolved_version,
            source_kind=source_kind,
            source_value=source_value,
            last_updated=_utc_now(),
            frida_analykit_version=__version__,
            legacy=False,
        )
        registry, _ = self._refresh_registry()
        envs = {env.name: env for env in self._iter_registry_envs(registry)}
        envs[managed.name] = managed
        registry["current"] = managed.name
        registry["envs"] = [env.to_record() for env in sorted(envs.values(), key=lambda item: item.name)]
        self._save_registry(registry)
        return managed

    def remove(self, name: str) -> ManagedEnv:
        registry, _ = self._refresh_registry()
        envs = {env.name: env for env in self._iter_registry_envs(registry)}
        if name not in envs:
            available = ", ".join(sorted(envs)) or "none"
            raise DevEnvError(f"Unknown environment {name}. Available: {available}")

        env = envs[name]
        self._remove_env_dir(env)

        remaining_envs = [item for item in envs.values() if item.name != name]
        registry["envs"] = [item.to_record() for item in sorted(remaining_envs, key=lambda item: item.name)]
        if registry.get("current") == name:
            registry["current"] = None
        self._save_registry(registry)
        return env

    def use(self, name: str) -> ManagedEnv:
        env = self._resolve_env(name)
        self._set_current(env.name)
        return env

    def list_envs(self) -> list[ManagedEnv]:
        registry, _ = self._refresh_registry()
        return self._iter_registry_envs(registry)

    def render_list(self) -> str:
        registry, _ = self._refresh_registry()
        envs = self._iter_registry_envs(registry)
        if not envs:
            return "No managed Frida environments found."

        current = registry.get("current")
        headers = ("*", "name", "frida", "analykit", "source", "path", "updated")
        rows = [
            (
                "*" if env.name == current else "",
                env.name,
                env.frida_version,
                env.frida_analykit_version,
                env.source_label,
                env.path,
                env.last_updated,
            )
            for env in envs
        ]
        widths = [
            max(len(headers[index]), *(len(str(row[index])) for row in rows))
            for index in range(len(headers))
        ]
        lines = [
            "  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))),
            "  ".join("-" * widths[index] for index in range(len(headers))),
        ]
        lines.extend(
            "  ".join(str(row[index]).ljust(widths[index]) for index in range(len(headers)))
            for row in rows
        )
        return "\n".join(lines)

    def enter(self, name: str | None = None) -> ManagedEnv:
        env = self._resolve_env(name)
        self._set_current(env.name)
        self._open_shell(env)
        return env

    def install_frida(
        self,
        python_path: Path,
        frida_version: str,
        *,
        update_registry: bool = True,
    ) -> dict[str, str]:
        env_dir = _env_root_for_python(python_path)
        if env_dir is None:
            raise DevEnvError(
                f"`{python_path}` is not inside a virtual environment; use `frida-analykit env create` first"
            )
        self._run_checked(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python_path),
                f"frida=={frida_version}",
                _FRIDA_TOOLS_REQUIREMENT,
            ],
            cwd=self._repo_root,
            error_message=f"Failed to install frida=={frida_version} into {env_dir.name}",
            stream_output=True,
        )
        if update_registry:
            self._update_registry_for_env(env_dir, frida_version)
        return {
            "env_dir": str(env_dir),
            "python": str(python_path),
            "frida_version": frida_version,
        }

    def _resolve_source(
        self,
        *,
        profile: str | None,
        frida_version: str | None,
    ) -> tuple[str, str, str]:
        if bool(profile) == bool(frida_version):
            raise DevEnvError("choose exactly one of `--profile` or `--frida-version`")
        if profile is not None:
            profiles = load_profiles(self._repo_root)
            if profile not in profiles:
                available = ", ".join(sorted(profiles))
                raise DevEnvError(f"Unknown profile {profile}. Available: {available}")
            return ("profile", profile, profiles[profile].tested_version)
        assert frida_version is not None
        return ("version", frida_version, frida_version)

    def _validate_new_env_name(self, name: str) -> None:
        if not _ENV_NAME_RE.fullmatch(name):
            raise DevEnvError(
                "environment names must match `[A-Za-z0-9][A-Za-z0-9._-]*` and cannot include path separators"
            )

    def _load_registry(self) -> dict[str, Any]:
        if not self._registry_path.exists():
            return {"current": None, "envs": []}
        try:
            payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DevEnvError(f"Failed to read registry {self._registry_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise DevEnvError(f"{self._registry_path} is invalid: top-level payload must be an object")
        current = payload.get("current")
        envs = payload.get("envs", [])
        if current is not None and not isinstance(current, str):
            raise DevEnvError(f"{self._registry_path} is invalid: `current` must be a string or null")
        if not isinstance(envs, list):
            raise DevEnvError(f"{self._registry_path} is invalid: `envs` must be an array")
        return {"current": current, "envs": envs}

    def _save_registry(self, payload: dict[str, Any]) -> None:
        tmp_path: Path | None = None
        try:
            self._storage_root.mkdir(parents=True, exist_ok=True)
            self._env_root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._registry_path.parent,
                prefix=f".{self._registry_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self._registry_path)
        except OSError as exc:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise DevEnvError(f"Failed to write registry {self._registry_path}: {exc}") from exc

    def _iter_registry_envs(self, registry: dict[str, Any]) -> list[ManagedEnv]:
        envs: list[ManagedEnv] = []
        for item in registry.get("envs", []):
            envs.append(
                ManagedEnv(
                    name=item["name"],
                    path=item["path"],
                    frida_version=item["frida_version"],
                    source_kind=item["source_kind"],
                    source_value=item["source_value"],
                    last_updated=item["last_updated"],
                    frida_analykit_version=item.get("frida_analykit_version", __version__),
                    legacy=bool(item.get("legacy", False)),
                )
            )
        return sorted(envs, key=lambda item: item.name)

    def _refresh_registry(self) -> tuple[dict[str, Any], bool]:
        registry = self._load_registry()
        normalized_envs, changed = self._normalize_registry_envs(registry)
        envs_by_name: dict[str, ManagedEnv] = {}
        for env in normalized_envs:
            if Path(env.path).exists():
                envs_by_name[env.name] = env
            else:
                changed = True

        for env in self._discover_legacy_envs():
            if env.name not in envs_by_name:
                envs_by_name[env.name] = env
                changed = True

        current = registry.get("current")
        if current not in envs_by_name:
            if current is not None:
                changed = True
            current = None

        payload = {
            "current": current,
            "envs": [env.to_record() for env in sorted(envs_by_name.values(), key=lambda item: item.name)],
        }
        changed = changed or payload != {"current": registry.get("current"), "envs": registry.get("envs", [])}
        if changed:
            self._save_registry(payload)
        return payload, changed

    def _discover_legacy_envs(self) -> list[ManagedEnv]:
        if self._repo_root is None:
            return []

        profiles = load_profiles(self._repo_root)
        envs: list[ManagedEnv] = []
        for candidate in sorted(self._repo_root.glob(_LEGACY_ENV_GLOB)):
            if candidate.name == ".venv" or not candidate.is_dir():
                continue
            if (candidate / "pyvenv.cfg").exists() is False:
                continue
            frida_version = self._detect_installed_frida_version(candidate)
            if frida_version is None:
                continue
            if candidate.name.startswith(".venv-frida-"):
                source_kind = "version"
                source_value = candidate.name.removeprefix(".venv-frida-")
            else:
                profile_name = candidate.name.removeprefix(".venv-")
                if profile_name in profiles:
                    source_kind = "profile"
                    source_value = profile_name
                else:
                    source_kind = "version"
                    source_value = frida_version
            envs.append(
                ManagedEnv(
                    name=candidate.name,
                    path=str(candidate),
                    frida_version=frida_version,
                    source_kind=source_kind,
                    source_value=source_value,
                    last_updated=_timestamp_for_path(candidate),
                    frida_analykit_version=self._detect_installed_frida_analykit_version(candidate) or __version__,
                    legacy=True,
                )
            )
        return envs

    def _detect_installed_frida_version(self, env_dir: Path) -> str | None:
        python_path = _python_path(env_dir)
        if not python_path.exists():
            return None
        result = self._subprocess_run(
            [str(python_path), "-c", "import frida; print(frida.__version__)"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _detect_installed_frida_analykit_version(self, env_dir: Path) -> str | None:
        python_path = _python_path(env_dir)
        if not python_path.exists():
            return None
        try:
            result = self._subprocess_run(
                [str(python_path), "-c", "import frida_analykit; print(frida_analykit.__version__)"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _resolve_env(self, name: str | None) -> ManagedEnv:
        registry, _ = self._refresh_registry()
        envs = {env.name: env for env in self._iter_registry_envs(registry)}
        if name is not None:
            if name not in envs:
                available = ", ".join(sorted(envs)) or "none"
                raise DevEnvError(f"Unknown environment {name}. Available: {available}")
            return envs[name]

        current = registry.get("current")
        if current is not None and current in envs:
            return envs[current]
        if len(envs) == 1:
            only_env = next(iter(envs.values()))
            self._set_current(only_env.name)
            return only_env
        raise DevEnvError("No current environment selected; run `list` or pass `--name`/`ENV_NAME`")

    def _set_current(self, name: str) -> None:
        registry, _ = self._refresh_registry()
        envs = {env.name: env for env in self._iter_registry_envs(registry)}
        if name not in envs:
            raise DevEnvError(f"Unknown environment {name}")
        if registry.get("current") == name:
            return
        registry["current"] = name
        self._save_registry(registry)

    def _update_registry_for_env(self, env_dir: Path, frida_version: str) -> None:
        if not self._registry_path.exists():
            return
        registry, _ = self._refresh_registry()
        envs = []
        updated = False
        now = _utc_now()
        for env in self._iter_registry_envs(registry):
            if env.env_dir == env_dir:
                env = ManagedEnv(
                    name=env.name,
                    path=env.path,
                    frida_version=frida_version,
                    source_kind=env.source_kind,
                    source_value=env.source_value,
                    last_updated=now,
                    frida_analykit_version=env.frida_analykit_version,
                    legacy=env.legacy,
                )
                updated = True
            envs.append(env)
        if not updated:
            return
        registry["envs"] = [env.to_record() for env in envs]
        self._save_registry(registry)

    def _normalize_registry_envs(self, registry: dict[str, Any]) -> tuple[list[ManagedEnv], bool]:
        envs: list[ManagedEnv] = []
        changed = False
        for item in registry.get("envs", []):
            env, item_changed = self._normalize_registry_env(item)
            changed = changed or item_changed
            if env is not None:
                envs.append(env)
        return sorted(envs, key=lambda item: item.name), changed

    def _normalize_registry_env(self, item: Any) -> tuple[ManagedEnv | None, bool]:
        if not isinstance(item, dict):
            return None, True

        name = item.get("name")
        path = item.get("path")
        if not isinstance(name, str) or not name:
            return None, True
        if not isinstance(path, str) or not path:
            return None, True

        env_dir = Path(path)
        changed = False

        frida_version = item.get("frida_version")
        if not isinstance(frida_version, str) or not frida_version:
            frida_version = self._detect_installed_frida_version(env_dir) or "unknown"
            changed = True

        stored_frida_analykit_version = item.get("frida_analykit_version")
        if not isinstance(stored_frida_analykit_version, str) or not stored_frida_analykit_version:
            stored_frida_analykit_version = None
            changed = True
        detected_frida_analykit_version = self._detect_installed_frida_analykit_version(env_dir)
        if detected_frida_analykit_version is not None:
            frida_analykit_version = detected_frida_analykit_version
            if frida_analykit_version != stored_frida_analykit_version:
                changed = True
        else:
            frida_analykit_version = stored_frida_analykit_version or "unknown"

        source_kind = item.get("source_kind")
        if not isinstance(source_kind, str) or not source_kind:
            source_kind = "version"
            changed = True

        source_value = item.get("source_value")
        if not isinstance(source_value, str) or not source_value:
            source_value = frida_version or name
            changed = True

        last_updated = item.get("last_updated")
        if not isinstance(last_updated, str) or not last_updated:
            try:
                last_updated = _timestamp_for_path(env_dir)
            except OSError:
                last_updated = _utc_now()
            changed = True

        legacy = item.get("legacy")
        if not isinstance(legacy, bool):
            legacy = False
            changed = True

        return (
            ManagedEnv(
                name=name,
                path=path,
                frida_version=frida_version,
                source_kind=source_kind,
                source_value=source_value,
                last_updated=last_updated,
                frida_analykit_version=frida_analykit_version,
                legacy=legacy,
            ),
            changed,
        )

    def _remove_existing_env_dir(self, env_dir: Path) -> None:
        # For deletion safety we do resolve symlinks: the real target must still stay under
        # the managed env root, otherwise we refuse to remove it.
        if env_dir.is_symlink():
            raise DevEnvError(f"Refusing to recreate {env_dir.name}: managed env path is a symlink")
        if not env_dir.is_dir():
            raise DevEnvError(f"Refusing to recreate {env_dir.name}: managed env path is not a directory")
        if not self._is_within_env_root(env_dir):
            raise DevEnvError(f"Refusing to recreate {env_dir.name}: path escapes managed env root")
        shutil.rmtree(env_dir)

    def _is_within_env_root(self, env_dir: Path) -> bool:
        try:
            env_dir.resolve().relative_to(self._env_root.resolve())
        except (OSError, RuntimeError, ValueError):
            return False
        return True

    def _remove_env_dir(self, env: ManagedEnv) -> None:
        env_dir = env.env_dir
        if env_dir.is_symlink():
            raise DevEnvError(f"Refusing to remove {env.name}: managed env path is a symlink")
        if not env_dir.is_dir():
            raise DevEnvError(f"Refusing to remove {env.name}: managed env path is not a directory")
        if env.legacy:
            if self._repo_root is None:
                raise DevEnvError(f"Refusing to remove {env.name}: legacy environments are only supported in repo mode")
            if not self._is_within_repo_root(env_dir):
                raise DevEnvError(f"Refusing to remove {env.name}: legacy path escapes repository root")
        elif not self._is_within_env_root(env_dir):
            raise DevEnvError(f"Refusing to remove {env.name}: path escapes managed env root")
        shutil.rmtree(env_dir)

    def _is_within_repo_root(self, env_dir: Path) -> bool:
        if self._repo_root is None:
            return False
        try:
            env_dir.resolve().relative_to(self._repo_root.resolve())
        except (OSError, RuntimeError, ValueError):
            return False
        return True

    def _shell_environment(self, env: ManagedEnv, base_env: dict[str, str]) -> dict[str, str]:
        shell_env = dict(base_env)
        shell_env["VIRTUAL_ENV"] = str(env.env_dir)
        shell_env["PATH"] = f"{_binary_dir(env.env_dir)}{os.pathsep}{shell_env.get('PATH', '')}"
        shell_env["FRIDA_ANALYKIT_ENV_NAME"] = env.name
        shell_env["FRIDA_ANALYKIT_ENV_DIR"] = str(env.env_dir)
        if self._repo_root is not None:
            shell_env["UV_PROJECT"] = str(self._repo_root)
        return shell_env

    def _open_shell(self, env: ManagedEnv) -> None:
        env_dir = env.env_dir
        if os.name == "nt":
            shell = os.environ.get("COMSPEC", "cmd.exe")
            result = self._subprocess_run(
                [shell, "/K", str(env.activate_path)],
                env=self._shell_environment(env, os.environ.copy()),
                check=False,
            )
        else:
            shell = os.environ.get("SHELL", "/bin/sh")
            shell_name = Path(shell).name
            base_env = self._shell_environment(env, os.environ.copy())
            if shell_name == "zsh":
                result = self._open_zsh_shell(shell, env, base_env)
            elif shell_name == "bash":
                result = self._open_bash_shell(shell, env, base_env)
            else:
                result = self._subprocess_run(
                    [shell, "-i"],
                    env=base_env,
                    check=False,
                )
        if result.returncode != 0:
            raise DevEnvError(f"shell exited with status {result.returncode}")

    def _open_zsh_shell(
        self,
        shell: str,
        env: ManagedEnv,
        base_env: dict[str, str],
    ) -> subprocess.CompletedProcess[Any]:
        original_zdotdir = Path(base_env.get("ZDOTDIR", str(Path.home())))
        with tempfile.TemporaryDirectory(prefix="frida-analykit-zdotdir-") as temp_dir:
            temp_zdotdir = Path(temp_dir)
            self._write_shell_hook(
                temp_zdotdir / ".zshenv",
                original_zdotdir / ".zshenv",
            )
            self._write_shell_hook(
                temp_zdotdir / ".zshrc",
                original_zdotdir / ".zshrc",
                extra=f". {shlex.quote(str(env.activate_path))}",
            )
            base_env = dict(base_env)
            base_env["ZDOTDIR"] = str(temp_zdotdir)
            return self._subprocess_run(
                [shell, "-i"],
                env=base_env,
                check=False,
            )

    def _open_bash_shell(
        self,
        shell: str,
        env: ManagedEnv,
        base_env: dict[str, str],
    ) -> subprocess.CompletedProcess[Any]:
        original_rc = Path(base_env.get("HOME", str(Path.home()))) / ".bashrc"
        with tempfile.TemporaryDirectory(prefix="frida-analykit-bashrc-") as temp_dir:
            rc_path = Path(temp_dir) / ".bashrc"
            self._write_shell_hook(
                rc_path,
                original_rc,
                extra=f". {shlex.quote(str(env.activate_path))}",
            )
            return self._subprocess_run(
                [shell, "--rcfile", str(rc_path), "-i"],
                env=base_env,
                check=False,
            )

    def _write_shell_hook(self, path: Path, source_path: Path, *, extra: str | None = None) -> None:
        lines = []
        if source_path.exists():
            lines.append(f". {shlex.quote(str(source_path))}")
        if extra is not None:
            lines.append(extra)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _run_checked(
        self,
        command: list[str],
        *,
        cwd: Path | None,
        error_message: str,
        env: dict[str, str] | None = None,
        stream_output: bool = False,
    ) -> None:
        try:
            result = self._subprocess_run(
                command,
                cwd=cwd,
                env=env,
                check=False,
                capture_output=not stream_output,
                text=True,
            )
        except FileNotFoundError as exc:
            if command and command[0] == "uv":
                raise DevEnvError(_UV_REQUIRED_MESSAGE) from exc
            tool = command[0] if command else "<unknown>"
            raise DevEnvError(f"Required command `{tool}` was not found on PATH") from exc
        if result.returncode != 0:
            detail = "\n".join(
                part for part in (getattr(result, "stdout", None), getattr(result, "stderr", None)) if part
            ).strip()
            if detail:
                raise DevEnvError(f"{error_message}: {detail}")
            raise DevEnvError(error_message)


def repo_cli_main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Manage repository-local Frida environments.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.epilog = (
        "Examples:\n"
        "  make dev-env\n"
        "  make dev-env-list\n"
        "  make dev-env-gen FRIDA_VERSION=16.5.9\n"
        "  make dev-env-gen FRIDA_VERSION=16.5.9 NO_REPL=1\n"
        "  make dev-env-gen FRIDA_VERSION=16.5.9 ENV_NAME=frida-16.5.9\n"
        "  make dev-env-enter ENV_NAME=frida-16.5.9\n"
        "  make dev-env-remove ENV_NAME=frida-16.5.9\n"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("help")
    subparsers.add_parser("list")

    gen_parser = subparsers.add_parser("gen")
    gen_group = gen_parser.add_mutually_exclusive_group(required=True)
    gen_group.add_argument("--profile")
    gen_group.add_argument("--frida-version")
    gen_parser.add_argument("--name")
    gen_parser.add_argument("--no-repl", action="store_true")

    enter_parser = subparsers.add_parser("enter")
    enter_parser.add_argument("--name")

    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("--name", required=True)

    args = parser.parse_args(argv)
    if args.command in {None, "help"}:
        parser.print_help()
        return 0

    manager = DevEnvManager.for_repo((repo_root or Path.cwd()).resolve())
    try:
        if args.command == "list":
            print(manager.render_list())
            return 0
        if args.command == "gen":
            env = manager.create(
                name=args.name,
                profile=args.profile,
                frida_version=args.frida_version,
                with_repl=not args.no_repl,
            )
            print(render_env_summary(env))
            return 0
        if args.command == "enter":
            manager.enter(args.name)
            return 0
        if args.command == "remove":
            env = manager.remove(args.name)
            print(render_remove_summary(env))
            return 0
    except DevEnvError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 1
