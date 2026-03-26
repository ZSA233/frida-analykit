import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from frida_analykit.cli import cli
from frida_analykit.config import AppConfig
from frida_analykit.scaffold import default_agent_package_spec


def _config(base_dir: Path, *, app: str | None = None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": app,
            "jsfile": "_agent.js",
            "server": {"host": "local"},
            "agent": {},
            "script": {"nettools": {}},
        }
    ).resolve_paths(base_dir, source_path=base_dir / "config.yml")


def _remote_config(base_dir: Path, *, version: str | None = None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": "_agent.js",
            "server": {
                "host": "127.0.0.1:27042",
                "servername": "/data/local/tmp/frida-server",
                "device": "emulator-5554",
                "version": version,
            },
            "agent": {},
            "script": {"nettools": {}},
        }
    ).resolve_paths(base_dir, source_path=base_dir / "config.yml")


class _FakeDevice:
    def __init__(self) -> None:
        self.spawned: list[str] | None = None
        self.resumed: int | None = None

    def spawn(self, argv: list[str]) -> int:
        self.spawned = argv
        return 4321

    def resume(self, pid: int) -> None:
        self.resumed = pid


class _FakeCompat:
    def __init__(self) -> None:
        self.device = _FakeDevice()

    def get_device(self, host: str) -> _FakeDevice:
        return self.device

    def enumerate_applications(self, device: _FakeDevice, scope: str = "minimal"):
        return []


def test_gen_dev_creates_v2_workspace(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["gen", "dev", "--work-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["@zsa233/frida-analykit-agent"] == default_agent_package_spec("2.0.0")
    assert package["scripts"]["build"] == "frida-compile index.ts -o _agent.js -c"
    assert package["scripts"]["watch"] == "frida-compile index.ts -o _agent.js -w"
    assert package["devDependencies"]["typescript"] == "^5.8.3"
    assert not (tmp_path / ".npmrc").exists()
    assert (tmp_path / "README.md").exists()
    assert "frida-analykit build --config config.yml" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_default_agent_package_spec_maps_python_rc_to_npm_rc() -> None:
    assert default_agent_package_spec("2.0.0rc1") == "^2.0.0-rc.1"


def test_attach_rejects_conflicting_build_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("frida_analykit.cli.FridaCompat", _FakeCompat)
    monkeypatch.setattr("frida_analykit.cli._load_config", lambda _: _config(tmp_path))

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

    monkeypatch.setattr("frida_analykit.cli.FridaCompat", lambda: compat)
    monkeypatch.setattr("frida_analykit.cli._load_config", lambda _: _config(tmp_path))
    monkeypatch.setattr(
        "frida_analykit.cli._prepare_frontend_assets",
        lambda **kwargs: calls.update(kwargs) or None,
    )
    monkeypatch.setattr(
        "frida_analykit.cli._prepare_session",
        lambda config, device, pid: (device, object(), object()),
    )
    monkeypatch.setattr("frida_analykit.cli._post_attach", lambda **kwargs: None)

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

    monkeypatch.setattr("frida_analykit.cli.FridaCompat", lambda: compat)
    monkeypatch.setattr("frida_analykit.cli._load_config", lambda _: _config(tmp_path, app="com.example.demo"))
    monkeypatch.setattr("frida_analykit.cli._prepare_frontend_assets", lambda **kwargs: FakeWatcher())
    monkeypatch.setattr(
        "frida_analykit.cli._prepare_session",
        lambda config, device, pid: (device, object(), object()),
    )
    monkeypatch.setattr("frida_analykit.cli._post_attach", lambda **kwargs: None)

    result = runner.invoke(
        cli,
        ["spawn", "--config", str(tmp_path / "config.yml"), "--watch", "--detach-on-load"],
    )

    assert result.exit_code == 0, result.output
    assert compat.device.spawned == ["com.example.demo"]
    assert compat.device.resumed == 4321
    assert watch_state["closed"] is True


def test_server_install_forwards_version_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: dict[str, object] = {}

    class FakeManager:
        def install_remote_server(self, config, *, version_override=None, force_download=False):
            calls["config"] = config
            calls["version_override"] = version_override
            calls["force_download"] = force_download
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
            )

    monkeypatch.setattr("frida_analykit.cli._load_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.FridaServerManager", lambda *args, **kwargs: FakeManager())

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
    assert calls["force_download"] is True
    assert "installed frida-server 17.8.2" in result.output


def test_doctor_reports_remote_server_status_when_config_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()

    class FakeCompat:
        def doctor_report(self):
            return {
                "installed_version": "17.8.2",
                "supported": True,
                "matched_profile": "current-17",
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

        def inspect_remote_server(self, config):
            return SimpleNamespace(
                selected_version="17.8.1",
                device_abi="arm64-v8a",
                asset_arch="android-arm64",
                exists=True,
                executable=True,
                installed_version="17.8.0",
                supported=True,
                matched_profile="current-17",
            )

    monkeypatch.setattr("frida_analykit.cli.FridaCompat", FakeCompat)
    monkeypatch.setattr("frida_analykit.cli._load_optional_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.FridaServerManager", FakeManager)

    result = runner.invoke(cli, ["doctor", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert "Configured server version: 17.8.1" in result.output
    assert "Install target version: 17.8.1" in result.output
    assert "Device ABI: arm64-v8a (android-arm64)" in result.output
    assert "Remote server version: 17.8.0" in result.output
    assert "Remote server supported: yes" in result.output


def test_doctor_verbose_configures_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    configured: list[bool] = []

    class FakeCompat:
        def doctor_report(self):
            return {
                "installed_version": "17.8.2",
                "supported": True,
                "matched_profile": "current-17",
                "profiles": [],
            }

    monkeypatch.setattr("frida_analykit.cli.set_verbose", lambda enabled: configured.append(enabled))
    monkeypatch.setattr("frida_analykit.cli.FridaCompat", FakeCompat)
    monkeypatch.setattr("frida_analykit.cli._load_optional_config", lambda _: None)

    result = runner.invoke(cli, ["doctor", "--verbose", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert configured == [True]
