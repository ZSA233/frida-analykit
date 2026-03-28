import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from frida_analykit._version import __version__
from frida_analykit.cli import cli
from frida_analykit.config import AppConfig
from frida_analykit.dev_env import DevEnvError, ManagedEnv
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


def _config_with_logs(base_dir: Path, *, app: str | None = None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": app,
            "jsfile": "_agent.js",
            "server": {"host": "local"},
            "agent": {
                "stdout": "./logs/outerr.log",
                "stderr": "./logs/outerr.log",
            },
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


def _usb_config(base_dir: Path, *, app: str | None = None, device: str | None = "emulator-5554") -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": app,
            "jsfile": "_agent.js",
            "server": {
                "host": "usb",
                "device": device,
            },
            "agent": {},
            "script": {"nettools": {}},
        }
    ).resolve_paths(base_dir, source_path=base_dir / "config.yml")


def _remote_runtime_config(
    base_dir: Path,
    *,
    app: str | None = None,
    device: str | None = "emulator-5554",
) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": app,
            "jsfile": "_agent.js",
            "server": {
                "host": "127.0.0.1:27042",
                "servername": "/data/local/tmp/frida-server",
                "device": device,
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


class _FakeScript:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.log_handler = None
        self.loaded = False

    def on(self, signal: str, callback) -> None:
        self.handlers[signal] = callback

    def set_log_handler(self, handler) -> None:
        self.log_handler = handler

    def load(self) -> None:
        self.loaded = True


class _FakeAttachedSession:
    def __init__(self) -> None:
        self.script = _FakeScript()

    def create_script(self, source: str, name=None, snapshot=None, runtime=None):
        self.source = source
        return self.script

    def on(self, signal: str, callback) -> None:
        self.handlers = getattr(self, "handlers", {})
        self.handlers[signal] = callback


class _FakeAttachDevice(_FakeDevice):
    def __init__(self) -> None:
        super().__init__()
        self.attached: int | None = None
        self.session = _FakeAttachedSession()

    def attach(self, pid: int) -> _FakeAttachedSession:
        self.attached = pid
        return self.session


class _FakeCompat:
    def __init__(self) -> None:
        self.device = _FakeDevice()
        self.calls: list[tuple[str, str | None]] = []

    def get_device(self, host: str, *, device_id: str | None = None) -> _FakeDevice:
        self.calls.append((host, device_id))
        return self.device

    def enumerate_applications(self, device: _FakeDevice, scope: str = "minimal"):
        return []


class _FakeCompatWithAttach:
    def __init__(self) -> None:
        self.device = _FakeAttachDevice()
        self.calls: list[tuple[str, str | None]] = []

    def get_device(self, host: str, *, device_id: str | None = None) -> _FakeAttachDevice:
        self.calls.append((host, device_id))
        return self.device

    def enumerate_applications(self, device: _FakeAttachDevice, scope: str = "minimal"):
        return []


def test_gen_dev_creates_v2_workspace(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["gen", "dev", "--work-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["@zsa233/frida-analykit-agent"] == default_agent_package_spec()
    assert package["scripts"]["build"] == "frida-compile index.ts -o _agent.js -c"
    assert package["scripts"]["watch"] == "frida-compile index.ts -o _agent.js -w"
    assert package["devDependencies"]["typescript"] == "^5.8.3"
    assert not (tmp_path / ".npmrc").exists()
    assert (tmp_path / "README.md").exists()
    assert "frida-analykit build --config config.yml" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_default_agent_package_spec_maps_python_rc_to_npm_rc() -> None:
    assert default_agent_package_spec("2.0.0rc1") == "2.0.0-rc.1"


def test_cli_version_option_reports_installed_version() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0, result.output
    assert __version__ in result.output
    assert "frida-analykit" in result.output


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
    assert Path(calls["python_path"]).stem == "python"
    assert "updated Frida runtime" in result.output

def test_env_install_frida_surfaces_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    class FakeManager:
        def install_frida(self, python_path: Path, frida_version: str):
            raise DevEnvError("not inside a virtual environment")

    monkeypatch.setattr("frida_analykit.cli.common._global_env_manager", lambda: FakeManager())

    result = runner.invoke(cli, ["env", "install-frida", "--version", "16.5.9"])

    assert result.exit_code != 0
    assert "not inside a virtual environment" in result.output


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
        lambda config, device, pid: (device, object(), object()),
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
        lambda config, device, pid: (device, object(), object()),
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
        lambda config, device, pid: (device, object(), object()),
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
        "frida_analykit.cli.common._load_config",
        lambda _: _remote_runtime_config(tmp_path, app="com.example.demo"),
    )
    monkeypatch.setattr("frida_analykit.cli.common.FridaServerManager", lambda *args, **kwargs: FakeManager())
    monkeypatch.setattr("frida_analykit.cli.common._prepare_frontend_assets", lambda **kwargs: None)
    monkeypatch.setattr(
        "frida_analykit.cli.common._prepare_session",
        lambda config, device, pid: (device, object(), object()),
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
        lambda config, device, pid: (device, object(), object()),
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
        lambda config, device, pid: (device, object(), object()),
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


def test_server_boot_forwards_force_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    calls: dict[str, object] = {}

    def fake_boot(config, *, force_restart: bool = False):
        calls["config"] = config
        calls["force_restart"] = force_restart

    monkeypatch.setattr("frida_analykit.cli.common._load_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.commands.server.boot_server", fake_boot)

    result = runner.invoke(
        cli,
        ["server", "boot", "--config", str(tmp_path / "config.yml"), "--force-restart"],
    )

    assert result.exit_code == 0, result.output
    assert calls["config"].server.version == "17.8.1"
    assert calls["force_restart"] is True


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


def test_doctor_reports_remote_server_status_when_config_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()

    class FakeCompat:
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

        def inspect_remote_server(self, config):
            return SimpleNamespace(
                selected_version="17.8.1",
                adb_target="emulator-5554",
                device_abi="arm64-v8a",
                asset_arch="android-arm64",
                exists=True,
                executable=True,
                installed_version="17.8.0",
                supported=True,
                matched_profile="current-17",
            )

    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaCompat", FakeCompat)
    monkeypatch.setattr("frida_analykit.cli.common._load_optional_config", lambda _: _remote_config(tmp_path, version="17.8.1"))
    monkeypatch.setattr("frida_analykit.cli.commands.doctor.FridaServerManager", FakeManager)

    result = runner.invoke(cli, ["doctor", "--config", str(tmp_path / "config.yml")])

    assert result.exit_code == 0, result.output
    assert "Support status: tested" in result.output
    assert "Supported range: >=16.5.9, <18.0.0" in result.output
    assert "Configured server device: emulator-5554" in result.output
    assert "Configured server version: 17.8.1" in result.output
    assert "Install target version: 17.8.1" in result.output
    assert "ADB target device: emulator-5554" in result.output
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
