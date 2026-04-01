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
    _FailingSpawnDevice,
    _FakeCompat,
    _FakeCompatWithAttach,
    _config,
    _config_with_logs,
    _doctor_status,
    _remote_config,
    _remote_runtime_config,
    _usb_config,
)


def test_attach_rejects_conflicting_build_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", _FakeCompat)
    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _config(tmp_path))

    result = runner.invoke(
        cli,
        ["attach", "--config", str(tmp_path / "config.yml"), "--pid", "123", "--build", "--watch"],
    )

    assert result.exit_code != 0
    assert "choose either `--build` or `--watch`" in result.output


def test_attach_forwards_frontend_build_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: dict[str, object] = {}
    compat = _FakeCompat()
    project_dir = tmp_path / "agent"
    project_dir.mkdir()

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _config(tmp_path))
    monkeypatch.setattr(
        "frida_analykit.cli.common._prepare_frontend_assets",
        lambda **kwargs: calls.update(kwargs) or None,
    )
    monkeypatch.setattr(
        "frida_analykit.cli.common._prepare_session",
        lambda config, device, pid, **kwargs: (device, object(), object()),
    )
    monkeypatch.setattr("frida_analykit.cli.common._post_attach", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        [
            "attach",
            "--config",
            str(tmp_path / "config.yml"),
            "--pid",
            "123",
            "--build",
            "--project-dir",
            str(project_dir),
            "--install",
            "--detach-on-load",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls["config"].source_path == (tmp_path / "config.yml")
    assert calls["build_agent"] is True
    assert calls["watch_agent"] is False
    assert calls["project_dir"] == project_dir
    assert calls["install"] is True


def test_attach_uses_configured_usb_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    compat = _FakeCompatWithAttach()

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _usb_config(tmp_path))
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: None)
    monkeypatch.setattr(
        "frida_analykit.cli.common._prepare_session",
        lambda config, device, pid, **kwargs: (device, object(), object()),
    )
    monkeypatch.setattr("frida_analykit.cli.common._post_attach", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["attach", "--config", str(tmp_path / "config.yml"), "--pid", "123", "--detach-on-load"],
    )

    assert result.exit_code == 0, result.output
    assert compat.calls == [("usb", "emulator-5554")]


def test_spawn_closes_watch_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    compat = _FakeCompat()
    watch_state = {"waited": False, "closed": False}

    class FakeWatcher:
        def wait_until_ready(self) -> Path:
            watch_state["waited"] = True
            return tmp_path / "_agent.js"

        def close(self) -> None:
            watch_state["closed"] = True

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _config(tmp_path, app="com.example.demo"))
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: FakeWatcher())
    monkeypatch.setattr(
        "frida_analykit.cli.common._prepare_session",
        lambda config, device, pid, **kwargs: (device, object(), object()),
    )
    monkeypatch.setattr("frida_analykit.cli.common._post_attach", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["spawn", "--config", str(tmp_path / "config.yml"), "--watch", "--detach-on-load"],
    )

    assert result.exit_code == 0, result.output
    assert compat.device.spawned == ["com.example.demo"]
    assert compat.device.resumed == 4321
    assert watch_state["closed"] is True


def test_spawn_forwards_remote_port_for_configured_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    compat = _FakeCompat()
    forwarded: dict[str, object] = {}

    class FakeManager:
        def ensure_remote_forward(self, config, *, action="remote port forward"):
            forwarded["config"] = config
            forwarded["action"] = action
            return "27042"

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr(
        "frida_analykit.cli.common.FridaCompat",
        lambda: SimpleNamespace(installed_version="17.8.2"),
    )
    monkeypatch.setattr(
        "frida_analykit.cli.common._load_config",
        lambda _: _remote_runtime_config(tmp_path, app="com.example.demo"),
    )
    monkeypatch.setattr("frida_analykit.cli.common.FridaServerManager", lambda *args, **kwargs: FakeManager())
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: None)
    monkeypatch.setattr(
        "frida_analykit.cli.common._prepare_session",
        lambda config, device, pid, **kwargs: (device, object(), object()),
    )
    monkeypatch.setattr("frida_analykit.cli.common._post_attach", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["spawn", "--config", str(tmp_path / "config.yml"), "--detach-on-load"],
    )

    assert result.exit_code == 0, result.output
    assert compat.calls == [("127.0.0.1:27042", None)]
    assert forwarded["config"].server.device == "emulator-5554"
    assert forwarded["action"] == "device connection"


def test_spawn_forwards_remote_port_without_configured_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    compat = _FakeCompat()
    forwarded: dict[str, object] = {}

    class FakeManager:
        def ensure_remote_forward(self, config, *, action="remote port forward"):
            forwarded["config"] = config
            forwarded["action"] = action
            return "27042"

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr(
        "frida_analykit.cli.common._load_config",
        lambda _: _remote_runtime_config(tmp_path, app="com.example.demo", device=None),
    )
    monkeypatch.setattr("frida_analykit.cli.common.FridaServerManager", lambda *args, **kwargs: FakeManager())
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: None)
    monkeypatch.setattr(
        "frida_analykit.cli.common._prepare_session",
        lambda config, device, pid, **kwargs: (device, object(), object()),
    )
    monkeypatch.setattr("frida_analykit.cli.common._post_attach", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["spawn", "--config", str(tmp_path / "config.yml"), "--detach-on-load"],
    )

    assert result.exit_code == 0, result.output
    assert compat.calls == [("127.0.0.1:27042", None)]
    assert forwarded["config"].server.device is None
    assert forwarded["action"] == "device connection"


