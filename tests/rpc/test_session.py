import asyncio
import io
from datetime import datetime
from pathlib import Path

from frida_analykit._version import __version__
from frida_analykit.config import AppConfig
from frida_analykit.logging import LoggerBundle
from frida_analykit.rpc.protocol import RPCRuntimeInfo
from frida_analykit.session import (
    AsyncScriptWrapper,
    SessionWrapper,
    SyncScriptWrapper,
    render_session_banner,
    try_inject_environ,
)


def _config(
    tmp_path: Path,
    *,
    jsfile: str = "_agent.js",
    stdout: str | None = None,
    stderr: str | None = None,
) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": jsfile,
            "server": {"host": "local"},
            "agent": {"stdout": stdout, "stderr": stderr},
            "script": {"nettools": {}},
        }
    ).resolve_paths(tmp_path, source_path=tmp_path / "config.yml")


class _FakeSyncExports:
    def __init__(self) -> None:
        self.scope_clear_calls: list[tuple[object, ...]] = []

    def plain_payload(self) -> dict[str, str]:
        return {"type": "demo"}

    def scope_del(self, *args, **kwargs) -> None:
        del args, kwargs

    def scope_clear(self, *args, **kwargs) -> None:
        self.scope_clear_calls.append(args)
        del kwargs

    def rpc_runtime_info(self) -> dict[str, object]:
        return RPCRuntimeInfo(protocol_version=2, features=["handle_ref", "async_scope"]).model_dump(mode="json")


class _FakeAsyncExports:
    async def plain_payload(self) -> dict[str, str]:
        return {"type": "demo"}

    async def scope_clear(self, *args, **kwargs) -> None:
        del args, kwargs


class _FakeScript:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.log_handler = None
        self.exports_sync = _FakeSyncExports()
        self.exports_async = _FakeAsyncExports()

    def on(self, signal: str, callback) -> None:
        self.handlers[signal] = callback

    def set_log_handler(self, handler) -> None:
        self.log_handler = handler

    def list_exports_sync(self) -> list[str]:
        return ["plainPayload", "scopeClear", "rpcRuntimeInfo"]

    async def list_exports_async(self) -> list[str]:
        return ["plainPayload", "scopeClear", "rpcRuntimeInfo"]


class _FakeSession:
    def __init__(self) -> None:
        self.script = _FakeScript()
        self.last_source: str | None = None
        self.is_detached = False

    def create_script(self, source: str, name=None, snapshot=None, runtime=None):
        del name, snapshot, runtime
        self.last_source = source
        return self.script

    def on(self, signal: str, callback) -> None:
        self.handlers = getattr(self, "handlers", {})
        self.handlers[signal] = callback

    def off(self, signal: str, callback) -> None:
        del signal, callback

    def detach(self) -> None:
        self.is_detached = True

    def resume(self) -> None:
        pass

    def enable_child_gating(self) -> None:
        pass

    def disable_child_gating(self) -> None:
        pass


def test_try_inject_environ_wraps_module_import_with_bootstrap_guard() -> None:
    script_src = "16 /index.js\n✄\nconsole.log('demo')\n"

    injected = try_inject_environ(script_src, {"OnRPC": True, "BatchMaxBytes": 1024})

    assert 'globalThis.__FRIDA_ANALYKIT_CONFIG__' in injected
    assert 'await import("/index.js");' in injected
    assert "catch (error)" in injected
    assert 'console.error(`[frida-analykit/bootstrap] ${description}`);' in injected
    assert '"BatchMaxBytes": 1024' in injected


def test_session_wrapper_reuses_existing_logger_bundle(monkeypatch, tmp_path: Path) -> None:
    shared = io.StringIO()
    bundle = LoggerBundle(stdout=shared, stderr=shared)
    calls: list[object] = []

    def fake_build_loggers(agent):
        calls.append(agent)
        return bundle

    monkeypatch.setattr("frida_analykit.session.build_loggers", fake_build_loggers)

    session = SessionWrapper(_FakeSession(), config=_config(tmp_path, stdout="logs/outerr.log", stderr="logs/outerr.log"))
    script = session.create_script("16 /index.js\n✄\n")

    script.set_logger()

    assert len(calls) == 1
    session._runtime.resolver._registry.handle_exception({"description": "boom"}, None)
    session._session.script.log_handler("info", "hello")
    session._session.script.log_handler("error", "trace")
    output = shared.getvalue()
    assert "[script-error] boom" in output
    assert "hello" in output
    assert "trace" in output


