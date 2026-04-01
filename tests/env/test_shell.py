from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from frida_analykit._version import __version__
from frida_analykit.development import load_profiles
from frida_analykit.env import (
    EnvError,
    EnvManager,
    ManagedEnv,
    _activate_path,
    _env_root_for_python,
    _python_path,
)

from tests.support.paths import REPO_ROOT

from .support import _write_file


@pytest.mark.skipif(os.name == "nt", reason="POSIX zsh wrapper behavior is not used on Windows")
def test_open_shell_uses_zsh_wrapper_that_reactivates_after_user_rc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    activate_path = env_dir / "bin" / "activate"
    activate_path.parent.mkdir(parents=True, exist_ok=True)
    activate_path.write_text("", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    original_zshrc = home / ".zshrc"
    original_zshrc.write_text("export PATH=/shim:$PATH\n", encoding="utf-8")
    manager = EnvManager.for_repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str] | None, str, str]] = []

    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("HOME", str(home))
    # `_open_zsh_shell()` prefers ZDOTDIR over HOME. Clear any host-level
    # ZDOTDIR so this test exercises the HOME-based fallback deterministically.
    monkeypatch.delenv("ZDOTDIR", raising=False)

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        assert env is not None
        zdotdir = Path(env["ZDOTDIR"])
        calls.append(
            (
                command,
                env,
                (zdotdir / ".zshenv").read_text(encoding="utf-8"),
                (zdotdir / ".zshrc").read_text(encoding="utf-8"),
            )
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    manager._runtime.subprocess_run = _run
    managed_env = ManagedEnv(
        name="frida-16.5.9",
        path=str(env_dir),
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    manager._shell_launcher.open_shell(managed_env)

    assert calls[0][0] == ["/bin/zsh", "-i"]
    assert ". " + str(original_zshrc) in calls[0][3]
    assert ". " + str(activate_path) in calls[0][3]
    assert calls[0][1]["VIRTUAL_ENV"] == str(env_dir)
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_NAME"] == "frida-16.5.9"
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_DIR"] == str(env_dir)
    assert calls[0][1]["UV_PROJECT"] == str(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX zsh wrapper behavior is not used on Windows")

def test_open_shell_prefers_explicit_zdotdir_for_zsh_startup_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    activate_path = env_dir / "bin" / "activate"
    activate_path.parent.mkdir(parents=True, exist_ok=True)
    activate_path.write_text("", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    zdotdir = tmp_path / "zdotdir"
    zdotdir.mkdir()
    original_zshrc = zdotdir / ".zshrc"
    original_zshrc.write_text("export PATH=/shim:$PATH\n", encoding="utf-8")
    manager = EnvManager.for_repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str] | None, str, str]] = []

    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("HOME", str(home))
    # Keep a dedicated test for the opposite branch so future refactors do not
    # accidentally stop honoring an explicit ZDOTDIR from the environment.
    monkeypatch.setenv("ZDOTDIR", str(zdotdir))

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        assert env is not None
        temp_zdotdir = Path(env["ZDOTDIR"])
        calls.append(
            (
                command,
                env,
                (temp_zdotdir / ".zshenv").read_text(encoding="utf-8"),
                (temp_zdotdir / ".zshrc").read_text(encoding="utf-8"),
            )
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    manager._runtime.subprocess_run = _run
    managed_env = ManagedEnv(
        name="frida-16.5.9",
        path=str(env_dir),
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    manager._shell_launcher.open_shell(managed_env)

    assert calls[0][0] == ["/bin/zsh", "-i"]
    assert ". " + str(original_zshrc) in calls[0][3]
    assert ". " + str(activate_path) in calls[0][3]


@pytest.mark.skipif(os.name == "nt", reason="POSIX generic shell fallback is not used on Windows")

def test_open_shell_fallback_exports_virtualenv_for_generic_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    (env_dir / "bin").mkdir(parents=True, exist_ok=True)
    manager = EnvManager.for_repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    monkeypatch.setenv("SHELL", "/bin/sh")

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager._runtime.subprocess_run = _run
    managed_env = ManagedEnv(
        name="frida-16.5.9",
        path=str(env_dir),
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    manager._shell_launcher.open_shell(managed_env)

    assert calls[0][0] == ["/bin/sh", "-i"]
    assert calls[0][1] is not None
    assert calls[0][1]["VIRTUAL_ENV"] == str(env_dir)
    assert calls[0][1]["PATH"].split(os.pathsep)[0] == str(_python_path(env_dir).parent)
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_NAME"] == "frida-16.5.9"
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_DIR"] == str(env_dir)
    assert calls[0][1]["UV_PROJECT"] == str(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd activation behavior only applies on Windows")

def test_open_shell_uses_cmd_activation_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    activate_path = _activate_path(env_dir)
    activate_path.parent.mkdir(parents=True, exist_ok=True)
    activate_path.write_text("", encoding="utf-8")
    manager = EnvManager.for_repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    monkeypatch.setenv("SHELL", "/bin/zsh")

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager._runtime.subprocess_run = _run
    managed_env = ManagedEnv(
        name="frida-16.5.9",
        path=str(env_dir),
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    manager._shell_launcher.open_shell(managed_env)

    assert calls[0][0] == [r"C:\Windows\System32\cmd.exe", "/K", str(activate_path)]
    assert calls[0][1] is not None
    assert calls[0][1]["VIRTUAL_ENV"] == str(env_dir)
    assert calls[0][1]["PATH"].split(os.pathsep)[0] == str(activate_path.parent)
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_NAME"] == "frida-16.5.9"
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_DIR"] == str(env_dir)
    assert calls[0][1]["UV_PROJECT"] == str(tmp_path)
