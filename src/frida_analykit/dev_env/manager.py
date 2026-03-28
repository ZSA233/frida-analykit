from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .._version import __version__
from .constants import (
    _DEFAULT_PYTHON_VERSION,
    _ENV_NAME_RE,
    _FRIDA_TOOLS_REQUIREMENT,
    _REPL_EXTRA,
    _UV_REQUIRED_MESSAGE,
)
from .models import DevEnvError, ManagedEnv
from .paths import (
    _env_root_for_python,
    _global_storage_root,
    _install_requirement,
    _python_path,
    _repo_install_source,
    _repo_storage_root,
)
from .profiles import load_profiles
from .registry import DevEnvRegistryStore, _utc_now
from .runtime import DevEnvRuntime, DevEnvSubprocessRun
from .shell import DevEnvShellLauncher


class DevEnvManager:
    def __init__(
        self,
        *,
        storage_root: Path,
        repo_root: Path | None,
        subprocess_run: DevEnvSubprocessRun = subprocess.run,
    ) -> None:
        runtime = DevEnvRuntime(
            storage_root=storage_root,
            env_root=storage_root / "envs",
            registry_path=storage_root / "envs.json",
            repo_root=repo_root,
            subprocess_run=subprocess_run,
        )
        self._runtime = runtime
        self._registry_store = DevEnvRegistryStore(runtime)
        self._shell_launcher = DevEnvShellLauncher(runtime)

    @classmethod
    def for_repo(
        cls,
        repo_root: Path,
        *,
        subprocess_run: DevEnvSubprocessRun = subprocess.run,
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
        subprocess_run: DevEnvSubprocessRun = subprocess.run,
    ) -> "DevEnvManager":
        return cls(
            storage_root=_global_storage_root(),
            repo_root=None,
            subprocess_run=subprocess_run,
        )

    @property
    def registry_path(self) -> Path:
        return self._runtime.registry_path

    @property
    def env_root(self) -> Path:
        return self._runtime.env_root

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

        env_dir = self._runtime.env_root / resolved_name
        if env_dir.exists():
            self._registry_store.remove_existing_env_dir(env_dir)

        self._run_checked(
            ["uv", "venv", str(env_dir), "--python", _DEFAULT_PYTHON_VERSION],
            cwd=self._runtime.repo_root,
            error_message=f"Failed to create {resolved_name}",
            stream_output=True,
        )

        env_python = _python_path(env_dir)
        if self._runtime.repo_root is not None:
            env = self._shell_launcher.shell_environment(
                ManagedEnv(
                    name=resolved_name,
                    path=str(env_dir),
                    frida_version=resolved_version,
                    source_kind=source_kind,
                    source_value=source_value,
                    last_updated=_utc_now(),
                    legacy=False,
                ),
                dict(os.environ),
            )
            command = ["uv", "sync", "--active"]
            if with_repl:
                command.extend(["--extra", _REPL_EXTRA])
            command.append("--dev")
            self._run_checked(
                command,
                cwd=self._runtime.repo_root,
                env=env,
                error_message=f"Failed to sync project dependencies into {resolved_name}",
                stream_output=True,
            )
        else:
            install_source = _repo_install_source(self._runtime.repo_root)
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
            cwd=self._runtime.repo_root,
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
        registry, _ = self._registry_store.refresh_registry()
        envs = {env.name: env for env in self._registry_store.iter_registry_envs(registry)}
        envs[managed.name] = managed
        registry["current"] = managed.name
        registry["envs"] = [env.to_record() for env in sorted(envs.values(), key=lambda item: item.name)]
        self._registry_store.save_registry(registry)
        return managed

    def remove(self, name: str) -> ManagedEnv:
        registry, _ = self._registry_store.refresh_registry()
        envs = {env.name: env for env in self._registry_store.iter_registry_envs(registry)}
        if name not in envs:
            available = ", ".join(sorted(envs)) or "none"
            raise DevEnvError(f"Unknown environment {name}. Available: {available}")

        env = envs[name]
        self._registry_store.remove_env_dir(env)

        remaining_envs = [item for item in envs.values() if item.name != name]
        registry["envs"] = [item.to_record() for item in sorted(remaining_envs, key=lambda item: item.name)]
        if registry.get("current") == name:
            registry["current"] = None
        self._registry_store.save_registry(registry)
        return env

    def use(self, name: str) -> ManagedEnv:
        env = self._registry_store.resolve_env(name)
        self._registry_store.set_current(env.name)
        return env

    def list_envs(self) -> list[ManagedEnv]:
        registry, _ = self._registry_store.refresh_registry()
        return self._registry_store.iter_registry_envs(registry)

    def render_list(self) -> str:
        registry, _ = self._registry_store.refresh_registry()
        envs = self._registry_store.iter_registry_envs(registry)
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
        env = self._registry_store.resolve_env(name)
        self._registry_store.set_current(env.name)
        self._shell_launcher.open_shell(env)
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
            cwd=self._runtime.repo_root,
            error_message=f"Failed to install frida=={frida_version} into {env_dir.name}",
            stream_output=True,
        )
        if update_registry:
            self._registry_store.update_registry_for_env(env_dir, frida_version)
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
            repo_root = self._runtime.repo_root
            if repo_root is None:
                raise DevEnvError("profiles are only available for repository-local environments")
            profiles = load_profiles(repo_root)
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
            result = self._runtime.subprocess_run(
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
