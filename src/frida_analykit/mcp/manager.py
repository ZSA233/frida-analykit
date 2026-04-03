from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from pydantic import ValidationError

from ..compat import FridaCompat
from ..config import AppConfig
from ..rpc import RPCValueUnavailableError
from ..rpc.handler.js_handle import AsyncJsHandle
from ..server import FridaServerManager, ServerManagerError
from ..session import AsyncScriptWrapper, SessionWrapper
from .config import MCPStartupConfig
from .history import SessionHistoryManager, SessionHistoryRecord
from .history.service import SessionHistoryError
from .models import (
    EvalResult,
    HandleSnapshot,
    PreparedConfigSummary,
    PreparedSessionInspectResult,
    PreparedSessionPruneResult,
    QuickPathCheckSummary,
    QuickPathCompileProbeSummary,
    QuickPathReadinessSummary,
    QuickPathToolchainSummary,
    ServiceConfigSummary,
    SessionMode,
    SessionState,
    SessionStatus,
    SessionTargetStatus,
    SnippetCollectionResult,
    SnippetMutationResult,
    SnippetState,
    SnippetStatus,
    TailLogsEntry,
    TailLogsResult,
)
from .prepared import (
    PreparedArtifactManifest,
    PreparedSessionOpenRequest,
    PreparedWorkspaceBuildResult,
    PreparedWorkspaceError,
    PreparedWorkspaceManager,
)
from .prepared.models import QuickCapability, QuickTemplate

_REMOTE_BOOT_WAIT_SECONDS = 15.0
T = TypeVar("T")


class MCPManagerError(RuntimeError):
    pass


class RuntimeApplication(Protocol):
    identifier: str
    pid: int | None


class RuntimeDevice(Protocol):
    def attach(self, pid: int) -> object: ...

    def spawn(self, argv: list[str]) -> int: ...

    def resume(self, pid: int) -> None: ...


class CompatProtocol(Protocol):
    def get_device(self, host: str, *, device_id: str | None = None) -> RuntimeDevice: ...

    def enumerate_applications(self, device: RuntimeDevice, *, scope: str = "minimal") -> Iterable[RuntimeApplication]: ...


class ServerManagerProtocol(Protocol):
    def inspect_remote_server(
        self,
        config: AppConfig,
        *,
        probe_abi: bool = True,
        probe_host: bool = False,
    ) -> object: ...

    def list_remote_server_pids(self, config: AppConfig) -> set[int]: ...

    def boot_remote_server(self, config: AppConfig, *, force_restart: bool = False) -> None: ...

    def stop_remote_server(self, config: AppConfig) -> set[int]: ...

    def ensure_remote_forward(self, config: AppConfig, *, action: str = "remote port forward") -> str: ...


class PreparedWorkspaceProtocol(Protocol):
    @property
    def cache_root(self) -> Path: ...

    def prepare(self, request: PreparedSessionOpenRequest) -> PreparedWorkspaceBuildResult: ...

    def inspect(self, signature: str) -> PreparedArtifactManifest | None: ...

    def prune(
        self,
        *,
        signature: str | None = None,
        all_unused: bool = False,
        older_than_seconds: int | None = None,
        protected_signatures: set[str] | None = None,
    ) -> tuple[list[str], list[str]]: ...


class SessionHistoryProtocol(Protocol):
    @property
    def root(self) -> Path: ...

    def begin_session(
        self,
        *,
        open_kind: str,
        requested_mode: str,
        requested_pid: int | None,
        app: str | None,
        config_path: Path | None,
        prepared_artifact: PreparedArtifactManifest | None,
    ) -> SessionHistoryRecord: ...

    def record_open_success(
        self,
        record: SessionHistoryRecord,
        *,
        config: AppConfig,
        attached_pid: int,
        prepared_artifact: PreparedArtifactManifest | None,
    ) -> None: ...

    def record_open_failure(
        self,
        record: SessionHistoryRecord,
        *,
        message: str,
        config: AppConfig | None = None,
        prepared_artifact: PreparedArtifactManifest | None = None,
        attached_pid: int | None = None,
    ) -> None: ...

    def record_broken(
        self,
        record: SessionHistoryRecord,
        *,
        reason: str,
        snippet_names: list[str],
        crash_report: str | None,
    ) -> None: ...

    def record_recovered(self, record: SessionHistoryRecord, *, attached_pid: int) -> None: ...

    def record_closed(self, record: SessionHistoryRecord, *, reason: str) -> None: ...

    def persist_snippet(
        self,
        record: SessionHistoryRecord,
        *,
        name: str,
        source: str,
        replaced: bool,
    ) -> Path: ...

    def record_snippet_removed(self, record: SessionHistoryRecord, *, name: str) -> None: ...

    def materialize_prepared_workspace(
        self,
        record: SessionHistoryRecord,
        *,
        prepared_artifact: PreparedArtifactManifest,
    ) -> Path: ...


SessionFactory = Callable[..., SessionWrapper]
ConfigLoader = Callable[[str | Path], AppConfig]


async def _to_thread(callable_obj: Callable[..., T], /, *args: object, **kwargs: object) -> T:
    return await asyncio.to_thread(partial(callable_obj, *args, **kwargs))


def _default_session_factory(raw_session: object, *, config: AppConfig, interactive: bool) -> SessionWrapper:
    return SessionWrapper.from_session(raw_session, config=config, interactive=interactive)