def test_spawn_reports_remote_transport_error_with_boot_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    compat = _FakeCompat()
    compat.device = _FailingSpawnDevice(frida.TransportError("connection closed"))

    class FakeManager:
        def ensure_remote_forward(self, config, *, action="remote port forward"):
            return "27042"

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr(
        "frida_analykit.cli.common._load_config",
        lambda _: _remote_runtime_config(tmp_path, app="com.example.demo"),
    )
    monkeypatch.setattr("frida_analykit.cli.common.FridaServerManager", lambda *args, **kwargs: FakeManager())
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["spawn", "--config", str(tmp_path / "config.yml"), "--detach-on-load"],
    )

    assert result.exit_code != 0
    assert "forwarded Frida host `127.0.0.1:27042` is not reachable right now" in result.output
    assert "connection closed" in result.output
    assert "adb forward for this host is still alive" in result.output
    assert "if you already ran `frida-analykit server boot --config" in result.output
    assert "Traceback" not in result.output


def test_spawn_reports_remote_protocol_error_with_version_mismatch_diagnosis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    compat = _FakeCompat()
    compat.device = _FailingSpawnDevice(
        frida.ProtocolError("unable to communicate with remote frida-server")
    )

    class FakeManager:
        def ensure_remote_forward(self, config, *, action="remote port forward"):
            return "27042"

        def inspect_remote_server(self, config, *, probe_host=False):
            assert probe_host is True
            return _doctor_status(
                selected_version="16.6.6",
                selected_version_source="installed Frida",
                configured_version=None,
                resolved_device="SERIAL123",
                resolved_device_source="config.server.device",
                installed_version="17.7.0",
                version_matches_target=False,
                protocol_compatible=False,
                protocol_error="unable to communicate with remote frida-server",
            )

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr(
        "frida_analykit.cli.common._load_config",
        lambda _: _remote_runtime_config(tmp_path, app="com.example.demo"),
    )
    monkeypatch.setattr("frida_analykit.cli.common.FridaServerManager", lambda *args, **kwargs: FakeManager())
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["spawn", "--config", str(tmp_path / "config.yml"), "--detach-on-load"],
    )

    assert result.exit_code != 0
    assert "protocol-incompatible right now" in result.output
    assert "Local Frida: `17.8.2`" in result.output
    assert "Target server version: `16.6.6` (from installed Frida)" in result.output
    assert "Remote installed version: `17.7.0` on device `SERIAL123`" in result.output
    assert "frida-analykit doctor --config" in result.output
    assert "frida-analykit doctor fix --config" in result.output
    assert "rerun `frida-analykit server boot --config" in result.output
    assert "Traceback" not in result.output


def test_spawn_reports_timeout_without_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    compat = _FakeCompat()
    compat.device = _FailingSpawnDevice(frida.TimedOutError("timed out"))

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _config(tmp_path, app="com.example.demo"))
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["spawn", "--config", str(tmp_path / "config.yml"), "--detach-on-load"],
    )

    assert result.exit_code != 0
    assert "spawn of `com.example.demo` timed out while waiting for the app to launch" in result.output
    assert "Check whether the app blocks or exits during launch" in result.output
    assert "Traceback" not in result.output


def test_attach_forwards_remote_port_without_configured_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    compat = _FakeCompatWithAttach()
    forwarded: dict[str, object] = {}

    class FakeManager:
        def ensure_remote_forward(self, config, *, action="remote port forward"):
            forwarded["config"] = config
            forwarded["action"] = action
            return "27042"

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr(
        "frida_analykit.cli.common._load_config",
        lambda _: _remote_runtime_config(tmp_path, app="com.example.demo", device=None),
    )
    monkeypatch.setattr("frida_analykit.cli.common.FridaServerManager", lambda *args, **kwargs: FakeManager())
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: None)
    monkeypatch.setattr(
        "frida_analykit.cli.common._prepare_session",
        lambda config, device, pid, **kwargs: (device, object(), object()),
    )
    monkeypatch.setattr("frida_analykit.cli.common._find_app_pid", lambda device, compat, app_id: 123)
    monkeypatch.setattr("frida_analykit.cli.common._post_attach", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["attach", "--config", str(tmp_path / "config.yml"), "--detach-on-load"],
    )

    assert result.exit_code == 0, result.output
    assert compat.calls == [("127.0.0.1:27042", None)]
    assert forwarded["config"].server.device is None
    assert forwarded["action"] == "device connection"


def test_spawn_prints_resolved_agent_log_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    compat = _FakeCompatWithAttach()
    (tmp_path / "_agent.js").write_text("16 /index.js\n✄\n", encoding="utf-8")

    monkeypatch.setattr("frida_analykit.cli.commands.runtime.FridaCompat", lambda: compat)
    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _config_with_logs(tmp_path, app="com.example.demo"))
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: None)
    monkeypatch.setattr("frida_analykit.cli.common._post_attach", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["spawn", "--config", str(tmp_path / "config.yml"), "--detach-on-load"],
    )

    assert result.exit_code == 0, result.output
    assert "➜  Host:" in result.output
    assert "➜  Target:" in result.output
    assert "➜  Script:" in result.output
    assert "➜  Log Output:" in result.output
    assert "com.example.demo" in result.output
    assert "_agent.js" in result.output
    assert "outerr.log" in result.output
