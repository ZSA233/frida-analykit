from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import AppConfig
from ..rpc.handler.js_handle import AsyncJsHandle
from ..session import AsyncScriptWrapper, SessionWrapper
from .history import SessionHistoryRecord
from .models import (
    HandleSnapshot,
    SessionMode,
    SessionState,
    SessionStatus,
    SessionTargetStatus,
    SnippetState,
    SnippetStatus,
)
from .prepared.models import PreparedArtifactManifest
from .protocols import RuntimeDevice
from .remote import RemoteServerLease


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
