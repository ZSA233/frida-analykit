from __future__ import annotations

from pathlib import Path

import pytest

from frida_analykit.config import AppConfig
from frida_analykit.mcp.manager import DebugSessionManager, MCPManagerError


class FakeScriptWrapper:
    def __init__(self) -> None:
        self.extra_handler = None
        self.clear_scope_calls = 0

    def set_logger(self, loggers=None, *, extra_handler=None) -> None:
        del loggers
        self.extra_handler = extra_handler

    def load(self) -> None:
        return None

    async def ensure_runtime_compatible_async(self) -> None:
        return None

    async def clear_scope_async(self) -> None:
        self.clear_scope_calls += 1


class FakeSessionWrapper:
    def __init__(self, script: FakeScriptWrapper) -> None:
        self.script = script
        self.handlers: dict[str, object] = {}
        self.is_detached = False

    def on(self, signal: str, callback) -> None:
        self.handlers[signal] = callback

    def create_script(self, source: str, name=None, snapshot=None, runtime=None, env=None) -> FakeScriptWrapper:
        del source, name, snapshot, runtime, env
        return self.script

    def detach(self) -> None:
        self.is_detached = True


class FakeDevice:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self.attach_calls: list[int] = []
        self.last_session: FakeSessionWrapper | None = None

    def attach(self, pid: int) -> FakeSessionWrapper:
        self.attach_calls.append(pid)
        self.last_session = self._session_factory()
        return self.last_session

    def spawn(self, argv: list[str]) -> int:
        del argv
        return 777

    def resume(self, pid: int) -> None:
        del pid


class FakeCompat:
    def __init__(self, device: FakeDevice) -> None:
        self.device = device

    def get_device(self, host: str, *, device_id: str | None = None) -> FakeDevice:
        del host, device_id
        return self.device

    def enumerate_applications(self, device: FakeDevice, *, scope: str = "minimal"):
        del device, scope
        return []


def _write_agent_file(tmp_path: Path) -> Path:
    path = tmp_path / "_agent.js"
    path.write_text("16 /index.js\n✄\n", encoding="utf-8")
    return path


def _config(tmp_path: Path) -> AppConfig:
    _write_agent_file(tmp_path)
    return AppConfig.model_validate(
        {
            "app": "com.example.demo",
            "jsfile": "_agent.js",
            "server": {"host": "local"},
            "script": {"nettools": {}},
        }
    ).resolve_paths(tmp_path, source_path=tmp_path / "config.yml")


def test_sync_adapter_reuses_background_loop_and_closes_cleanly(tmp_path: Path) -> None:
    script = FakeScriptWrapper()
    device = FakeDevice(lambda: FakeSessionWrapper(script))
    config = _config(tmp_path)
    manager = DebugSessionManager(
        config_loader=lambda path: config if Path(path).resolve() == config.source_path else None,  # type: ignore[return-value]
        compat_factory=lambda: FakeCompat(device),
        session_factory=lambda raw_session, *, config, interactive: raw_session,
    )

    opened = manager.session_open(config_path=str(config.source_path), mode="attach", pid=321)
    status = manager.session_status()
    manager._shutdown_at_exit()

    assert opened.state == "live"
    assert status.state == "live"
    assert device.attach_calls == [321]
    assert device.last_session is not None and device.last_session.is_detached is True
    assert script.clear_scope_calls == 1


def test_sync_adapter_reports_closed_loop_after_close(tmp_path: Path) -> None:
    script = FakeScriptWrapper()
    device = FakeDevice(lambda: FakeSessionWrapper(script))
    config = _config(tmp_path)
    manager = DebugSessionManager(
        config_loader=lambda path: config if Path(path).resolve() == config.source_path else None,  # type: ignore[return-value]
        compat_factory=lambda: FakeCompat(device),
        session_factory=lambda raw_session, *, config, interactive: raw_session,
    )

    manager.close()

    with pytest.raises(MCPManagerError, match="background loop is closed"):
        manager.session_status()