def _default_quick_path_summary(*, cache_root: Path, checked_at: datetime) -> QuickPathReadinessSummary:
    return QuickPathReadinessSummary(
        state="failed",
        checked_at=checked_at,
        message="startup quick-path warmup summary was not provided",
        cache_root=QuickPathCheckSummary(
            state="skipped",
            path=cache_root,
            detail="startup quick-path warmup summary was not provided",
        ),
        npm=QuickPathCheckSummary(
            state="skipped",
            path=None,
            detail="startup quick-path warmup summary was not provided",
        ),
        frida_compile=QuickPathCheckSummary(
            state="skipped",
            path=None,
            detail="startup quick-path warmup summary was not provided",
        ),
        shared_toolchain=QuickPathToolchainSummary(
            state="skipped",
            root=cache_root / "_toolchains",
            agent_package_spec="unknown",
            detail="startup quick-path warmup summary was not provided",
        ),
        compile_probe=QuickPathCompileProbeSummary(
            state="skipped",
            workspace_root=cache_root / "_startup_probe",
            bundle_path=cache_root / "_startup_probe" / "_agent.js",
            detail="startup quick-path warmup summary was not provided",
            last_error=None,
        ),
    )


@dataclass(slots=True, frozen=True)
class OpenSessionSpec:
    config_path: Path
    mode: SessionMode
    requested_pid: int | None

    def matches(self, other: "OpenSessionSpec") -> bool:
        return (
            self.config_path == other.config_path
            and self.mode == other.mode
            and self.requested_pid == other.requested_pid
        )


@dataclass(slots=True)
class LogEntryRecord:
    timestamp: datetime
    source: str
    level: str
    text: str


@dataclass(slots=True)
class SnippetRecord:
    name: str
    source: str
    snapshot: HandleSnapshot
    installed_at: datetime
    last_called_at: datetime | None = None
    has_dispose: bool = False
    handle: AsyncJsHandle | None = None
    state: SnippetState = "active"

    def to_status(self) -> SnippetStatus:
        return SnippetStatus(
            name=self.name,
            source=self.source,
            state=self.state,
            installed_at=self.installed_at,
            last_called_at=self.last_called_at,
            has_dispose=self.has_dispose,
            root=self.snapshot,
        )


@dataclass(slots=True)
class RemoteServerLease:
    config: AppConfig
    manager: ServerManagerProtocol
    boot_owned: bool = False
    _boot_task: asyncio.Task[None] | None = None
    _boot_error: BaseException | None = None

    async def ensure_ready(self, *, timeout_seconds: float = _REMOTE_BOOT_WAIT_SECONDS) -> None:
        status = await _to_thread(self.manager.inspect_remote_server, self.config, probe_abi=False, probe_host=True)
        host_reachable = getattr(status, "host_reachable", None)
        if host_reachable:
            return

        running_pids = await _to_thread(self.manager.list_remote_server_pids, self.config)
        if running_pids:
            detail = getattr(status, "host_error", None) or "unknown transport error"
            pid_list = ", ".join(str(pid) for pid in sorted(running_pids))
            raise MCPManagerError(
                "remote frida-server is already running but the forwarded host is not reachable "
                f"({detail}; pids: {pid_list}). Repair the device session first, or run "
                "`frida-analykit server stop --config ...` before retrying."
            )

        if self._boot_task is None or self._boot_task.done():
            self._boot_error = None
            self._boot_task = asyncio.create_task(self._boot_worker())
            self.boot_owned = True

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        latest_status = status
        while loop.time() < deadline:
            if self._boot_error is not None:
                raise MCPManagerError(f"failed to boot remote frida-server: {self._boot_error}") from self._boot_error
            latest_status = await _to_thread(
                self.manager.inspect_remote_server,
                self.config,
                probe_abi=False,
                probe_host=True,
            )
            if getattr(latest_status, "host_reachable", None):
                return
            if self._boot_task is not None and self._boot_task.done() and self._boot_error is None:
                break
            await asyncio.sleep(0.25)

        detail = getattr(latest_status, "host_error", None) or "timed out while waiting for the remote host"
        raise MCPManagerError(f"failed to boot remote frida-server: {detail}")

    async def stop(self) -> None:
        if not self.boot_owned:
            return
        await _to_thread(self.manager.stop_remote_server, self.config)
        if self._boot_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._boot_task), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        self._boot_task = None
        self._boot_error = None
        self.boot_owned = False

    async def _boot_worker(self) -> None:
        try:
            await _to_thread(self.manager.boot_remote_server, self.config, force_restart=False)
        except BaseException as exc:
            self._boot_error = exc


@dataclass(slots=True)
class ActiveDebugSession:
    spec: OpenSessionSpec
    config: AppConfig
    device: RuntimeDevice
    session: SessionWrapper
    script: AsyncScriptWrapper
    attached_pid: int
    remote_lease: RemoteServerLease | None
    logs: deque[LogEntryRecord]
    snippets: dict[str, SnippetRecord]
    history: SessionHistoryRecord
    prepared_artifact: PreparedArtifactManifest | None = None
    state: SessionState = "live"
    last_activity_at: datetime | None = None
    broken_reason: str | None = None
    crash_report: str | None = None
    closed_reason: str | None = None
    closing: bool = False

    def append_log(self, *, source: str, level: str, text: str, timestamp: datetime) -> None:
        self.logs.append(LogEntryRecord(timestamp=timestamp, source=source, level=level, text=text))

    def mark_activity(self, *, timestamp: datetime) -> None:
        self.last_activity_at = timestamp

    def mark_broken(
        self,
        *,
        reason: str,
        crash_report: str | None,
        timestamp: datetime,
    ) -> None:
        self.state = "broken"
        self.broken_reason = reason
        self.crash_report = crash_report
        self.last_activity_at = timestamp
        for record in self.snippets.values():
            record.handle = None
            record.state = "inactive"

    def to_status(self, *, idle_timeout_seconds: int) -> SessionStatus:
        target = SessionTargetStatus(
            config_path=self.spec.config_path,
            mode=self.spec.mode,
            requested_pid=self.spec.requested_pid,
            attached_pid=self.attached_pid,
            app=self.config.app,
            host=self.config.server.host,
            device=self.config.server.device,
            boot_owned=self.remote_lease.boot_owned if self.remote_lease is not None else False,
        )
        snippets = [record.to_status() for record in self.snippets.values()]
        return SessionStatus(
            state=self.state,
            target=target,
            session_id=self.history.session_id,
            session_label=self.history.session_label,
            session_root=self.history.root,
            session_workspace=self.history.workspace_root,
            idle_timeout_seconds=idle_timeout_seconds,
            last_activity_at=self.last_activity_at,
            broken_reason=self.broken_reason,
            crash_report=self.crash_report,
            closed_reason=self.closed_reason,
            snippet_count=len(snippets),
            snippets=snippets,
            log_count=len(self.logs),
            prepared=self.prepared_artifact is not None,
            prepared_workspace=self.prepared_artifact.workspace_root if self.prepared_artifact is not None else None,
            prepared_signature=self.prepared_artifact.signature if self.prepared_artifact is not None else None,
            prepared_capabilities=(
                list(self.prepared_artifact.capabilities) if self.prepared_artifact is not None else []
            ),
        )


