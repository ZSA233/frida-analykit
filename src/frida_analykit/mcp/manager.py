from __future__ import annotations

import atexit
import asyncio
import concurrent.futures
import threading
from collections.abc import Callable
from datetime import datetime

from ..compat import FridaCompat
from ..config import AppConfig
from ..server import FridaServerManager
from .async_manager import (
    AsyncDebugSessionManager,
    CompatProtocol,
    ConfigLoader,
    MCPManagerError,
    ServerManagerProtocol,
    SessionFactory,
    _default_session_factory,
)
from .models import (
    EvalResult,
    SessionMode,
    SessionStatus,
    SnippetCollectionResult,
    SnippetMutationResult,
    TailLogsResult,
)


class _AsyncManagerRunner:
    def __init__(self, manager_factory: Callable[[], AsyncDebugSessionManager]) -> None:
        self._manager_factory = manager_factory
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="frida-analykit-mcp-loop",
            daemon=True,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager: AsyncDebugSessionManager | None = None
        self._closed = False
        self._thread.start()
        self._ready.wait()

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._manager = self._manager_factory()
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def call(self, method_name: str, /, *args: object, **kwargs: object) -> object:
        if self._closed or self._loop is None or self._manager is None:
            raise MCPManagerError("DebugSessionManager background loop is closed")
        method = getattr(self._manager, method_name)
        future = asyncio.run_coroutine_threadsafe(method(*args, **kwargs), self._loop)
        try:
            return future.result()
        except concurrent.futures.CancelledError as exc:
            raise MCPManagerError("DebugSessionManager background loop is closed") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._loop is not None and self._manager is not None:
            try:
                shutdown = asyncio.run_coroutine_threadsafe(self._manager.aclose(), self._loop)
                shutdown.result(timeout=5)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


class DebugSessionManager:
    def __init__(
        self,
        *,
        idle_timeout_seconds: int = 1200,
        log_capacity: int = 200,
        config_loader: ConfigLoader = AppConfig.from_yaml,
        compat_factory: Callable[[], CompatProtocol] = FridaCompat,
        server_manager_factory: Callable[[], ServerManagerProtocol] = FridaServerManager,
        session_factory: SessionFactory = _default_session_factory,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._runner = _AsyncManagerRunner(
            lambda: AsyncDebugSessionManager(
                idle_timeout_seconds=idle_timeout_seconds,
                log_capacity=log_capacity,
                config_loader=config_loader,
                compat_factory=compat_factory,
                server_manager_factory=server_manager_factory,
                session_factory=session_factory,
                now_fn=now_fn,
            )
        )
        atexit.register(self._shutdown_at_exit)

    def session_open(
        self,
        *,
        config_path: str,
        mode: SessionMode,
        pid: int | None = None,
        force_replace: bool = False,
    ) -> SessionStatus:
        return self._runner.call(
            "session_open",
            config_path=config_path,
            mode=mode,
            pid=pid,
            force_replace=force_replace,
        )

    def session_status(self) -> SessionStatus:
        return self._runner.call("session_status")

    def session_close(self) -> SessionStatus:
        return self._runner.call("session_close")

    def session_recover(self) -> SessionStatus:
        return self._runner.call("session_recover")

    def eval_js(self, *, source: str) -> EvalResult:
        return self._runner.call("eval_js", source=source)

    def install_snippet(self, *, name: str, source: str, replace: bool = False) -> SnippetMutationResult:
        return self._runner.call("install_snippet", name=name, source=source, replace=replace)

    def call_snippet(self, *, name: str, method: str | None = None, args: list | None = None) -> EvalResult:
        return self._runner.call("call_snippet", name=name, method=method, args=args)

    def inspect_snippet(self, *, name: str) -> SnippetMutationResult:
        return self._runner.call("inspect_snippet", name=name)

    def remove_snippet(self, *, name: str) -> SnippetMutationResult:
        return self._runner.call("remove_snippet", name=name)

    def list_snippets(self) -> SnippetCollectionResult:
        return self._runner.call("list_snippets")

    def tail_logs(self, *, limit: int = 50) -> TailLogsResult:
        return self._runner.call("tail_logs", limit=limit)

    def resource_current_json(self) -> str:
        return self._runner.call("resource_current_json")

    def resource_snippets_json(self) -> str:
        return self._runner.call("resource_snippets_json")

    def resource_logs_json(self) -> str:
        return self._runner.call("resource_logs_json")

    def close(self) -> None:
        self._shutdown_at_exit()

    def _shutdown_at_exit(self) -> None:
        self._runner.close()
