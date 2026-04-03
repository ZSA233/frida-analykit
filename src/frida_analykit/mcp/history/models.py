from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HistoryOpenKind = Literal["quick", "explicit"]
HistorySessionState = Literal["opening", "live", "broken", "closed", "failed"]
HistorySnippetState = Literal["active", "inactive", "removed"]
HistoryEventType = Literal[
    "open_started",
    "open_succeeded",
    "open_failed",
    "snippet_installed",
    "snippet_replaced",
    "snippet_removed",
    "snippet_inactive",
    "session_broken",
    "session_recovered",
    "session_closed",
    "session_idle_timeout_closed",
]


@dataclass(slots=True, frozen=True)
class SessionHistoryRecord:
    session_id: str
    session_label: str
    root: Path
    workspace_root: Path
    snippets_root: Path
    manifest_path: Path
    events_path: Path


class SessionHistorySnippetVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    stored_at: datetime
    file_path: Path


class SessionHistorySnippetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    safe_name: str
    state: HistorySnippetState
    updated_at: datetime
    versions: list[SessionHistorySnippetVersion] = Field(default_factory=list)


class SessionHistoryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    session_label: str
    session_root: Path
    workspace_root: Path
    created_at: datetime
    updated_at: datetime
    state: HistorySessionState
    open_kind: HistoryOpenKind
    requested_mode: str | None = None
    requested_pid: int | None = None
    app: str | None = None
    config_path: Path | None = None
    prepared_signature: str | None = None
    prepared_workspace: Path | None = None
    attached_pid: int | None = None
    broken_reason: str | None = None
    closed_reason: str | None = None
    last_error: str | None = None
    snippets: dict[str, SessionHistorySnippetManifest] = Field(default_factory=dict)


class SessionHistoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    event: HistoryEventType
    detail: dict[str, Any] = Field(default_factory=dict)
