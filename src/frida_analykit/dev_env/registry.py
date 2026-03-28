from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .._version import __version__
from .constants import _LEGACY_ENV_GLOB
from .models import DevEnvError, ManagedEnv, ManagedEnvRecord, RegistryPayload
from .paths import _python_path
from .profiles import load_profiles
from .runtime import DevEnvRuntime


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timestamp_for_path(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


class DevEnvRegistryStore:
    def __init__(self, runtime: DevEnvRuntime) -> None:
        self._runtime = runtime

    def load_registry(self) -> RegistryPayload:
        registry_path = self._runtime.registry_path
        if not registry_path.exists():
            return {"current": None, "envs": []}
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DevEnvError(f"Failed to read registry {registry_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise DevEnvError(f"{registry_path} is invalid: top-level payload must be an object")
        current = payload.get("current")
        envs = payload.get("envs", [])
        if current is not None and not isinstance(current, str):
            raise DevEnvError(f"{registry_path} is invalid: `current` must be a string or null")
        if not isinstance(envs, list):
            raise DevEnvError(f"{registry_path} is invalid: `envs` must be an array")
        return {
            "current": current,
            "envs": [item for item in envs if isinstance(item, dict)],
        }

    def save_registry(self, payload: RegistryPayload) -> None:
        registry_path = self._runtime.registry_path
        tmp_path: Path | None = None
        try:
            self._runtime.storage_root.mkdir(parents=True, exist_ok=True)
            self._runtime.env_root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=registry_path.parent,
                prefix=f".{registry_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, registry_path)
        except OSError as exc:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise DevEnvError(f"Failed to write registry {registry_path}: {exc}") from exc

    def iter_registry_envs(self, registry: RegistryPayload) -> list[ManagedEnv]:
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

    def refresh_registry(self) -> tuple[RegistryPayload, bool]:
        registry = self.load_registry()
        normalized_envs, changed = self._normalize_registry_envs(registry)
        envs_by_name: dict[str, ManagedEnv] = {}
        for env in normalized_envs:
            if Path(env.path).exists():
                envs_by_name[env.name] = env
            else:
                changed = True

        for env in self.discover_legacy_envs():
            if env.name not in envs_by_name:
                envs_by_name[env.name] = env
                changed = True

        current = registry.get("current")
        if current not in envs_by_name:
            if current is not None:
                changed = True
            current = None

        payload: RegistryPayload = {
            "current": current,
            "envs": [env.to_record() for env in sorted(envs_by_name.values(), key=lambda item: item.name)],
        }
        changed = changed or payload != {
            "current": registry.get("current"),
            "envs": registry.get("envs", []),
        }
        if changed:
            self.save_registry(payload)
        return payload, changed

    def discover_legacy_envs(self) -> list[ManagedEnv]:
        repo_root = self._runtime.repo_root
        if repo_root is None:
            return []

        profiles = load_profiles(repo_root)
        envs: list[ManagedEnv] = []
        for candidate in sorted(repo_root.glob(_LEGACY_ENV_GLOB)):
            if candidate.name == ".venv" or not candidate.is_dir():
                continue
            if (candidate / "pyvenv.cfg").exists() is False:
                continue
            frida_version = self.detect_installed_frida_version(candidate)
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
                    frida_analykit_version=self.detect_installed_frida_analykit_version(candidate) or __version__,
                    legacy=True,
                )
            )
        return envs

    def detect_installed_frida_version(self, env_dir: Path) -> str | None:
        python_path = _python_path(env_dir)
        if not python_path.exists():
            return None
        result = self._runtime.subprocess_run(
            [str(python_path), "-c", "import frida; print(frida.__version__)"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def detect_installed_frida_analykit_version(self, env_dir: Path) -> str | None:
        python_path = _python_path(env_dir)
        if not python_path.exists():
            return None
        try:
            result = self._runtime.subprocess_run(
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

    def resolve_env(self, name: str | None) -> ManagedEnv:
        registry, _ = self.refresh_registry()
        envs = {env.name: env for env in self.iter_registry_envs(registry)}
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
            self.set_current(only_env.name)
            return only_env
        raise DevEnvError("No current environment selected; run `list` or pass `--name`/`ENV_NAME`")

    def set_current(self, name: str) -> None:
        registry, _ = self.refresh_registry()
        envs = {env.name: env for env in self.iter_registry_envs(registry)}
        if name not in envs:
            raise DevEnvError(f"Unknown environment {name}")
        if registry.get("current") == name:
            return
        registry["current"] = name
        self.save_registry(registry)

    def update_registry_for_env(self, env_dir: Path, frida_version: str) -> None:
        if not self._runtime.registry_path.exists():
            return
        registry, _ = self.refresh_registry()
        envs: list[ManagedEnv] = []
        updated = False
        now = _utc_now()
        for env in self.iter_registry_envs(registry):
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
        self.save_registry(registry)

    def remove_existing_env_dir(self, env_dir: Path) -> None:
        if env_dir.is_symlink():
            raise DevEnvError(f"Refusing to recreate {env_dir.name}: managed env path is a symlink")
        if not env_dir.is_dir():
            raise DevEnvError(f"Refusing to recreate {env_dir.name}: managed env path is not a directory")
        if not self._is_within_env_root(env_dir):
            raise DevEnvError(f"Refusing to recreate {env_dir.name}: path escapes managed env root")
        shutil.rmtree(env_dir)

    def remove_env_dir(self, env: ManagedEnv) -> None:
        env_dir = env.env_dir
        if env_dir.is_symlink():
            raise DevEnvError(f"Refusing to remove {env.name}: managed env path is a symlink")
        if not env_dir.is_dir():
            raise DevEnvError(f"Refusing to remove {env.name}: managed env path is not a directory")
        if env.legacy:
            if self._runtime.repo_root is None:
                raise DevEnvError(f"Refusing to remove {env.name}: legacy environments are only supported in repo mode")
            if not self._is_within_repo_root(env_dir):
                raise DevEnvError(f"Refusing to remove {env.name}: legacy path escapes repository root")
        elif not self._is_within_env_root(env_dir):
            raise DevEnvError(f"Refusing to remove {env.name}: path escapes managed env root")
        shutil.rmtree(env_dir)

    def _normalize_registry_envs(self, registry: RegistryPayload) -> tuple[list[ManagedEnv], bool]:
        envs: list[ManagedEnv] = []
        changed = False
        for item in registry.get("envs", []):
            env, item_changed = self._normalize_registry_env(item)
            changed = changed or item_changed
            if env is not None:
                envs.append(env)
        return sorted(envs, key=lambda item: item.name), changed

    def _normalize_registry_env(self, item: object) -> tuple[ManagedEnv | None, bool]:
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
            frida_version = self.detect_installed_frida_version(env_dir) or "unknown"
            changed = True

        stored_frida_analykit_version = item.get("frida_analykit_version")
        if not isinstance(stored_frida_analykit_version, str) or not stored_frida_analykit_version:
            stored_frida_analykit_version = None
            changed = True
        detected_frida_analykit_version = self.detect_installed_frida_analykit_version(env_dir)
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

    def _is_within_env_root(self, env_dir: Path) -> bool:
        try:
            env_dir.resolve().relative_to(self._runtime.env_root.resolve())
        except (OSError, RuntimeError, ValueError):
            return False
        return True

    def _is_within_repo_root(self, env_dir: Path) -> bool:
        repo_root = self._runtime.repo_root
        if repo_root is None:
            return False
        try:
            env_dir.resolve().relative_to(repo_root.resolve())
        except (OSError, RuntimeError, ValueError):
            return False
        return True
