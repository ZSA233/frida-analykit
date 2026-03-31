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
        self.exports_sync = SimpleNamespace()
        self.exports_async = SimpleNamespace()

    def on(self, signal: str, callback) -> None:
        self.handlers[signal] = callback

    def set_log_handler(self, handler) -> None:
        self.log_handler = handler

    def list_exports_sync(self) -> list[str]:
        return []

    async def list_exports_async(self) -> list[str]:
        return []

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


class _FailingSpawnDevice(_FakeDevice):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self._exc = exc

    def spawn(self, argv: list[str]) -> int:
        self.spawned = argv
        raise self._exc


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


def _doctor_status(**overrides):
    payload = {
        "selected_version": "17.8.1",
        "selected_version_source": "config.server.version",
        "configured_version": "17.8.1",
        "server_path": "/data/local/tmp/frida-server",
        "adb_target": "emulator-5554",
        "resolved_device": "emulator-5554",
        "resolved_device_source": "config.server.device",
        "exists": True,
        "executable": True,
        "installed_version": "17.8.0",
        "version_matches_target": False,
        "supported": True,
        "matched_profile": "current-17",
        "device_abi": "arm64-v8a",
        "asset_arch": "android-arm64",
        "host_reachable": True,
        "host_error": None,
        "protocol_compatible": True,
        "protocol_error": None,
        "error": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_gen_dev_creates_v2_workspace(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["gen", "dev", "--work-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["@zsa233/frida-analykit-agent"] == default_agent_package_spec()
    assert "frida-java-bridge" not in package["dependencies"]
    assert package["scripts"]["build"] == "frida-compile index.ts -o _agent.js -c"
    assert package["scripts"]["watch"] == "frida-compile index.ts -o _agent.js -w"
    assert package["devDependencies"]["typescript"] == "^5.8.3"
    assert not (tmp_path / ".npmrc").exists()
    assert (tmp_path / "README.md").exists()
    assert "frida-analykit build --config config.yml" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "/helper" in (tmp_path / "index.ts").read_text(encoding="utf-8")
    assert "only bundles what your script uses" in (tmp_path / "README.md").read_text(encoding="utf-8")
    generated_config = AppConfig.from_yaml(tmp_path / "config.yml")
    assert generated_config.script.repl.globals == list(DEFAULT_SCRIPT_REPL_GLOBALS)


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
