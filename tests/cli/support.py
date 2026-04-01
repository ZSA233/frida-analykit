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


