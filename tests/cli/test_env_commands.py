from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import frida
import pytest
from click.testing import CliRunner

from frida_analykit._version import __version__
from frida_analykit.cli import cli
from frida_analykit.config import AppConfig, DEFAULT_SCRIPT_REPL_GLOBALS
from frida_analykit.development import DeviceCompatResult, DeviceCompatSummary
from frida_analykit.env import EnvError, ManagedEnv
from frida_analykit.scaffold import default_agent_package_spec
from frida_analykit.server import ServerManagerError

from .support import (
    _FakeCompat,
    _FakeCompatWithAttach,
    _config,
    _config_with_logs,
    _doctor_status,
    _remote_config,
    _remote_runtime_config,
    _usb_config,
)


def test_env_group_prints_help_when_no_subcommand() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["env"])

    assert result.exit_code == 0, result.output
    assert "Manage isolated Frida environments." in result.output
    assert "create" in result.output
    assert "remove" in result.output
    assert "install-frida" in result.output


def test_env_create_uses_manager_and_prints_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: dict[str, object] = {}
    env = ManagedEnv(
        name="frida-16.5.9",
        path="/tmp/frida-16.5.9",
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    class FakeManager:
        def create(self, *, name=None, profile=None, frida_version=None, with_repl=True):
            calls.update(name=name, profile=profile, frida_version=frida_version, with_repl=with_repl)
            return env

    monkeypatch.setattr("frida_analykit.cli.common._global_env_manager", lambda: FakeManager())

    result = runner.invoke(
        cli,
        ["env", "create", "--frida-version", "16.5.9", "--name", "frida-16.5.9"],
    )

    assert result.exit_code == 0, result.output
    assert calls == {
        "name": "frida-16.5.9",
        "profile": None,
        "frida_version": "16.5.9",
        "with_repl": True,
    }
    assert "created managed env `frida-16.5.9`" in result.output
    assert "activate:" in result.output


def test_env_create_can_skip_repl(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: dict[str, object] = {}
    env = ManagedEnv(
        name="frida-16.5.9",
        path="/tmp/frida-16.5.9",
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    class FakeManager:
        def create(self, *, name=None, profile=None, frida_version=None, with_repl=True):
            calls.update(name=name, profile=profile, frida_version=frida_version, with_repl=with_repl)
            return env

    monkeypatch.setattr("frida_analykit.cli.common._global_env_manager", lambda: FakeManager())

    result = runner.invoke(cli, ["env", "create", "--frida-version", "16.5.9", "--no-repl"])

    assert result.exit_code == 0, result.output
    assert calls["with_repl"] is False


def test_env_list_prints_manager_table(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    class FakeManager:
        def render_list(self) -> str:
            return "*  frida-16.5.9"

    monkeypatch.setattr("frida_analykit.cli.common._global_env_manager", lambda: FakeManager())

    result = runner.invoke(cli, ["env", "list"])

    assert result.exit_code == 0, result.output
    assert "*  frida-16.5.9" in result.output


def test_env_shell_forwards_optional_name(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: list[str | None] = []

    class FakeManager:
        def enter(self, name=None):
            calls.append(name)

    monkeypatch.setattr("frida_analykit.cli.common._global_env_manager", lambda: FakeManager())

    result = runner.invoke(cli, ["env", "shell", "legacy-16"])

    assert result.exit_code == 0, result.output
    assert calls == ["legacy-16"]


def test_env_remove_deletes_selected_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: list[str] = []
    managed_env = ManagedEnv(
        name="frida-16.5.9",
        path="/tmp/frida-16.5.9",
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    class FakeManager:
        def remove(self, name: str):
            calls.append(name)
            return managed_env

    monkeypatch.setattr("frida_analykit.cli.common._global_env_manager", lambda: FakeManager())

    result = runner.invoke(cli, ["env", "remove", "frida-16.5.9"])

    assert result.exit_code == 0, result.output
    assert calls == ["frida-16.5.9"]
    assert "removed managed env `frida-16.5.9`" in result.output


def test_env_use_sets_current_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: list[str] = []
    managed_env = ManagedEnv(
        name="frida-16.5.9",
        path="/tmp/frida-16.5.9",
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    class FakeManager:
        def use(self, name: str):
            calls.append(name)
            return managed_env

    monkeypatch.setattr("frida_analykit.cli.common._global_env_manager", lambda: FakeManager())

    result = runner.invoke(cli, ["env", "use", "frida-16.5.9"])

    assert result.exit_code == 0, result.output
    assert calls == ["frida-16.5.9"]
    assert "current env: frida-16.5.9" in result.output
    assert "current shell unchanged" in result.output


def test_env_install_frida_uses_current_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: dict[str, object] = {}

    class FakeManager:
        def install_frida(self, python_path: Path, frida_version: str):
            calls["python_path"] = python_path
            calls["frida_version"] = frida_version
            return {
                "env_dir": "/tmp/frida-16.5.9",
                "python": str(python_path),
                "frida_version": frida_version,
            }

    monkeypatch.setattr("frida_analykit.cli.common._global_env_manager", lambda: FakeManager())

    result = runner.invoke(cli, ["env", "install-frida", "--version", "16.5.9"])

    assert result.exit_code == 0, result.output
    assert calls["frida_version"] == "16.5.9"
    assert Path(calls["python_path"]).stem.startswith("python")
    assert "updated Frida runtime" in result.output

def test_env_install_frida_surfaces_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    class FakeManager:
        def install_frida(self, python_path: Path, frida_version: str):
            raise EnvError("not inside a virtual environment")

    monkeypatch.setattr("frida_analykit.cli.common._global_env_manager", lambda: FakeManager())

    result = runner.invoke(cli, ["env", "install-frida", "--version", "16.5.9"])

    assert result.exit_code != 0
    assert "not inside a virtual environment" in result.output
