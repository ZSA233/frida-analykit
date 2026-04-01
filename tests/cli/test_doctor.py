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


def test_doctor_reports_remote_server_status_when_config_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()

    class FakeCompat:
        installed_version = "17.8.2"

        def doctor_report(self):
            return {
                "installed_version": "17.8.2",
                "support_status": "tested",
                "support_range": ">=16.5.9, <18.0.0",
                "supported": True,
                "matched_profile": "current-17",
                "tested_version": "17.8.2",
                "profiles": [
                    {
                        "name": "current-17",
                        "series": "17.x",
                        "tested_version": "17.8.2",
                        "range": ">=17.0.0, <18.0.0",
                    }
                ],
            }

    class FakeManager:
        def __init__(self, compat=None) -> None:
            self.compat = compat

        def inspect_remote_server(self, config, *, probe_host=False):
            assert probe_host is True
            return _doctor_status()

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaCompat", FakeCompat)
    monkeypatch.setattr("frida_analykit.cli.common._load_optional_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaServerManager", FakeManager)

    result = runner.invoke(cli, ["doctor", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert "[OK] Local Frida: 17.8.2 (tested, profile current-17)" in result.output
    assert "Target device: emulator-5554 (from config.server.device)" in result.output
    assert "Target server version: 17.8.1 (from config.server.version)" in result.output
    assert "Remote server version: 17.8.0 at /data/local/tmp/frida-server" in result.output
    assert "Remote server version mismatch: target 17.8.1, device has 17.8.0" in result.output
    assert "Remote host reachable: yes" in result.output
    assert "Remote protocol compatible: yes" in result.output
    assert "Supported range:" not in result.output


def test_doctor_reports_unreachable_remote_host_when_binary_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()

    class FakeCompat:
        installed_version = "17.8.2"

        def doctor_report(self):
            return {
                "installed_version": "17.8.2",
                "support_status": "tested",
                "support_range": ">=16.5.9, <18.0.0",
                "supported": True,
                "matched_profile": "current-17",
                "tested_version": "17.8.2",
                "profiles": [],
            }

    class FakeManager:
        def __init__(self, compat=None) -> None:
            self.compat = compat

        def inspect_remote_server(self, config, *, probe_host=False):
            assert probe_host is True
            return _doctor_status(
                host_reachable=False,
                host_error="connection closed",
                protocol_compatible=None,
                protocol_error=None,
            )

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaCompat", FakeCompat)
    monkeypatch.setattr("frida_analykit.cli.common._load_optional_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaServerManager", FakeManager)

    result = runner.invoke(cli, ["doctor", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert "Remote server version mismatch: target 17.8.1, device has 17.8.0" in result.output
    assert "Remote host reachable: no (connection closed)" in result.output


def test_doctor_verbose_configures_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    configured: list[bool] = []

    class FakeCompat:
        installed_version = "17.8.2"

        def doctor_report(self):
            return {
                "installed_version": "17.8.2",
                "support_status": "tested",
                "support_range": ">=16.5.9, <18.0.0",
                "supported": True,
                "matched_profile": "current-17",
                "tested_version": "17.8.2",
                "profiles": [],
            }

    monkeypatch.setattr("frida_analykit.cli.common.set_verbose", lambda enabled: configured.append(enabled))
    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaCompat", FakeCompat)
    monkeypatch.setattr("frida_analykit.cli.common._load_optional_config", lambda _: None)

    result = runner.invoke(cli, ["doctor", "--verbose", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert configured == [True]
    assert "Verbose details:" in result.output
    assert "Supported range: >=16.5.9, <18.0.0" in result.output


def test_doctor_reports_target_resolution_error_for_multiple_devices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()

    class FakeCompat:
        installed_version = "17.8.2"

        def doctor_report(self):
            return {
                "installed_version": "17.8.2",
                "support_status": "tested",
                "support_range": ">=16.5.9, <18.0.0",
                "supported": True,
                "matched_profile": "current-17",
                "tested_version": "17.8.2",
                "profiles": [],
            }

    class FakeManager:
        def __init__(self, compat=None) -> None:
            self.compat = compat

        def inspect_remote_server(self, config, *, probe_host=False):
            assert probe_host is True
            raise ServerManagerError(
                "remote server inspection requires a unique Android device; "
                "set config.server.device or ANDROID_SERIAL=<serial>. connected devices: SERIAL123, SERIAL456"
            )

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaCompat", FakeCompat)
    config = _remote_config(tmp_path, version="17.8.1")
    config = config.model_copy(update={"server": config.server.model_copy(update={"device": None})})
    monkeypatch.setattr("frida_analykit.cli.common._load_optional_config", lambda _: config)
    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaServerManager", FakeManager)

    result = runner.invoke(cli, ["doctor", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert (
        "Remote server checks failed: remote server inspection requires a unique Android device; "
        "set config.server.device or ANDROID_SERIAL=<serial>. connected devices: SERIAL123, SERIAL456"
    ) in result.output


def test_doctor_fix_reinstalls_remote_server_and_requires_manual_boot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    calls = {"inspect": 0, "install": 0}

    class FakeCompat:
        installed_version = "16.6.6"

        def doctor_report(self):
            return {
                "installed_version": "16.6.6",
                "support_status": "tested",
                "support_range": ">=16.5.9, <18.0.0",
                "supported": True,
                "matched_profile": "legacy-16",
                "tested_version": "16.5.9",
                "profiles": [],
            }

    class FakeManager:
        def __init__(self, compat=None) -> None:
            self.compat = compat

        def inspect_remote_server(self, config, *, probe_host=False):
            assert probe_host is True
            calls["inspect"] += 1
            if calls["inspect"] == 1:
                return _doctor_status(
                    selected_version="16.6.6",
                    selected_version_source="installed Frida",
                    configured_version=None,
                    installed_version="17.7.0",
                    version_matches_target=False,
                    protocol_compatible=False,
                    protocol_error="unable to communicate with remote frida-server",
                    resolved_device="SERIAL123",
                )
            return _doctor_status(
                selected_version="16.6.6",
                selected_version_source="installed Frida",
                configured_version=None,
                installed_version="16.6.6",
                version_matches_target=True,
                host_reachable=False,
                host_error="connection closed",
                protocol_compatible=None,
                protocol_error=None,
                resolved_device="SERIAL123",
            )

        def install_remote_server(self, config, **kwargs):
            calls["install"] += 1
            return SimpleNamespace(installed_version="16.6.6")

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaCompat", FakeCompat)
    monkeypatch.setattr("frida_analykit.cli.common._load_optional_config", lambda _: _remote_config(tmp_path, version=None))
    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaServerManager", FakeManager)

    result = runner.invoke(cli, ["doctor", "fix", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code != 0
    assert calls["install"] == 1
    assert "Applying doctor fix: reinstall remote frida-server 16.6.6 (from installed Frida)" in result.output
    assert "Remote server version mismatch: target 16.6.6, device has 17.7.0" in result.output
    assert "Remote server version matches target 16.6.6" in result.output
    assert "Remote host reachable: no (connection closed)" in result.output
    assert "Run `frida-analykit server boot --config" in result.output
    assert "doctor fix left unresolved runtime issues" in result.output


def test_doctor_fix_returns_zero_when_reinstall_clears_remote_issues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    calls = {"inspect": 0, "install": 0}

    class FakeCompat:
        installed_version = "16.6.6"

        def doctor_report(self):
            return {
                "installed_version": "16.6.6",
                "support_status": "tested",
                "support_range": ">=16.5.9, <18.0.0",
                "supported": True,
                "matched_profile": "legacy-16",
                "tested_version": "16.5.9",
                "profiles": [],
            }

    class FakeManager:
        def __init__(self, compat=None) -> None:
            self.compat = compat

        def inspect_remote_server(self, config, *, probe_host=False):
            assert probe_host is True
            calls["inspect"] += 1
            if calls["inspect"] == 1:
                return _doctor_status(
                    selected_version="16.6.6",
                    selected_version_source="installed Frida",
                    configured_version=None,
                    installed_version="17.7.0",
                    version_matches_target=False,
                    protocol_compatible=False,
                    protocol_error="unable to communicate with remote frida-server",
                    resolved_device="SERIAL123",
                )
            return _doctor_status(
                selected_version="16.6.6",
                selected_version_source="installed Frida",
                configured_version=None,
                installed_version="16.6.6",
                version_matches_target=True,
                host_reachable=True,
                protocol_compatible=True,
                resolved_device="SERIAL123",
            )

        def install_remote_server(self, config, **kwargs):
            calls["install"] += 1
            return SimpleNamespace(installed_version="16.6.6")

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaCompat", FakeCompat)
    monkeypatch.setattr("frida_analykit.cli.common._load_optional_config", lambda _: _remote_config(tmp_path, version=None))
    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaServerManager", FakeManager)

    result = runner.invoke(cli, ["doctor", "fix", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert calls["install"] == 1
    assert "Remote server version matches target 16.6.6" in result.output
    assert "Remote protocol compatible: yes" in result.output


def test_doctor_device_compat_reports_scan_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    configured: list[bool] = []
    captured: dict[str, object] = {}

    monkeypatch.setattr("frida_analykit.cli.common.set_verbose", lambda enabled: configured.append(enabled))
    monkeypatch.setattr("frida_analykit.cli.commands.doctor.cli_common._load_optional_config", lambda _: None)
    monkeypatch.setattr(
        "frida_analykit.cli.commands.doctor.resolve_device_compat_serials",
        lambda **kwargs: ("SERIAL123", "SERIAL456"),
    )
    def fake_run_device_compat_scan(*args, **kwargs):
        captured["iterations"] = kwargs["iterations"]
        captured["probe_kinds"] = kwargs["probe_kinds"]
        reporter = kwargs["reporter"]
        reporter.on_scan_start(serials=("SERIAL123", "SERIAL456"))
        reporter.on_device_start(
            device_index=1,
            device_total=2,
            serial="SERIAL123",
            remote_host="127.0.0.1:31123",
            sampled_versions=("17.9.1", "16.6.6"),
        )
        reporter.on_device_stage(
            device_index=1,
            device_total=2,
            serial="SERIAL123",
            stage="select-app",
            detail="selected `com.demo`",
        )
        reporter.on_version_start(
            device_index=1,
            device_total=2,
            version_index=1,
            version_total=2,
            serial="SERIAL123",
            version="17.9.1",
        )
        reporter.on_version_stage(
            device_index=1,
            device_total=2,
            version_index=1,
            version_total=2,
            serial="SERIAL123",
            version="17.9.1",
            stage="env",
        )
        reporter.on_version_result(
            device_index=1,
            device_total=2,
            version_index=1,
            version_total=2,
            serial="SERIAL123",
            version="17.9.1",
            result=DeviceCompatResult("17.9.1", "spawn", "success", None, "spawn injection probe succeeded", 1.0, app="com.demo"),
        )
        reporter.on_device_start(
            device_index=2,
            device_total=2,
            serial="SERIAL456",
            remote_host="127.0.0.1:31124",
            sampled_versions=("17.9.1",),
        )
        reporter.on_version_start(
            device_index=2,
            device_total=2,
            version_index=1,
            version_total=1,
            serial="SERIAL456",
            version="17.9.1",
        )
        reporter.on_version_stage(
            device_index=2,
            device_total=2,
            version_index=1,
            version_total=1,
            serial="SERIAL456",
            version="17.9.1",
            stage="env",
        )
        reporter.on_version_result(
            device_index=2,
            device_total=2,
            version_index=1,
            version_total=1,
            serial="SERIAL456",
            version="17.9.1",
            result=DeviceCompatResult("17.9.1", "spawn", "success", None, "spawn injection probe succeeded", 1.0, app="com.demo"),
        )
        return (
            DeviceCompatSummary(
                serial="SERIAL123",
                remote_host="127.0.0.1:31123",
                sampled_versions=("17.9.1", "16.6.6"),
                results=(
                    DeviceCompatResult("17.9.1", "spawn", "success", None, "spawn injection probe succeeded", 1.0, app="com.demo"),
                    DeviceCompatResult("16.6.6", "spawn", "success", None, "spawn injection probe succeeded", 1.0, app="com.demo"),
                ),
            ),
            DeviceCompatSummary(
                serial="SERIAL456",
                remote_host="127.0.0.1:31124",
                sampled_versions=("17.9.1",),
                results=(
                    DeviceCompatResult("17.9.1", "spawn", "success", None, "spawn injection probe succeeded", 1.0, app="com.demo"),
                ),
            ),
        )

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.run_device_compat_scan", fake_run_device_compat_scan)

    result = runner.invoke(cli, ["doctor", "--verbose", "device-compat", "--all-devices"])

    assert result.exit_code == 0, result.output
    assert configured == [True, True]
    assert captured["iterations"] == 3
    assert captured["probe_kinds"] == ()
    assert "Target devices: SERIAL123, SERIAL456" in result.output
    assert "[device 1/2] serial=SERIAL123 remote_host=127.0.0.1:31123 sampled=17.9.1, 16.6.6" in result.output
    assert "[device 1/2] [version 1/2] SERIAL123 17.9.1 start" in result.output
    assert "[device 1/2] [version 1/2] SERIAL123 17.9.1 [spawn] success" in result.output
    assert "Device: SERIAL123" in result.output
    assert "Device: SERIAL456" in result.output
    assert "Probe: spawn" in result.output
    assert "Estimated boundary: all sampled versions succeeded through 17.9.1" in result.output


def test_doctor_device_compat_returns_click_error_on_failed_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.cli_common._load_optional_config", lambda _: None)
    monkeypatch.setattr(
        "frida_analykit.cli.commands.doctor.resolve_device_compat_serials",
        lambda **kwargs: ("SERIAL123",),
    )
    monkeypatch.setattr(
        "frida_analykit.cli.commands.doctor.run_device_compat_scan",
        lambda *args, **kwargs: (
            DeviceCompatSummary(
                serial="SERIAL123",
                remote_host="127.0.0.1:31123",
                sampled_versions=("16.6.6",),
                results=(
                    DeviceCompatResult("16.6.6", "spawn", "unavailable", "env", "no managed env", 0.1),
                ),
            ),
        ),
    )

    result = runner.invoke(cli, ["doctor", "device-compat", "--all-devices"])

    assert result.exit_code != 0
    assert "device compatibility scan reported failures or unavailable versions" in result.output


def test_doctor_device_compat_forwards_explicit_probe_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    captured: dict[str, object] = {}

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.cli_common._load_optional_config", lambda _: None)
    monkeypatch.setattr(
        "frida_analykit.cli.commands.doctor.resolve_device_compat_serials",
        lambda **kwargs: ("SERIAL123",),
    )

    def fake_run_device_compat_scan(*args, **kwargs):
        captured["probe_kinds"] = kwargs["probe_kinds"]
        return (
            DeviceCompatSummary(
                serial="SERIAL123",
                remote_host="127.0.0.1:31123",
                sampled_versions=("17.9.1",),
                results=(
                    DeviceCompatResult("17.9.1", "attach", "success", None, "attach injection probe succeeded", 0.1),
                ),
            ),
        )

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.run_device_compat_scan", fake_run_device_compat_scan)

    result = runner.invoke(cli, ["doctor", "device-compat", "--serial", "SERIAL123", "--versions", "17.9.1", "--probe", "attach"])

    assert result.exit_code == 0, result.output
    assert captured["probe_kinds"] == ("attach",)
    assert "Probe: attach" in result.output


def test_doctor_device_compat_forwards_install_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    captured: dict[str, object] = {}

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.cli_common._load_optional_config", lambda _: None)
    monkeypatch.setattr(
        "frida_analykit.cli.commands.doctor.resolve_device_compat_serials",
        lambda **kwargs: ("SERIAL123",),
    )

    def fake_run_device_compat_scan(*args, **kwargs):
        captured["install_missing_env"] = kwargs["install_missing_env"]
        return (
            DeviceCompatSummary(
                serial="SERIAL123",
                remote_host="127.0.0.1:31123",
                sampled_versions=("17.9.0",),
                results=(
                    DeviceCompatResult("17.9.0", "spawn", "success", None, "spawn injection probe succeeded", 0.1),
                ),
            ),
        )

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.run_device_compat_scan", fake_run_device_compat_scan)

    result = runner.invoke(
        cli,
        ["doctor", "device-compat", "--serial", "SERIAL123", "--versions", "17.9.0", "--install-missing-env"],
    )

    assert result.exit_code == 0, result.output
    assert captured["install_missing_env"] is True
