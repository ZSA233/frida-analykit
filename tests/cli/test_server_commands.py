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


def test_server_boot_forwards_force_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: dict[str, object] = {}

    class FakeManager:
        def inspect_remote_server(self, config, *, probe_abi: bool = True, probe_host: bool = False):
            calls["inspect"] = {
                "config": config,
                "probe_abi": probe_abi,
                "probe_host": probe_host,
            }
            return _doctor_status(
                selected_version="17.8.1",
                selected_version_source="config.server.version",
                resolved_device="emulator-5554",
                resolved_device_source="config.server.device",
                installed_version="17.8.1",
                version_matches_target=True,
                server_path="/data/local/tmp/frida-server",
            )

        def boot_remote_server(self, config, *, force_restart: bool = False):
            calls["config"] = config
            calls["force_restart"] = force_restart

    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.commands.server.FridaServerManager", lambda: FakeManager())

    result = runner.invoke(
        cli,
        ["server", "boot", "--config", str(tmp_path / "config.yml"), "--force-restart"],
    )

    assert result.exit_code == 0, result.output
    assert calls["inspect"]["probe_abi"] is False
    assert calls["inspect"]["probe_host"] is False
    assert calls["config"].server.version == "17.8.1"
    assert calls["force_restart"] is True
    assert "Server Boot" in result.output
    assert "Target device: emulator-5554 (config.server.device)" in result.output
    assert "Remote host: 127.0.0.1:27042" in result.output
    assert "Remote port: 27042" in result.output
    assert "Restart mode: force-restart" in result.output


def test_server_stop_prints_stopped_pids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.commands.server.stop_server", lambda config: {222, 111})

    result = runner.invoke(cli, ["server", "stop", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert "stopped remote frida-server pids: 111, 222" in result.output


def test_server_stop_reports_no_matching_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.commands.server.stop_server", lambda config: set())

    result = runner.invoke(cli, ["server", "stop", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert "no matching remote frida-server was running" in result.output


def test_server_install_forwards_version_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: dict[str, object] = {}

    class FakeManager:
        def install_remote_server(
            self,
            config,
            *,
            version_override=None,
            local_server_path=None,
            force_download=False,
            download_progress=None,
        ):
            calls["config"] = config
            calls["version_override"] = version_override
            calls["local_server_path"] = local_server_path
            calls["force_download"] = force_download
            calls["download_progress"] = download_progress
            local_binary = tmp_path / "cache" / "frida-server"
            local_binary.parent.mkdir(parents=True, exist_ok=True)
            local_binary.write_text("binary", encoding="utf-8")
            return SimpleNamespace(
                installed_version="17.8.2",
                selected_version="17.8.2",
                remote_path=config.server.servername,
                device_abi="arm64-v8a",
                asset_arch="android-arm64",
                local_binary=local_binary,
                local_source=None,
                local_source_abi_hint=None,
                local_source_asset_arch_hint=None,
            )

    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.commands.server.FridaServerManager", lambda *args, **kwargs: FakeManager())

    result = runner.invoke(
        cli,
        [
            "server",
            "install",
            "--config",
            str(tmp_path / "config.yml"),
            "--version",
            "17.8.2",
            "--force-download",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls["config"].server.version == "17.8.1"
    assert calls["version_override"] == "17.8.2"
    assert calls["local_server_path"] is None
    assert calls["force_download"] is True
    assert calls["download_progress"] is not None
    assert "installed frida-server 17.8.2" in result.output


def test_server_install_supports_local_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: dict[str, object] = {}
    local_server = tmp_path / "frida-server.xz"
    local_server.write_text("binary", encoding="utf-8")

    class FakeManager:
        def install_remote_server(
            self,
            config,
            *,
            version_override=None,
            local_server_path=None,
            force_download=False,
            download_progress=None,
        ):
            calls["config"] = config
            calls["version_override"] = version_override
            calls["local_server_path"] = local_server_path
            calls["force_download"] = force_download
            calls["download_progress"] = download_progress
            local_binary = tmp_path / "cache" / "frida-server"
            local_binary.parent.mkdir(parents=True, exist_ok=True)
            local_binary.write_text("binary", encoding="utf-8")
            return SimpleNamespace(
                installed_version="16.5.9",
                selected_version="local",
                remote_path=config.server.servername,
                device_abi=None,
                asset_arch=None,
                local_binary=local_binary,
                local_source=local_server,
                local_source_abi_hint="arm64-v8a",
                local_source_asset_arch_hint="android-arm64",
            )

    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.commands.server.FridaServerManager", lambda *args, **kwargs: FakeManager())

    result = runner.invoke(
        cli,
        [
            "server",
            "install",
            "--config",
            str(tmp_path / "config.yml"),
            "--local-server",
            str(local_server),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls["version_override"] is None
    assert calls["local_server_path"] == local_server
    assert calls["force_download"] is False
    assert calls["download_progress"] is None
    assert "device abi: skipped (local server source)" in result.output
    assert "local source arch hint: arm64-v8a (android-arm64)" in result.output
    assert f"local source: {local_server}" in result.output


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["server", "install", "--config", "config.yml", "--version", "17.8.2", "--local-server", "frida-server"],
            "`--local-server` cannot be combined with `--version`",
        ),
        (
            ["server", "install", "--config", "config.yml", "--local-server", "frida-server", "--force-download"],
            "`--force-download` can only be used together with `--version`",
        ),
        (
            ["server", "install", "--config", "config.yml", "--force-download"],
            "`--force-download` requires an explicit `--version`",
        ),
    ],
)

def test_server_install_validates_option_combinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    expected: str,
) -> None:
    runner = CliRunner()
    local_server = tmp_path / "frida-server"
    local_server.write_text("binary", encoding="utf-8")
    rewritten_args = [str(local_server) if item == "frida-server" else item for item in args]

    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _remote_config(tmp_path, version="17.8.1"))

    result = runner.invoke(cli, rewritten_args)

    assert result.exit_code != 0
    assert expected in result.output


def test_server_install_reports_target_resolution_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()

    class FakeManager:
        def install_remote_server(self, config, **kwargs):
            raise ServerManagerError(
                "remote server installation requires a unique Android device; "
                "set config.server.device or ANDROID_SERIAL=<serial>. connected devices: SERIAL123, SERIAL456"
            )

    config = _remote_config(tmp_path, version="17.8.1")
    config = config.model_copy(update={"server": config.server.model_copy(update={"device": None})})
    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: config)
    monkeypatch.setattr("frida_analykit.cli.commands.server.FridaServerManager", lambda *args, **kwargs: FakeManager())

    result = runner.invoke(cli, ["server", "install", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code != 0
    assert "remote server installation requires a unique Android device; set config.server.device or ANDROID_SERIAL=<serial>. connected devices: SERIAL123, SERIAL456" in result.output
