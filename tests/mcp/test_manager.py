from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from frida_analykit.config import AppConfig
from frida_analykit.mcp.async_manager import AsyncDebugSessionManager, MCPManagerError
from frida_analykit.rpc import RPCCompatibilityError


class FakeHandle:
    def __init__(
        self,
        path: str,
        *,
        value: object | Exception | None = None,
        type_name: str = "object",
        props: dict[str, "FakeHandle"] | None = None,
        call_factory: Callable[..., "FakeHandle"] | None = None,
    ) -> None:
        self._path = path
        self._value = value
        self._type = type_name
        self._props = props or {}
        self._call_factory = call_factory
        self.release_calls = 0
        self.calls: list[tuple[object, ...]] = []

    @property
    def value_(self) -> object | None:
        if isinstance(self._value, Exception):
            raise self._value
        return self._value

    @property
    def type_(self) -> str:
        return self._type

    async def resolve_async(self) -> object | None:
        return self.value_

    def release(self) -> None:
        self.release_calls += 1

    async def release_async(self) -> None:
        self.release()

    def __dir__(self) -> list[str]:
        return sorted({"type_", "value_", *self._props.keys()})

    def __getattr__(self, name: str) -> "FakeHandle":
        try:
            return self._props[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    async def resolve_path_async(self, path: str | None) -> "FakeHandle":
        target = self
        if not path:
            return target
        for segment in path.split("."):
            clean = segment.strip()
            if not clean:
                continue
            target = getattr(target, clean)
        return target

    def __call__(self, *args: object) -> "FakeHandle":
        self.calls.append(args)
        if self._call_factory is None:
            return FakeHandle(f"{self._path}()", value={"args": list(args)})
        return self._call_factory(*args)

    async def call_async(self, *args: object) -> "FakeHandle":
        return self(*args)

    def __str__(self) -> str:
        return self._path


class FakeScriptWrapper:
    def __init__(self, eval_factories: dict[str, object | Callable[[], FakeHandle]]) -> None:
        self._eval_factories = eval_factories
        self.extra_handler = None
        self.loaded = False
        self.clear_scope_calls = 0
        self.compat_error: Exception | None = None
        self.eval_calls: list[str] = []

    def set_logger(self, loggers=None, *, extra_handler=None) -> None:
        del loggers
        self.extra_handler = extra_handler

    def load(self) -> None:
        self.loaded = True

    def ensure_runtime_compatible(self) -> None:
        if self.compat_error is not None:
            raise self.compat_error

    async def ensure_runtime_compatible_async(self) -> None:
        self.ensure_runtime_compatible()

    def clear_scope(self) -> None:
        self.clear_scope_calls += 1

    async def clear_scope_async(self) -> None:
        self.clear_scope()

    def eval(self, source: str) -> FakeHandle:
        self.eval_calls.append(source)
        factory = self._eval_factories.get(source)
        if factory is None:
            return FakeHandle(f"eval:{source}", value={"source": source})
        if callable(factory):
            return factory()
        return factory

    async def eval_async(self, source: str) -> FakeHandle:
        return self.eval(source)

    def emit_log(self, level: str, text: str) -> None:
        if self.extra_handler is not None:
            self.extra_handler(level, text)


class FakeSessionWrapper:
    def __init__(self, script: FakeScriptWrapper) -> None:
        self.script = script
        self.handlers: dict[str, object] = {}
        self.created_source: str | None = None
        self.is_detached = False

    def on(self, signal: str, callback) -> None:
        self.handlers[signal] = callback

    def create_script(self, source: str, name=None, snapshot=None, runtime=None, env=None) -> FakeScriptWrapper:
        del name, snapshot, runtime, env
        self.created_source = source
        return self.script

    def detach(self) -> None:
        self.is_detached = True


class FakeDevice:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self.attach_calls: list[int] = []
        self.spawn_calls: list[list[str]] = []
        self.resume_calls: list[int] = []
        self.last_session: FakeSessionWrapper | None = None

    def attach(self, pid: int) -> FakeSessionWrapper:
        self.attach_calls.append(pid)
        self.last_session = self._session_factory()
        return self.last_session

    def spawn(self, argv: list[str]) -> int:
        self.spawn_calls.append(argv)
        return 777

    def resume(self, pid: int) -> None:
        self.resume_calls.append(pid)


class FakeCompat:
    def __init__(self, device: FakeDevice, *, app_pid: int | None = None) -> None:
        self.device = device
        self.app_pid = app_pid
        self.get_device_calls: list[tuple[str, str | None]] = []

    def get_device(self, host: str, *, device_id: str | None = None) -> FakeDevice:
        self.get_device_calls.append((host, device_id))
        return self.device

    def enumerate_applications(self, device: FakeDevice, *, scope: str = "minimal"):
        del device, scope
        if self.app_pid is None:
            return []
        return [SimpleNamespace(identifier="com.example.demo", pid=self.app_pid)]


class FakeRemoteServerManager:
    def __init__(self) -> None:
        self.host_reachable = False
        self.host_error = "connection refused"
        self.running_pids: set[int] = set()
        self.boot_calls = 0
        self.stop_calls = 0
        self._stop_event = threading.Event()

    def inspect_remote_server(self, config: AppConfig, *, probe_abi: bool = True, probe_host: bool = False):
        del config, probe_abi, probe_host
        return SimpleNamespace(
            host_reachable=self.host_reachable,
            host_error=None if self.host_reachable else self.host_error,
        )

    def list_remote_server_pids(self, config: AppConfig) -> set[int]:
        del config
        return set(self.running_pids)

    def boot_remote_server(self, config: AppConfig, *, force_restart: bool = False) -> None:
        del config, force_restart
        self.boot_calls += 1
        self.running_pids = {4321}
        self.host_reachable = True
        self.host_error = None
        self._stop_event.wait(timeout=5)

    def stop_remote_server(self, config: AppConfig) -> set[int]:
        del config
        self.stop_calls += 1
        self.host_reachable = False
        self.host_error = "stopped"
        self._stop_event.set()
        stopped = set(self.running_pids)
        self.running_pids.clear()
        return stopped

    def ensure_remote_forward(self, config: AppConfig, *, action: str = "remote port forward") -> str:
        del config, action
        return "27042"


def _run_async(coro):
    return asyncio.run(coro)


def _write_agent_file(tmp_path: Path) -> Path:
    path = tmp_path / "_agent.js"
    path.write_text("16 /index.js\n✄\n", encoding="utf-8")
    return path


def _config(
    tmp_path: Path,
    *,
    host: str = "local",
    app: str | None = "com.example.demo",
) -> AppConfig:
    _write_agent_file(tmp_path)
    return AppConfig.model_validate(
        {
            "app": app,
            "jsfile": "_agent.js",
            "server": {"host": host, "device": "SERIAL123" if host != "local" else None},
            "script": {"nettools": {}},
        }
    ).resolve_paths(tmp_path, source_path=tmp_path / "config.yml")


def _snippet_handle() -> FakeHandle:
    dispose_result = FakeHandle("snippet/demo.dispose()", value="disposed", type_name="string")
    dispose = FakeHandle(
        "snippet/demo.dispose",
        props={},
        call_factory=lambda *args: dispose_result,
    )
    ping = FakeHandle(
        "snippet/demo.ping",
        props={},
        call_factory=lambda *args: FakeHandle(
            "snippet/demo.ping()",
            value=f"pong:{args[0]}" if args else "pong",
            type_name="string",
        ),
    )
    return FakeHandle(
        "snippet/demo",
        value={"installed": True},
        props={"dispose": dispose, "ping": ping},
    )


def test_session_open_reuses_same_target_and_force_replace_reopens(tmp_path: Path) -> None:
    async def scenario() -> None:
        script = FakeScriptWrapper({"snippet:demo": _snippet_handle})
        device = FakeDevice(lambda: FakeSessionWrapper(script))
        config = _config(tmp_path)
        manager = AsyncDebugSessionManager(
            config_loader=lambda path: config if Path(path).resolve() == config.source_path else None,  # type: ignore[return-value]
            compat_factory=lambda: FakeCompat(device, app_pid=321),
            session_factory=lambda raw_session, *, config, interactive: raw_session,
        )

        first = await manager.session_open(config_path=str(config.source_path), mode="attach", pid=321)
        second = await manager.session_open(config_path=str(config.source_path), mode="attach", pid=321)

        assert first.state == "live"
        assert second.state == "live"
        assert device.attach_calls == [321]

        with pytest.raises(MCPManagerError, match="already active for a different target"):
            await manager.session_open(config_path=str(config.source_path), mode="attach", pid=654)

        reopened = await manager.session_open(
            config_path=str(config.source_path),
            mode="attach",
            pid=654,
            force_replace=True,
        )

        assert reopened.target is not None
        assert reopened.target.attached_pid == 654
        assert device.attach_calls == [321, 654]
        await manager.aclose()

    _run_async(scenario())


def test_idle_timeout_closes_current_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        script = FakeScriptWrapper({})
        device = FakeDevice(lambda: FakeSessionWrapper(script))
        config = _config(tmp_path)
        manager = AsyncDebugSessionManager(
            idle_timeout_seconds=1,
            config_loader=lambda path: config if Path(path).resolve() == config.source_path else None,  # type: ignore[return-value]
            compat_factory=lambda: FakeCompat(device, app_pid=111),
            session_factory=lambda raw_session, *, config, interactive: raw_session,
        )

        await manager.session_open(config_path=str(config.source_path), mode="attach", pid=111)
        await asyncio.sleep(1.25)
        status = await manager.session_status()

        assert status.state == "closed"
        assert status.closed_reason == "idle timeout"
        assert device.last_session is not None and device.last_session.is_detached is True
        await manager.aclose()

    _run_async(scenario())


def test_snippet_lifecycle_and_log_ring(tmp_path: Path) -> None:
    async def scenario() -> None:
        root_handle = _snippet_handle()
        script = FakeScriptWrapper(
            {
                "snippet:demo": lambda: root_handle,
                "eval:arch": lambda: FakeHandle("eval:arch", value="arm64", type_name="string"),
            }
        )
        device = FakeDevice(lambda: FakeSessionWrapper(script))
        config = _config(tmp_path)
        manager = AsyncDebugSessionManager(
            config_loader=lambda path: config if Path(path).resolve() == config.source_path else None,  # type: ignore[return-value]
            compat_factory=lambda: FakeCompat(device, app_pid=111),
            session_factory=lambda raw_session, *, config, interactive: raw_session,
        )

        await manager.session_open(config_path=str(config.source_path), mode="attach", pid=111)
        script.emit_log("info", "hook-ready")
        await asyncio.sleep(0)

        eval_result = await manager.eval_js(source="eval:arch")
        installed = await manager.install_snippet(name="demo", source="snippet:demo")
        inspected = await manager.inspect_snippet(name="demo")
        called = await manager.call_snippet(name="demo", method="ping", args=[7])
        logs = await manager.tail_logs(limit=10)
        removed = await manager.remove_snippet(name="demo")
        listed = await manager.list_snippets()

        assert eval_result.result.preview == "arm64"
        assert installed.snippet.has_dispose is True
        assert "dispose" in inspected.snippet.root.props
        assert called.result.preview == "pong:7"
        assert any(entry.text == "hook-ready" for entry in logs.entries)
        assert removed.snippet.name == "demo"
        assert listed.snippets == []
        assert root_handle.release_calls == 1
        await manager.aclose()

    _run_async(scenario())


def test_broken_session_requires_explicit_recover_and_keeps_snippet_metadata(tmp_path: Path) -> None:
    async def scenario() -> None:
        script_sessions = [FakeScriptWrapper({"snippet:demo": _snippet_handle}) for _ in range(2)]
        session_index = {"value": 0}

        def make_session() -> FakeSessionWrapper:
            script = script_sessions[session_index["value"]]
            session_index["value"] += 1
            return FakeSessionWrapper(script)

        device = FakeDevice(make_session)
        config = _config(tmp_path)
        manager = AsyncDebugSessionManager(
            config_loader=lambda path: config if Path(path).resolve() == config.source_path else None,  # type: ignore[return-value]
            compat_factory=lambda: FakeCompat(device, app_pid=222),
            session_factory=lambda raw_session, *, config, interactive: raw_session,
        )

        await manager.session_open(config_path=str(config.source_path), mode="attach", pid=222)
        await manager.install_snippet(name="demo", source="snippet:demo")
        assert device.last_session is not None

        detached = device.last_session.handlers["detached"]
        detached("connection-closed", None)
        await asyncio.sleep(0)

        broken = await manager.session_status()
        assert broken.state == "broken"
        assert broken.snippets[0].state == "inactive"
        with pytest.raises(MCPManagerError, match="broken"):
            await manager.call_snippet(name="demo", method="ping", args=[1])

        recovered = await manager.session_recover()
        listed = await manager.list_snippets()

        assert recovered.state == "live"
        assert device.attach_calls == [222, 222]
        assert listed.snippets[0].state == "inactive"
        await manager.aclose()

    _run_async(scenario())


def test_remote_open_boots_owned_server_and_stops_it_on_close(tmp_path: Path) -> None:
    async def scenario() -> None:
        script = FakeScriptWrapper({})
        device = FakeDevice(lambda: FakeSessionWrapper(script))
        config = _config(tmp_path, host="127.0.0.1:27042")
        remote = FakeRemoteServerManager()
        manager = AsyncDebugSessionManager(
            config_loader=lambda path: config if Path(path).resolve() == config.source_path else None,  # type: ignore[return-value]
            compat_factory=lambda: FakeCompat(device, app_pid=333),
            server_manager_factory=lambda: remote,
            session_factory=lambda raw_session, *, config, interactive: raw_session,
        )

        opened = await manager.session_open(config_path=str(config.source_path), mode="attach", pid=333)
        closed = await manager.session_close()

        assert opened.target is not None
        assert opened.target.boot_owned is True
        assert remote.boot_calls == 1
        assert remote.stop_calls == 1
        assert closed.state == "closed"
        await manager.aclose()

    _run_async(scenario())


def test_session_open_surfaces_runtime_mismatch_from_loaded_agent(tmp_path: Path) -> None:
    async def scenario() -> None:
        script = FakeScriptWrapper({})
        script.compat_error = RPCCompatibilityError("RPC runtime mismatch: missing `/rpc`")
        device = FakeDevice(lambda: FakeSessionWrapper(script))
        config = _config(tmp_path)
        manager = AsyncDebugSessionManager(
            config_loader=lambda path: config if Path(path).resolve() == config.source_path else None,  # type: ignore[return-value]
            compat_factory=lambda: FakeCompat(device, app_pid=444),
            session_factory=lambda raw_session, *, config, interactive: raw_session,
        )

        with pytest.raises(RPCCompatibilityError, match="missing `/rpc`"):
            await manager.session_open(config_path=str(config.source_path), mode="attach", pid=444)

        await manager.aclose()

    _run_async(scenario())
