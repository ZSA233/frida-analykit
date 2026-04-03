from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SessionMode = Literal["attach", "spawn"]
SessionState = Literal["closed", "live", "broken"]
SnippetState = Literal["active", "inactive"]
PreparedOutcome = Literal["cache_hit", "rebuilt", "failed"]
BootstrapKind = Literal["none", "source", "path"]
QuickPathState = Literal["ready", "failed"]
QuickPathCheckState = Literal["ready", "failed", "skipped"]
QuickPathToolchainState = Literal["cache_hit", "installed", "failed", "skipped"]
QuickPathCompileState = Literal["compiled", "failed", "skipped"]


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
    session_id: str | None = None
    session_label: str | None = None
    session_root: Path | None = None
    session_workspace: Path | None = None
    idle_timeout_seconds: int
    last_activity_at: datetime | None = None
    broken_reason: str | None = None
    crash_report: str | None = None
    closed_reason: str | None = None
    snippet_count: int = 0
    snippets: list[SnippetStatus] = Field(default_factory=list)
    log_count: int = 0
    prepared: bool = False
    prepared_workspace: Path | None = None
    prepared_signature: str | None = None
    prepared_capabilities: list[str] = Field(default_factory=list)


class ServiceAgentConfigSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datadir: Path | None = None
    stdout: Path | None = None
    stderr: Path | None = None


class ServiceScriptConfigSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dextools_output_dir: Path | None = None
    elftools_output_dir: Path | None = None
    ssl_log_secret: Path | None = None


class ServiceServerConfigSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    device: str | None = None
    path: str


class QuickPathCheckSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: QuickPathCheckState
    path: Path | None = None
    detail: str | None = None


class QuickPathToolchainSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: QuickPathToolchainState
    root: Path
    agent_package_spec: str
    detail: str | None = None


class QuickPathCompileProbeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: QuickPathCompileState
    workspace_root: Path
    bundle_path: Path
    detail: str | None = None
    last_error: str | None = None


class QuickPathReadinessSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: QuickPathState
    checked_at: datetime
    message: str | None = None
    cache_root: QuickPathCheckSummary
    npm: QuickPathCheckSummary
    frida_compile: QuickPathCheckSummary
    shared_toolchain: QuickPathToolchainSummary
    compile_probe: QuickPathCompileProbeSummary


class ServiceConfigSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_instance_id: str
    service_started_at: datetime
    config_path_raw: str | None = None
    config_path: Path | None = None
    idle_timeout_seconds: int
    prepared_cache_root: Path
    session_root: Path
    server: ServiceServerConfigSummary
    agent: ServiceAgentConfigSummary
    script: ServiceScriptConfigSummary
    quick_path: QuickPathReadinessSummary


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
    source: Literal["script", "host"] = "script"
    level: str
    text: str


class TailLogsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: SessionStatus
    entries: list[TailLogsEntry] = Field(default_factory=list)


class PreparedConfigSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: str | None = None
    host: str
    device: str | None = None
    path: str
    jsfile: Path
    datadir: Path | None = None
    stdout: Path | None = None
    stderr: Path | None = None
    dextools_output_dir: Path | None = None
    elftools_output_dir: Path | None = None
    ssl_log_secret: Path | None = None


class PreparedSessionInspectResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prepared: bool
    signature: str | None = None
    workspace_root: Path | None = None
    config_path: Path | None = None
    bundle_path: Path | None = None
    template: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    bootstrap_kind: BootstrapKind = "none"
    bootstrap_path: Path | None = None
    bootstrap_source: str | None = None
    config: PreparedConfigSummary | None = None
    build_ready: bool = False
    last_prepare_outcome: PreparedOutcome | None = None
    last_build_error: str | None = None
    last_prepared_at: datetime | None = None
    last_used_at: datetime | None = None
    current_session_uses_artifact: bool = False
    message: str | None = None


class PreparedSessionPruneResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted_signatures: list[str] = Field(default_factory=list)
    skipped_active_signatures: list[str] = Field(default_factory=list)
    message: str | None = None
