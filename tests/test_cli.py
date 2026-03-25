import json
from pathlib import Path

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
