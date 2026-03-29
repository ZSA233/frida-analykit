from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from .models import DevEnvError, ManagedEnv
from .paths import _binary_dir
from .runtime import DevEnvRuntime


class DevEnvShellLauncher:
    def __init__(self, runtime: DevEnvRuntime) -> None:
        self._runtime = runtime

    def shell_environment(self, env: ManagedEnv, base_env: dict[str, str]) -> dict[str, str]:
        shell_env = dict(base_env)
        shell_env["VIRTUAL_ENV"] = str(env.env_dir)
        shell_env["PATH"] = f"{_binary_dir(env.env_dir)}{os.pathsep}{shell_env.get('PATH', '')}"
        shell_env["FRIDA_ANALYKIT_ENV_NAME"] = env.name
        shell_env["FRIDA_ANALYKIT_ENV_DIR"] = str(env.env_dir)
        if self._runtime.repo_root is not None:
            shell_env["UV_PROJECT"] = str(self._runtime.repo_root)
        return shell_env

    def open_shell(self, env: ManagedEnv) -> None:
        if os.name == "nt":
            result = self._open_windows_shell(env)
        else:
            result = self._open_posix_shell(env)
        if result.returncode != 0:
            raise DevEnvError(f"shell exited with status {result.returncode}")

    def _open_windows_shell(self, env: ManagedEnv) -> subprocess.CompletedProcess[str]:
        shell = os.environ.get("COMSPEC", "cmd.exe")
        return self._runtime.subprocess_run(
            [shell, "/K", str(env.activate_path)],
            env=self.shell_environment(env, os.environ.copy()),
            check=False,
        )

    def _open_posix_shell(self, env: ManagedEnv) -> subprocess.CompletedProcess[str]:
        shell = os.environ.get("SHELL", "/bin/sh")
        shell_name = Path(shell).name
        base_env = self.shell_environment(env, os.environ.copy())
        if shell_name == "zsh":
            return self._open_zsh_shell(shell, env, base_env)
        if shell_name == "bash":
            return self._open_bash_shell(shell, env, base_env)
        return self._runtime.subprocess_run(
            [shell, "-i"],
            env=base_env,
            check=False,
        )

    def _open_zsh_shell(
        self,
        shell: str,
        env: ManagedEnv,
        base_env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        original_zdotdir = Path(base_env.get("ZDOTDIR", str(Path.home())))
        with tempfile.TemporaryDirectory(prefix="frida-analykit-zdotdir-") as temp_dir:
            temp_zdotdir = Path(temp_dir)
            self._write_shell_hook(temp_zdotdir / ".zshenv", original_zdotdir / ".zshenv")
            self._write_shell_hook(
                temp_zdotdir / ".zshrc",
                original_zdotdir / ".zshrc",
                extra=f". {shlex.quote(str(env.activate_path))}",
            )
            shell_env = dict(base_env)
            shell_env["ZDOTDIR"] = str(temp_zdotdir)
            return self._runtime.subprocess_run(
                [shell, "-i"],
                env=shell_env,
                check=False,
            )

    def _open_bash_shell(
        self,
        shell: str,
        env: ManagedEnv,
        base_env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        original_rc = Path(base_env.get("HOME", str(Path.home()))) / ".bashrc"
        with tempfile.TemporaryDirectory(prefix="frida-analykit-bashrc-") as temp_dir:
            rc_path = Path(temp_dir) / ".bashrc"
            self._write_shell_hook(
                rc_path,
                original_rc,
                extra=f". {shlex.quote(str(env.activate_path))}",
            )
            return self._runtime.subprocess_run(
                [shell, "--rcfile", str(rc_path), "-i"],
                env=base_env,
                check=False,
            )

    @staticmethod
    def _write_shell_hook(path: Path, source_path: Path, *, extra: str | None = None) -> None:
        lines: list[str] = []
        if source_path.exists():
            lines.append(f". {shlex.quote(str(source_path))}")
        if extra is not None:
            lines.append(extra)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
