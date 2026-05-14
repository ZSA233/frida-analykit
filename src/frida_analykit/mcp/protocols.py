from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

from ..config import AppConfig
from ..session import SessionWrapper
from .history import SessionHistoryRecord
from .prepared.models import PreparedArtifactManifest, PreparedSessionOpenRequest, PreparedWorkspaceBuildResult


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