class DebugSessionManager:
    def __init__(
        self,
        *,
        idle_timeout_seconds: int = 1200,
        log_capacity: int = 200,
        config_loader: ConfigLoader = AppConfig.from_file,
        compat_factory: Callable[[], CompatProtocol] = FridaCompat,
        server_manager_factory: Callable[[], ServerManagerProtocol] = FridaServerManager,
        session_factory: SessionFactory = _default_session_factory,
        prepared_workspace: PreparedWorkspaceProtocol | None = None,
        session_history: SessionHistoryProtocol | None = None,
        startup_config: MCPStartupConfig | None = None,
        startup_instance_id: str | None = None,
        startup_started_at: datetime | None = None,
        startup_quick_path_summary: QuickPathReadinessSummary | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._startup_config = startup_config or MCPStartupConfig()
        self._idle_timeout_seconds = idle_timeout_seconds
        self._log_capacity = log_capacity
        self._config_loader = config_loader
        self._compat_factory = compat_factory
        self._server_manager_factory = server_manager_factory
        self._session_factory = session_factory
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._prepared_workspace = prepared_workspace or PreparedWorkspaceManager(startup_config=self._startup_config)
        self._session_history = session_history or SessionHistoryManager(
            self._startup_config.session_root(prepared_cache_root=self._prepared_workspace.cache_root),
            now_fn=self._now_fn,
        )
        self._startup_instance_id = startup_instance_id or uuid4().hex[:12]
        self._startup_started_at = startup_started_at or self._now_fn()
        self._startup_quick_path_summary = startup_quick_path_summary or _default_quick_path_summary(
            cache_root=self._prepared_workspace.cache_root,
            checked_at=self._startup_started_at,
        )
        self._current: ActiveDebugSession | None = None
        self._last_closed_reason: str | None = None
        self._lock = asyncio.Lock()
        self._idle_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._home_loop: asyncio.AbstractEventLoop | None = None
        self._closed = False

    @property
    def startup_instance_id(self) -> str:
        return self._startup_instance_id

    @property
    def startup_started_at(self) -> datetime:
        return self._startup_started_at

    async def session_open(
        self,
        *,
        config_path: str,
        mode: SessionMode,
        pid: int | None = None,
        force_replace: bool = False,
    ) -> SessionStatus:
        self._bind_home_loop()
        spec = OpenSessionSpec(
            config_path=Path(config_path).expanduser().resolve(),
            mode=mode,
            requested_pid=pid,
        )
        async with self._lock:
            self._ensure_not_closed()
            current = self._current
            if current is not None and current.spec.matches(spec) and not force_replace:
                self._touch_locked(current)
                return current.to_status(idle_timeout_seconds=self._idle_timeout_seconds)
            if current is not None and not force_replace:
                raise MCPManagerError(
                    "an MCP session is already active for a different target; call `session_close` "
                    "or retry with `force_replace=true`"
                )
            try:
                history_record = self._session_history.begin_session(
                    open_kind="explicit",
                    requested_mode=mode,
                    requested_pid=pid,
                    app=None,
                    config_path=spec.config_path,
                    prepared_artifact=None,
                )
            except SessionHistoryError as exc:
                raise MCPManagerError(str(exc)) from exc
            try:
                return await self._open_or_reuse_locked(
                    spec,
                    force_replace=force_replace,
                    prepared_artifact=None,
                    history_record=history_record,
                )
            except SessionHistoryError as exc:
                self._record_open_failure_best_effort(history_record, message=str(exc))
                raise MCPManagerError(str(exc)) from exc
            except Exception as exc:
                self._record_open_failure_best_effort(history_record, message=str(exc))
                raise

    async def session_open_quick(
        self,
        *,
        app: str,
        mode: SessionMode,
        capabilities: list[QuickCapability] | None = None,
        template: QuickTemplate = "minimal",
        pid: int | None = None,
        bootstrap_path: str | None = None,
        bootstrap_source: str | None = None,
        force_replace: bool = False,
    ) -> SessionStatus:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            try:
                request = PreparedSessionOpenRequest(
                    app=app,
                    mode=mode,
                    capabilities=capabilities or [],
                    template=template,
                    pid=pid,
                    bootstrap_path=bootstrap_path,
                    bootstrap_source=bootstrap_source,
                    force_replace=force_replace,
                )
                prepared = await _to_thread(self._prepared_workspace.prepare, request)
            except (PreparedWorkspaceError, ValidationError, ValueError, OSError) as exc:
                try:
                    history_record = self._session_history.begin_session(
                        open_kind="quick",
                        requested_mode=mode,
                        requested_pid=pid,
                        app=app,
                        config_path=None,
                        prepared_artifact=None,
                    )
                    self._record_open_failure_best_effort(history_record, message=str(exc))
                except SessionHistoryError:
                    pass
                raise MCPManagerError(str(exc)) from exc
            current = self._current
            if (
                current is not None
                and current.prepared_artifact is not None
                and current.prepared_artifact.signature == prepared.manifest.signature
                and current.spec.mode == mode
                and current.spec.requested_pid == pid
                and current.config.app == app
                and not force_replace
            ):
                current.prepared_artifact = prepared.manifest
                self._touch_locked(current)
                return current.to_status(idle_timeout_seconds=self._idle_timeout_seconds)
            if current is not None and not force_replace:
                raise MCPManagerError(
                    "an MCP session is already active for a different target; call `session_close` "
                    "or retry with `force_replace=true`"
                )
            try:
                history_record = self._session_history.begin_session(
                    open_kind="quick",
                    requested_mode=mode,
                    requested_pid=pid,
                    app=app,
                    config_path=None,
                    prepared_artifact=prepared.manifest,
                )
            except SessionHistoryError as exc:
                raise MCPManagerError(str(exc)) from exc
            try:
                runtime_config_path = self._session_history.materialize_prepared_workspace(
                    history_record,
                    prepared_artifact=prepared.manifest,
                )
                runtime_spec = OpenSessionSpec(
                    config_path=runtime_config_path.expanduser().resolve(),
                    mode=mode,
                    requested_pid=pid,
                )
                return await self._open_or_reuse_locked(
                    runtime_spec,
                    force_replace=force_replace,
                    prepared_artifact=prepared.manifest,
                    history_record=history_record,
                )
            except SessionHistoryError as exc:
                self._record_open_failure_best_effort(history_record, message=str(exc))
                raise MCPManagerError(str(exc)) from exc
            except Exception as exc:
                self._record_open_failure_best_effort(history_record, message=str(exc))
                raise

    async def session_status(self) -> SessionStatus:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            if self._current is None:
                return SessionStatus(
                    state="closed",
                    idle_timeout_seconds=self._idle_timeout_seconds,
                    closed_reason=self._last_closed_reason,
                )
            return self._current.to_status(idle_timeout_seconds=self._idle_timeout_seconds)

    async def prepared_session_inspect(self, *, signature: str | None = None) -> PreparedSessionInspectResult:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            resolved_signature = signature
            current = self._current
            if resolved_signature is None and current is not None and current.prepared_artifact is not None:
                resolved_signature = current.prepared_artifact.signature
            if resolved_signature is None:
                return PreparedSessionInspectResult(
                    prepared=False,
                    message="no prepared quick-session artifact is associated with the current MCP session",
                )
            manifest = await _to_thread(self._prepared_workspace.inspect, resolved_signature)
            if manifest is None:
                return PreparedSessionInspectResult(
                    prepared=False,
                    signature=resolved_signature,
                    message="prepared quick-session artifact not found in cache",
                )
            return self._prepared_inspect_result(
                manifest,
                current_session_uses_artifact=(
                    current is not None
                    and current.prepared_artifact is not None
                    and current.prepared_artifact.signature == manifest.signature
                ),
            )

    async def prepared_session_prune(
        self,
        *,
        signature: str | None = None,
        all_unused: bool = False,
        older_than_seconds: int | None = None,
    ) -> PreparedSessionPruneResult:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            protected: set[str] = set()
            if self._current is not None and self._current.prepared_artifact is not None:
                protected.add(self._current.prepared_artifact.signature)
            try:
                deleted, skipped = await _to_thread(
                    self._prepared_workspace.prune,
                    signature=signature,
                    all_unused=all_unused,
                    older_than_seconds=older_than_seconds,
                    protected_signatures=protected,
                )
            except PreparedWorkspaceError as exc:
                raise MCPManagerError(str(exc)) from exc
            return PreparedSessionPruneResult(
                deleted_signatures=deleted,
                skipped_active_signatures=skipped,
                message=None if deleted or skipped else "no prepared cache entries matched the prune selector",
            )

    async def session_close(self) -> SessionStatus:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            await self._close_current_locked(reason="session closed", stop_remote=True, drop_snippets=True)
            return SessionStatus(
                state="closed",
                idle_timeout_seconds=self._idle_timeout_seconds,
                closed_reason=self._last_closed_reason,
            )

    async def session_recover(self) -> SessionStatus:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            current = self._current
            if current is None:
                raise MCPManagerError("no MCP session is open; call `session_open` first")
            if current.state == "live":
                self._touch_locked(current)
                return current.to_status(idle_timeout_seconds=self._idle_timeout_seconds)
            if current.state != "broken":
                raise MCPManagerError(f"unable to recover a session in state `{current.state}`")

            preserved_snippets = self._clone_inactive_snippets(current.snippets)
            remote_lease = current.remote_lease
            reopened = await self._open_active_session(
                current.spec,
                preserved_snippets=preserved_snippets,
                remote_lease=remote_lease,
                prepared_artifact=current.prepared_artifact,
                history_record=current.history,
                history_transition="recover",
            )
            current.remote_lease = None
            await self._cleanup_session_transport_locked(current, stop_remote=False)
            self._current = reopened
            self._touch_locked(reopened)
            return reopened.to_status(idle_timeout_seconds=self._idle_timeout_seconds)

    async def eval_js(self, *, source: str) -> EvalResult:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            current = self._require_live_session_locked()
            result = await current.script.eval_async(source)
            try:
                payload = EvalResult(
                    session=current.to_status(idle_timeout_seconds=self._idle_timeout_seconds),
                    result=await self._snapshot_handle_async(result, include_props=False),
                )
            finally:
                await result.release_async()
            self._touch_locked(current)
            return payload

    async def install_snippet(
        self,
        *,
        name: str,
        source: str,
        replace: bool = False,
    ) -> SnippetMutationResult:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            current = self._require_live_session_locked()
            existing = current.snippets.get(name)
            if existing is not None and not replace:
                raise MCPManagerError(f"snippet `{name}` already exists; retry with `replace=true` to overwrite it")

            handle = await current.script.eval_async(source)
            snapshot: HandleSnapshot | None = None
            replaced = existing is not None
            installed = False
            try:
                snapshot = await self._snapshot_handle_async(handle, include_props=True)
                # Persist the replacement before touching the live snippet so a history write
                # failure cannot silently delete the previously working controller.
                self._session_history.persist_snippet(
                    current.history,
                    name=name,
                    source=source,
                    replaced=replaced,
                )
                if existing is not None:
                    await self._remove_snippet_locked(current, name=name, reason="replace")
                record = SnippetRecord(
                    name=name,
                    source=source,
                    snapshot=snapshot,
                    installed_at=self._now_fn(),
                    has_dispose="dispose" in snapshot.props,
                    handle=handle,
                    state="active",
                )
                current.snippets[name] = record
                installed = True
                current.append_log(
                    source="host",
                    level="info",
                    text=f"[mcp] {'replaced' if replaced else 'installed'} snippet `{name}`",
                    timestamp=self._now_fn(),
                )
                self._touch_locked(current)
                return SnippetMutationResult(
                    session=current.to_status(idle_timeout_seconds=self._idle_timeout_seconds),
                    snippet=record.to_status(),
                )
            except SessionHistoryError as exc:
                raise MCPManagerError(str(exc)) from exc
            finally:
                if not installed:
                    await self._dispose_snippet_handle_async(
                        handle,
                        has_dispose=snapshot is not None and "dispose" in snapshot.props,
                        suppress_dispose_error=True,
                    )

    async def call_snippet(
        self,
        *,
        name: str,
        method: str | None = None,
        args: list[Any] | None = None,
    ) -> EvalResult:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            current = self._require_live_session_locked()
            record = self._require_active_snippet_locked(current, name=name)
            target = await self._resolve_snippet_target_async(record.handle, method)
            result = await target.call_async(*(args or []))
            try:
                record.last_called_at = self._now_fn()
                payload = EvalResult(
                    session=current.to_status(idle_timeout_seconds=self._idle_timeout_seconds),
                    result=await self._snapshot_handle_async(result, include_props=False),
                )
            finally:
                await result.release_async()
            self._touch_locked(current)
            return payload

    async def inspect_snippet(self, *, name: str) -> SnippetMutationResult:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            current = self._require_session_locked()
            record = self._require_snippet_locked(current, name=name)
            if record.handle is not None:
                record.snapshot = await self._snapshot_handle_async(record.handle, include_props=True)
                record.has_dispose = "dispose" in record.snapshot.props
            payload = SnippetMutationResult(
                session=current.to_status(idle_timeout_seconds=self._idle_timeout_seconds),
                snippet=record.to_status(),
            )
            if current.state == "live":
                self._touch_locked(current)
            return payload

    async def remove_snippet(self, *, name: str) -> SnippetMutationResult:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            current = self._require_session_locked()
            try:
                removed = await self._remove_snippet_locked(current, name=name)
            except SessionHistoryError as exc:
                raise MCPManagerError(str(exc)) from exc
            if current.state == "live":
                self._touch_locked(current)
            return SnippetMutationResult(
                session=current.to_status(idle_timeout_seconds=self._idle_timeout_seconds),
                snippet=removed.to_status(),
            )

    async def list_snippets(self) -> SnippetCollectionResult:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            current = self._current
            if current is None:
                return SnippetCollectionResult(
                    session=SessionStatus(
                        state="closed",
                        idle_timeout_seconds=self._idle_timeout_seconds,
                        closed_reason=self._last_closed_reason,
                    ),
                    snippets=[],
                )
            if current.state == "live":
                self._touch_locked(current)
            return SnippetCollectionResult(
                session=current.to_status(idle_timeout_seconds=self._idle_timeout_seconds),
                snippets=[record.to_status() for record in current.snippets.values()],
            )

    async def tail_logs(self, *, limit: int = 50) -> TailLogsResult:
        self._bind_home_loop()
        async with self._lock:
            self._ensure_not_closed()
            current = self._current
            if current is None:
                return TailLogsResult(
                    session=SessionStatus(
                        state="closed",
                        idle_timeout_seconds=self._idle_timeout_seconds,
                        closed_reason=self._last_closed_reason,
                    ),
                    entries=[],
                )
            if current.state == "live":
                self._touch_locked(current)
            entries = [
                TailLogsEntry(timestamp=item.timestamp, source=item.source, level=item.level, text=item.text)
                for item in list(current.logs)[-max(limit, 0) :]
            ]
            return TailLogsResult(
                session=current.to_status(idle_timeout_seconds=self._idle_timeout_seconds),
                entries=entries,
            )

    async def resource_current_json(self) -> str:
        return self._json_resource(await self.session_status())

    async def resource_service_config_json(self) -> str:
        return self._json_resource(self._service_config_summary())

    async def resource_prepared_json(self) -> str:
        return self._json_resource(await self.prepared_session_inspect())

    async def resource_snippets_json(self) -> str:
        return self._json_resource(await self.list_snippets())

    async def resource_logs_json(self) -> str:
        return self._json_resource(await self.tail_logs(limit=self._log_capacity))

    async def aclose(self) -> None:
        self._bind_home_loop()
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            await self._close_current_locked(reason="process exit", stop_remote=True, drop_snippets=True)
        if self._background_tasks:
            await asyncio.gather(*tuple(self._background_tasks), return_exceptions=True)

    async def _open_or_reuse_locked(
        self,
        spec: OpenSessionSpec,
        *,
        force_replace: bool,
        prepared_artifact: PreparedArtifactManifest | None,
        history_record: SessionHistoryRecord,
    ) -> SessionStatus:
        current = self._current
        if current is not None and current.spec.matches(spec) and not force_replace:
            if prepared_artifact is not None:
                current.prepared_artifact = prepared_artifact
            if current.state == "live":
                self._touch_locked(current)
            return current.to_status(idle_timeout_seconds=self._idle_timeout_seconds)

        if current is not None and not force_replace:
            raise MCPManagerError(
                "an MCP session is already active for a different target; call `session_close` "
                "or retry with `force_replace=true`"
            )

        if current is not None:
            await self._close_current_locked(reason="replaced session", stop_remote=True, drop_snippets=True)

        self._current = await self._open_active_session(
            spec,
            prepared_artifact=prepared_artifact,
            history_record=history_record,
        )
        self._touch_locked(self._current)
        return self._current.to_status(idle_timeout_seconds=self._idle_timeout_seconds)

    async def _open_active_session(
        self,
        spec: OpenSessionSpec,
        *,
        preserved_snippets: dict[str, SnippetRecord] | None = None,
        remote_lease: RemoteServerLease | None = None,
        prepared_artifact: PreparedArtifactManifest | None = None,
        history_record: SessionHistoryRecord,
        history_transition: str = "open",
    ) -> ActiveDebugSession:
        config: AppConfig | None = None
        resolved_pid: int | None = None
        session: SessionWrapper | None = None
        config = await _to_thread(self._config_loader, spec.config_path)
        lease = remote_lease
        created_lease = False
        if config.server.is_remote and lease is None:
            lease = RemoteServerLease(
                config=config,
                manager=self._server_manager_factory(),
            )
            created_lease = True

        try:
            if lease is not None:
                await lease.ensure_ready()

            compat = self._compat_factory()
            device = await self._resolve_runtime_device(config, compat, remote_manager=lease.manager if lease else None)
            resolved_pid: int
            resume_after_load = False
            if spec.mode == "spawn":
                if not config.app:
                    raise MCPManagerError("`session_open` with mode `spawn` requires `config.app`")
                resolved_pid = await _to_thread(device.spawn, [config.app])
                resume_after_load = True
            else:
                resolved_pid = spec.requested_pid or await self._find_app_pid(device, compat, config)
                if resolved_pid is None:
                    raise MCPManagerError("unable to resolve a target pid; set `config.app` or pass `pid`")

            raw_session = await _to_thread(device.attach, resolved_pid)
            session = self._session_factory(raw_session, config=config, interactive=False)
            source = await _to_thread(config.jsfile.read_text, encoding="utf-8")
            script = await _to_thread(session.create_script_async, source)

            active = ActiveDebugSession(
                spec=spec,
                config=config,
                device=device,
                session=session,
                script=script,
                attached_pid=resolved_pid,
                remote_lease=lease,
                logs=deque(maxlen=self._log_capacity),
                snippets=preserved_snippets or {},
                history=history_record,
                prepared_artifact=prepared_artifact,
                last_activity_at=self._now_fn(),
            )
            session.on("detached", self._build_detached_handler(active))
            session.set_host_log_handler(lambda level, text: self._append_log(active, source="host", level=level, text=text))
            script.set_logger(extra_handler=lambda level, text: self._append_log(active, source="script", level=level, text=text))
            await _to_thread(script.load)
            await script.ensure_runtime_compatible_async()
            if resume_after_load:
                await _to_thread(device.resume, resolved_pid)
            if history_transition == "recover":
                self._session_history.record_recovered(history_record, attached_pid=resolved_pid)
            else:
                self._session_history.record_open_success(
                    history_record,
                    config=config,
                    attached_pid=resolved_pid,
                    prepared_artifact=prepared_artifact,
                )
            return active
        except ServerManagerError as exc:
            self._record_open_failure_best_effort(
                history_record,
                message=str(exc),
                config=config,
                prepared_artifact=prepared_artifact,
                attached_pid=resolved_pid,
            )
            if session is not None:
                await self._detach_session_best_effort(session)
            if created_lease and lease is not None:
                await self._stop_remote_lease(lease)
            raise MCPManagerError(str(exc)) from exc
        except Exception as exc:
            self._record_open_failure_best_effort(
                history_record,
                message=str(exc),
                config=config,
                prepared_artifact=prepared_artifact,
                attached_pid=resolved_pid,
            )
            if session is not None:
                await self._detach_session_best_effort(session)
            if created_lease and lease is not None:
                await self._stop_remote_lease(lease)
            raise

    async def _close_current_locked(
        self,
        *,
        reason: str,
        stop_remote: bool,
        drop_snippets: bool,
    ) -> None:
        current = self._current
        self._cancel_idle_task_locked()
        if current is None:
            self._last_closed_reason = reason
            return

        current.closing = True
        if drop_snippets and current.state == "live":
            for name in list(current.snippets):
                try:
                    await self._remove_snippet_locked(current, name=name)
                except Exception as exc:
                    current.append_log(
                        source="host",
                        level="error",
                        text=f"[mcp] failed to remove snippet `{name}` during close: {exc}",
                        timestamp=self._now_fn(),
                    )

        if current.state == "live":
            try:
                await current.script.clear_scope_async()
            except Exception as exc:
                current.append_log(
                    source="host",
                    level="error",
                    text=f"[mcp] failed to clear the remote scope during close: {exc}",
                    timestamp=self._now_fn(),
                )

        await self._cleanup_session_transport_locked(current, stop_remote=stop_remote)
        if drop_snippets:
            current.snippets.clear()
        current.closed_reason = reason
        try:
            self._session_history.record_closed(current.history, reason=reason)
        except SessionHistoryError as exc:
            current.append_log(
                source="host",
                level="error",
                text=f"[mcp] failed to record session close history: {exc}",
                timestamp=self._now_fn(),
            )
        self._last_closed_reason = reason
        self._current = None

    async def _cleanup_session_transport_locked(self, session: ActiveDebugSession, *, stop_remote: bool) -> None:
        try:
            if not session.session.is_detached:
                await _to_thread(session.session.detach)
        except Exception:
            pass
        if stop_remote and session.remote_lease is not None:
            await self._stop_remote_lease(session.remote_lease)

    async def _remove_snippet_locked(
        self,
        current: ActiveDebugSession,
        *,
        name: str,
        reason: str = "remove",
    ) -> SnippetRecord:
        record = self._require_snippet_locked(current, name=name)
        if record.handle is not None:
            await self._dispose_snippet_handle_async(record.handle, has_dispose=record.has_dispose)
        record.handle = None
        record.state = "inactive"
        current.snippets.pop(name, None)
        if reason != "replace":
            self._session_history.record_snippet_removed(current.history, name=name)
            current.append_log(
                source="host",
                level="info",
                text=f"[mcp] removed snippet `{name}`",
                timestamp=self._now_fn(),
            )
        return record

    @staticmethod
    async def _dispose_snippet_handle_async(
        handle: AsyncJsHandle,
        *,
        has_dispose: bool,
        suppress_dispose_error: bool = False,
    ) -> None:
        try:
            if has_dispose:
                dispose_handle = await handle.resolve_path_async("dispose")
                dispose_result = await dispose_handle.call_async()
                await dispose_result.release_async()
        except Exception:
            if not suppress_dispose_error:
                raise
        await handle.release_async()

    def _require_session_locked(self) -> ActiveDebugSession:
        if self._current is None:
            raise MCPManagerError("no MCP session is open; call `session_open` first")
        return self._current

    def _require_live_session_locked(self) -> ActiveDebugSession:
        current = self._require_session_locked()
        if current.state == "broken":
            detail = current.broken_reason or "session detached unexpectedly"
            raise MCPManagerError(
                f"the current MCP session is broken ({detail}); call `session_recover` or `session_close` first"
            )
        if current.state != "live":
            raise MCPManagerError(f"the current MCP session is not live (state: `{current.state}`)")
        return current

    @staticmethod
    def _require_snippet_locked(current: ActiveDebugSession, *, name: str) -> SnippetRecord:
        record = current.snippets.get(name)
        if record is None:
            raise MCPManagerError(f"snippet `{name}` does not exist")
        return record

    def _require_active_snippet_locked(self, current: ActiveDebugSession, *, name: str) -> SnippetRecord:
        record = self._require_snippet_locked(current, name=name)
        if record.handle is None or record.state != "active":
            raise MCPManagerError(
                f"snippet `{name}` is inactive in the current session; reinstall it before calling it again"
            )
        return record

    async def _resolve_runtime_device(
        self,
        config: AppConfig,
        compat: CompatProtocol,
        *,
        remote_manager: ServerManagerProtocol | None,
    ) -> RuntimeDevice:
        host = config.server.host
        if host in {"local", "local://"}:
            return await _to_thread(compat.get_device, host)
        if host in {"usb", "usb://"}:
            return await _to_thread(compat.get_device, host, device_id=config.server.device)
        if config.server.is_remote:
            manager = remote_manager or self._server_manager_factory()
            await _to_thread(manager.ensure_remote_forward, config, action="MCP device connection")
        return await _to_thread(compat.get_device, host)

    async def _find_app_pid(self, device: RuntimeDevice, compat: CompatProtocol, config: AppConfig) -> int | None:
        if not config.app:
            return None
        applications = await _to_thread(lambda: list(compat.enumerate_applications(device, scope="minimal")))
        for app in applications:
            if getattr(app, "identifier", "").strip() == config.app:
                return getattr(app, "pid", None)
        return None

    def _build_detached_handler(self, active: ActiveDebugSession) -> Callable[[str, Any | None], None]:
        loop = self._home_loop
        if loop is None:
            raise MCPManagerError("async MCP manager has no home event loop")

        def on_detached(reason: str, crash: Any | None) -> None:
            if loop.is_closed():
                return
            loop.call_soon_threadsafe(self._schedule_detached, active, reason, crash)

        return on_detached

    def _schedule_detached(self, active: ActiveDebugSession, reason: str, crash: Any | None) -> None:
        if not self._lock.locked():
            self._apply_detached_locked(active, reason, crash)
            return
        task = asyncio.create_task(self._handle_detached(active, reason, crash))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _handle_detached(self, active: ActiveDebugSession, reason: str, crash: Any | None) -> None:
        async with self._lock:
            self._apply_detached_locked(active, reason, crash)

    def _append_log(self, active: ActiveDebugSession, *, source: str, level: str, text: str) -> None:
        loop = self._home_loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._append_log_on_loop, active, source, level, text)

    def _append_log_on_loop(self, active: ActiveDebugSession, source: str, level: str, text: str) -> None:
        if self._current is not active:
            return
        active.append_log(source=source, level=level, text=text, timestamp=self._now_fn())

    def _touch_locked(self, active: ActiveDebugSession) -> None:
        active.mark_activity(timestamp=self._now_fn())
        self._reset_idle_task_locked()

    def _reset_idle_task_locked(self) -> None:
        self._cancel_idle_task_locked()
        current = self._current
        if current is None or self._idle_timeout_seconds <= 0:
            return
        expected = current.last_activity_at
        self._idle_task = asyncio.create_task(self._idle_timeout_worker(expected))

    def _cancel_idle_task_locked(self) -> None:
        if self._idle_task is not None:
            task = self._idle_task
            self._idle_task = None
            if task is not asyncio.current_task():
                task.cancel()

    async def _idle_timeout_worker(self, expected: datetime | None) -> None:
        try:
            await asyncio.sleep(self._idle_timeout_seconds)
            async with self._lock:
                current = self._current
                if current is None or current.last_activity_at != expected:
                    return
                await self._close_current_locked(reason="idle timeout", stop_remote=True, drop_snippets=True)
        except asyncio.CancelledError:
            return

    def _apply_detached_locked(self, active: ActiveDebugSession, reason: str, crash: Any | None) -> None:
        if self._current is not active or active.closing:
            return
        crash_report = getattr(crash, "report", None)
        active.mark_broken(
            reason=reason,
            crash_report=crash_report,
            timestamp=self._now_fn(),
        )
        try:
            self._session_history.record_broken(
                active.history,
                reason=reason,
                snippet_names=list(active.snippets),
                crash_report=crash_report,
            )
        except SessionHistoryError as exc:
            active.append_log(
                source="host",
                level="error",
                text=f"[mcp] failed to record broken session history: {exc}",
                timestamp=self._now_fn(),
            )
        detail = reason.strip() or "detached"
        active.append_log(
            source="host",
            level="error",
            text=f"[mcp] session detached: {detail}",
            timestamp=self._now_fn(),
        )
        if crash_report:
            active.append_log(
                source="host",
                level="error",
                text=crash_report,
                timestamp=self._now_fn(),
            )
        self._reset_idle_task_locked()

    async def _snapshot_handle_async(self, handle: AsyncJsHandle, *, include_props: bool) -> HandleSnapshot:
        props = sorted(name for name in dir(handle) if not name.startswith("__")) if include_props else []
        preview_available = False
        preview: Any | None = None
        preview_error: str | None = None
        try:
            preview = self._to_json_compatible(await handle.resolve_async())
            preview_available = True
        except RPCValueUnavailableError as exc:
            preview_error = str(exc)
        except Exception as exc:
            preview_error = str(exc)
        return HandleSnapshot(
            path=str(handle),
            type=handle.type_,
            props=props,
            preview_available=preview_available,
            preview=preview,
            preview_error=preview_error,
        )

    def _clone_inactive_snippets(self, records: dict[str, SnippetRecord]) -> dict[str, SnippetRecord]:
        clones: dict[str, SnippetRecord] = {}
        for name, record in records.items():
            clones[name] = SnippetRecord(
                name=record.name,
                source=record.source,
                snapshot=record.snapshot.model_copy(deep=True),
                installed_at=record.installed_at,
                last_called_at=record.last_called_at,
                has_dispose=record.has_dispose,
                handle=None,
                state="inactive",
            )
        return clones

    @staticmethod
    async def _resolve_snippet_target_async(
        handle: AsyncJsHandle | None,
        method: str | None,
    ) -> AsyncJsHandle:
        if handle is None:
            raise MCPManagerError("snippet handle is no longer live")
        return await handle.resolve_path_async(method)

    def _bind_home_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._home_loop is None:
            self._home_loop = loop
            return
        if self._home_loop is not loop:
            raise MCPManagerError("the MCP session manager must be used from a single event loop")

    def _ensure_not_closed(self) -> None:
        if self._closed:
            raise MCPManagerError("the MCP session manager is closed")

    @staticmethod
    def _to_json_compatible(value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (list, tuple)):
            return [DebugSessionManager._to_json_compatible(item) for item in value]
        if isinstance(value, dict):
            return {str(key): DebugSessionManager._to_json_compatible(item) for key, item in value.items()}
        return str(value)

    @staticmethod
    def _json_resource(value: Any) -> str:
        if hasattr(value, "model_dump"):
            payload = value.model_dump(mode="json")
        else:
            payload = value
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _prepared_inspect_result(
        manifest: PreparedArtifactManifest,
        *,
        current_session_uses_artifact: bool,
    ) -> PreparedSessionInspectResult:
        return PreparedSessionInspectResult(
            prepared=True,
            signature=manifest.signature,
            workspace_root=manifest.workspace_root,
            config_path=manifest.config_path,
            bundle_path=manifest.bundle_path,
            template=manifest.template,
            capabilities=list(manifest.capabilities),
            imports=list(manifest.imports),
            bootstrap_kind=manifest.bootstrap_kind,
            bootstrap_path=manifest.bootstrap_path,
            bootstrap_source=manifest.bootstrap_source,
            config=PreparedConfigSummary(
                app=manifest.config.app,
                host=manifest.config.host,
                device=manifest.config.device,
                path=manifest.config.path,
                jsfile=manifest.bundle_path,
                datadir=manifest.config.datadir,
                stdout=manifest.config.stdout,
                stderr=manifest.config.stderr,
                dextools_output_dir=manifest.config.dextools_output_dir,
                elftools_output_dir=manifest.config.elftools_output_dir,
                ssl_log_secret=manifest.config.ssl_log_secret,
            ),
            build_ready=manifest.build_ready,
            last_prepare_outcome=manifest.last_prepare_outcome,
            last_build_error=manifest.last_build_error,
            last_prepared_at=manifest.last_prepared_at,
            last_used_at=manifest.last_used_at,
            current_session_uses_artifact=current_session_uses_artifact,
        )

    @staticmethod
    async def _stop_remote_lease(lease: RemoteServerLease) -> None:
        try:
            await lease.stop()
        except Exception:
            pass

    def _record_open_failure_best_effort(
        self,
        history_record: SessionHistoryRecord,
        *,
        message: str,
        config: AppConfig | None = None,
        prepared_artifact: PreparedArtifactManifest | None = None,
        attached_pid: int | None = None,
    ) -> None:
        try:
            self._session_history.record_open_failure(
                history_record,
                message=message,
                config=config,
                prepared_artifact=prepared_artifact,
                attached_pid=attached_pid,
            )
        except SessionHistoryError:
            pass

    @staticmethod
    async def _detach_session_best_effort(session: SessionWrapper) -> None:
        try:
            if not session.is_detached:
                await _to_thread(session.detach)
        except Exception:
            pass

    def _service_config_summary(self) -> ServiceConfigSummary:
        return self._startup_config.to_summary(
            service_instance_id=self._startup_instance_id,
            service_started_at=self._startup_started_at,
            prepared_cache_root=self._prepared_workspace.cache_root,
            session_root=self._session_history.root,
            idle_timeout_seconds=self._idle_timeout_seconds,
            quick_path=self._startup_quick_path_summary,
        )