def test_open_script_prints_resolved_output_paths(tmp_path: Path, capsys) -> None:
    jsfile = tmp_path / "_agent.js"
    jsfile.write_text("16 /index.js\n✄\n", encoding="utf-8")
    config = _config(tmp_path, stdout="logs/stdout.log", stderr="logs/stderr.log")

    session = SessionWrapper(_FakeSession(), config=config)

    session.open_script(str(config.jsfile))

    output = capsys.readouterr().out
    assert "███████╗██████╗" in output
    assert f"v{__version__} ready at " in output
    assert "➜  Host:" in output
    assert "➜  Target:" in output
    assert "➜  Script:" in output
    assert "➜  Stdout:" in output
    assert "➜  Stderr:" in output
    assert "_agent.js" in output
    assert "stdout.log" in output
    assert "stderr.log" in output


def test_render_session_banner_includes_core_metadata(tmp_path: Path) -> None:
    config = _config(tmp_path, stdout="logs/outerr.log", stderr="logs/outerr.log").model_copy(
        update={"app": "com.example.demo"}
    )
    banner = render_session_banner(
        config,
        jsfile=config.jsfile,
        updated=datetime(2026, 3, 27, 12, 0, 0),
    )

    assert "███████╗██████╗" in banner
    assert f"v{__version__} ready at 12:00:00" in banner
    assert "➜  Host:" in banner
    assert "➜  Target:" in banner
    assert "➜  Script:" in banner
    assert "➜  Log Output:" in banner
    assert "com.example.demo" in banner
    assert "_agent.js" in banner
    assert "outerr.log" in banner


def test_explicit_sync_and_async_script_wrappers_keep_exports_transparent(tmp_path: Path) -> None:
    session = SessionWrapper(_FakeSession(), config=_config(tmp_path))
    sync_script = session.create_script("16 /index.js\n✄\n")
    async_script = session.create_script_async("16 /index.js\n✄\n")

    assert sync_script.exports_sync.plain_payload() == {"type": "demo"}
    assert asyncio.run(async_script.exports_async.plain_payload()) == {"type": "demo"}


def test_session_wrapper_exposes_sync_default_and_explicit_async_script_owners(tmp_path: Path) -> None:
    session = SessionWrapper(_FakeSession(), config=_config(tmp_path))

    sync_script = session.create_script("16 /index.js\n✄\n")
    async_script = session.create_script_async("16 /index.js\n✄\n")
    opened_script_path = tmp_path / "_agent.js"
    opened_script_path.write_text("16 /index.js\n✄\n", encoding="utf-8")
    opened_sync_script = session.open_script(str(opened_script_path))

    assert isinstance(sync_script, SyncScriptWrapper)
    assert isinstance(async_script, AsyncScriptWrapper)
    assert isinstance(opened_sync_script, SyncScriptWrapper)
    assert hasattr(sync_script, "eval") and not hasattr(sync_script, "eval_async")
    assert hasattr(async_script, "eval_async") and not hasattr(async_script, "eval")
    assert hasattr(opened_sync_script, "eval") and not hasattr(opened_sync_script, "eval_async")


def test_session_wrapper_injects_default_batch_limit(tmp_path: Path) -> None:
    fake_session = _FakeSession()
    base_config = _config(tmp_path)
    config = base_config.model_copy(
        update={
            "script": base_config.script.model_copy(
                update={
                    "rpc": base_config.script.rpc.model_copy(update={"batch_max_bytes": 2048}),
                }
            )
        }
    )
    session = SessionWrapper(fake_session, config=config)

    session.create_script("16 /index.js\n✄\n")

    assert fake_session.last_source is not None
    assert '"BatchMaxBytes": 2048' in fake_session.last_source


def test_script_wrapper_clear_scope_uses_public_sync_cleanup_path(tmp_path: Path) -> None:
    fake_session = _FakeSession()
    session = SessionWrapper(fake_session, config=_config(tmp_path))
    script = session.create_script("16 /index.js\n✄\n")

    script.clear_scope()

    assert fake_session.script.exports_sync.scope_clear_calls == [(script.scope_id,)]


def test_script_wrapper_set_logger_can_tee_into_external_handler(monkeypatch, tmp_path: Path) -> None:
    shared = io.StringIO()
    bundle = LoggerBundle(stdout=shared, stderr=shared)
    seen: list[tuple[str, str]] = []

    monkeypatch.setattr("frida_analykit.session.build_loggers", lambda agent: bundle)

    session = SessionWrapper(_FakeSession(), config=_config(tmp_path))
    script = session.create_script("16 /index.js\n✄\n")

    script.set_logger(extra_handler=lambda level, text: seen.append((level, text)))
    session._session.script.log_handler("info", "hook-ready")

    assert "hook-ready" in shared.getvalue()
    assert seen == [("info", "hook-ready")]


def test_script_wrapper_can_probe_runtime_compatibility_through_public_api(tmp_path: Path) -> None:
    session = SessionWrapper(_FakeSession(), config=_config(tmp_path))
    script = session.create_script("16 /index.js\n✄\n")

    script.ensure_runtime_compatible()
