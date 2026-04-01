from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SessionMode = Literal["attach", "spawn"]
SessionState = Literal["closed", "live", "broken"]
SnippetState = Literal["active", "inactive"]


class HandleSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    type: str
    props: list[str] = Field(default_factory=list)
    preview_available: bool = False
    preview: Any | None = None
    preview_error: str | None = None


class SnippetStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    state: SnippetState
    installed_at: datetime
    last_called_at: datetime | None = None
    has_dispose: bool = False
    root: HandleSnapshot


class SessionTargetStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_path: Path
    mode: SessionMode
    requested_pid: int | None = None
    attached_pid: int | None = None
    app: str | None = None
    host: str
    device: str | None = None
    boot_owned: bool = False


class SessionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: SessionState
    target: SessionTargetStatus | None = None
    idle_timeout_seconds: int
    last_activity_at: datetime | None = None
    broken_reason: str | None = None
    crash_report: str | None = None
    closed_reason: str | None = None
    snippet_count: int = 0
    snippets: list[SnippetStatus] = Field(default_factory=list)
    log_count: int = 0


class EvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: SessionStatus
    result: HandleSnapshot


class SnippetMutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: SessionStatus
    snippet: SnippetStatus


class SnippetCollectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: SessionStatus
    snippets: list[SnippetStatus] = Field(default_factory=list)


class TailLogsEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    level: str
    text: str


class TailLogsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: SessionStatus
    entries: list[TailLogsEntry] = Field(default_factory=list)
