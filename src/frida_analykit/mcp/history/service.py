from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ...config import AppConfig
from ..prepared import PreparedArtifactManifest
from .models import (
    HistoryEventType,
    HistoryOpenKind,
    SessionHistoryEvent,
    SessionHistoryManifest,
    SessionHistoryRecord,
    SessionHistorySnippetManifest,
    SessionHistorySnippetVersion,
)

_MANIFEST_FILENAME = "session.json"
_EVENTS_FILENAME = "events.jsonl"
_WORKSPACE_DIRNAME = "workspace"
_SNIPPETS_DIRNAME = "snippets"
_SAFE_SNIPPET_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_PREPARED_MANIFEST_FILENAME = "prepared.json"
_WORKSPACE_OPTIONAL_FILENAMES = (
    "index.ts",
    "package.json",
    "tsconfig.json",
    "bootstrap.user.ts",
    "bootstrap.user.js",
)


class SessionHistoryError(RuntimeError):
    pass


class SessionHistoryManager:
    def __init__(
        self,
        root: str | Path,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = Path(root).expanduser().resolve()
        self._now_fn = now_fn or datetime.now

    @property
    def root(self) -> Path:
        return self._root

    def begin_session(
        self,
        *,
        open_kind: HistoryOpenKind,
        requested_mode: str,
        requested_pid: int | None,
        app: str | None,
        config_path: Path | None,
        prepared_artifact: PreparedArtifactManifest | None,
    ) -> SessionHistoryRecord:
        now = self._now_fn()
        record = self._allocate_record(now)
        manifest = SessionHistoryManifest(
            session_id=record.session_id,
            session_label=record.session_label,
            session_root=record.root,
            workspace_root=record.workspace_root,
            created_at=now,
            updated_at=now,
            state="opening",
            open_kind=open_kind,
            requested_mode=requested_mode,
            requested_pid=requested_pid,
            app=app,
            config_path=config_path,
            prepared_signature=prepared_artifact.signature if prepared_artifact is not None else None,
            prepared_workspace=prepared_artifact.workspace_root if prepared_artifact is not None else None,
        )
        self._write_manifest(record.manifest_path, manifest)
        self._append_event(
            record,
            event="open_started",
            timestamp=now,
            detail={
                "open_kind": open_kind,
                "requested_mode": requested_mode,
                "requested_pid": requested_pid,
                "app": app,
                "config_path": str(config_path) if config_path is not None else None,
                "prepared_signature": prepared_artifact.signature if prepared_artifact is not None else None,
            },
        )
        return record

    def record_open_success(
        self,
        record: SessionHistoryRecord,
        *,
        config: AppConfig,
        attached_pid: int,
        prepared_artifact: PreparedArtifactManifest | None,
    ) -> None:
        now = self._now_fn()
        manifest = self._load_manifest(record.manifest_path)
        self._snapshot_workspace(record, config=config, prepared_artifact=prepared_artifact)
        updated = manifest.model_copy(
            update={
                "updated_at": now,
                "state": "live",
                "app": config.app,
                "config_path": config.source_path,
                "prepared_signature": prepared_artifact.signature if prepared_artifact is not None else None,
                "prepared_workspace": prepared_artifact.workspace_root if prepared_artifact is not None else None,
                "attached_pid": attached_pid,
                "broken_reason": None,
                "last_error": None,
                "closed_reason": None,
            }
        )
        self._write_manifest(record.manifest_path, updated)
        self._append_event(
            record,
            event="open_succeeded",
            timestamp=now,
            detail={
                "attached_pid": attached_pid,
                "config_path": str(config.source_path) if config.source_path is not None else None,
                "prepared_signature": prepared_artifact.signature if prepared_artifact is not None else None,
            },
        )

    def record_open_failure(
        self,
        record: SessionHistoryRecord,
        *,
        message: str,
        config: AppConfig | None = None,
        prepared_artifact: PreparedArtifactManifest | None = None,
        attached_pid: int | None = None,
    ) -> None:
        now = self._now_fn()
        manifest = self._load_manifest(record.manifest_path)
        if manifest.state == "failed" and manifest.last_error == message:
            return
        if config is not None:
            self._snapshot_workspace(record, config=config, prepared_artifact=prepared_artifact)
        updated = manifest.model_copy(
            update={
                "updated_at": now,
                "state": "failed",
                "app": config.app if config is not None else manifest.app,
                "config_path": config.source_path if config is not None else manifest.config_path,
                "prepared_signature": prepared_artifact.signature if prepared_artifact is not None else manifest.prepared_signature,
                "prepared_workspace": (
                    prepared_artifact.workspace_root if prepared_artifact is not None else manifest.prepared_workspace
                ),
                "attached_pid": attached_pid if attached_pid is not None else manifest.attached_pid,
                "last_error": message,
            }
        )
        self._write_manifest(record.manifest_path, updated)
        self._append_event(
            record,
            event="open_failed",
            timestamp=now,
            detail={"message": message},
        )

    def record_broken(
        self,
        record: SessionHistoryRecord,
        *,
        reason: str,
        snippet_names: list[str],
        crash_report: str | None,
    ) -> None:
        now = self._now_fn()
        manifest = self._load_manifest(record.manifest_path)
        snippets = dict(manifest.snippets)
        for name in snippet_names:
            existing = snippets.get(name)
            if existing is None:
                continue
            snippets[name] = existing.model_copy(update={"state": "inactive", "updated_at": now})
            self._append_event(
                record,
                event="snippet_inactive",
                timestamp=now,
                detail={"name": name, "reason": "session_broken"},
            )
        updated = manifest.model_copy(
            update={
                "updated_at": now,
                "state": "broken",
                "broken_reason": reason,
                "snippets": snippets,
            }
        )
        self._write_manifest(record.manifest_path, updated)
        self._append_event(
            record,
            event="session_broken",
            timestamp=now,
            detail={"reason": reason, "crash_report": crash_report},
        )

    def record_recovered(self, record: SessionHistoryRecord, *, attached_pid: int) -> None:
        now = self._now_fn()
        manifest = self._load_manifest(record.manifest_path)
        updated = manifest.model_copy(
            update={
                "updated_at": now,
                "state": "live",
                "attached_pid": attached_pid,
                "broken_reason": None,
                "closed_reason": None,
                "last_error": None,
            }
        )
        self._write_manifest(record.manifest_path, updated)
        self._append_event(
            record,
            event="session_recovered",
            timestamp=now,
            detail={"attached_pid": attached_pid},
        )

    def record_closed(self, record: SessionHistoryRecord, *, reason: str) -> None:
        now = self._now_fn()
        manifest = self._load_manifest(record.manifest_path)
        updated = manifest.model_copy(
            update={
                "updated_at": now,
                "state": "closed",
                "closed_reason": reason,
            }
        )
        self._write_manifest(record.manifest_path, updated)
        event: HistoryEventType = "session_idle_timeout_closed" if reason == "idle timeout" else "session_closed"
        self._append_event(record, event=event, timestamp=now, detail={"reason": reason})

    def persist_snippet(
        self,
        record: SessionHistoryRecord,
        *,
        name: str,
        source: str,
        replaced: bool,
    ) -> Path:
        now = self._now_fn()
        manifest = self._load_manifest(record.manifest_path)
        existing = manifest.snippets.get(name)
        safe_name = self._select_snippet_safe_name(manifest, name=name)
        snippet_root = record.snippets_root / safe_name
        try:
            snippet_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SessionHistoryError(f"failed to prepare snippet history directory `{snippet_root}`: {exc}") from exc
        version = 1 if existing is None else len(existing.versions) + 1
        filename = f"{_label_timestamp(now)}-v{version:04d}.js"
        snippet_path = snippet_root / filename
        self._write_text(snippet_path, source)
        version_record = SessionHistorySnippetVersion(version=version, stored_at=now, file_path=snippet_path)
        snippet_entry = SessionHistorySnippetManifest(
            name=name,
            safe_name=safe_name,
            state="active",
            updated_at=now,
            versions=[*existing.versions, version_record] if existing is not None else [version_record],
        )
        updated_snippets = dict(manifest.snippets)
        updated_snippets[name] = snippet_entry
        updated = manifest.model_copy(update={"updated_at": now, "snippets": updated_snippets})
        self._write_manifest(record.manifest_path, updated)
        self._append_event(
            record,
            event="snippet_replaced" if replaced else "snippet_installed",
            timestamp=now,
            detail={
                "name": name,
                "file_path": str(snippet_path),
                "version": version,
            },
        )
        return snippet_path

    @classmethod
    def _select_snippet_safe_name(cls, manifest: SessionHistoryManifest, *, name: str) -> str:
        existing = manifest.snippets.get(name)
        if existing is not None:
            return existing.safe_name
        base = _safe_snippet_name(name)
        if not cls._snippet_safe_name_in_use(manifest, name=name, safe_name=base):
            return base
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        for length in range(8, len(digest) + 1):
            candidate = f"{base}--{digest[:length]}"
            if not cls._snippet_safe_name_in_use(manifest, name=name, safe_name=candidate):
                return candidate
        raise SessionHistoryError(f"failed to allocate snippet archive directory for `{name}`")

    @staticmethod
    def _snippet_safe_name_in_use(
        manifest: SessionHistoryManifest,
        *,
        name: str,
        safe_name: str,
    ) -> bool:
        return any(
            other_name != name and snippet.safe_name == safe_name
            for other_name, snippet in manifest.snippets.items()
        )

    def record_snippet_removed(self, record: SessionHistoryRecord, *, name: str) -> None:
        now = self._now_fn()
        manifest = self._load_manifest(record.manifest_path)
        existing = manifest.snippets.get(name)
        if existing is None:
            return
        updated_snippets = dict(manifest.snippets)
        updated_snippets[name] = existing.model_copy(update={"state": "removed", "updated_at": now})
        updated = manifest.model_copy(update={"updated_at": now, "snippets": updated_snippets})
        self._write_manifest(record.manifest_path, updated)
        self._append_event(record, event="snippet_removed", timestamp=now, detail={"name": name})

    def inspect(self, session_label: str) -> SessionHistoryManifest | None:
        manifest_path = self._root / session_label / _MANIFEST_FILENAME
        if not manifest_path.is_file():
            return None
        try:
            return SessionHistoryManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _allocate_record(self, now: datetime) -> SessionHistoryRecord:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SessionHistoryError(f"failed to prepare session history root `{self._root}`: {exc}") from exc
        while True:
            session_id = uuid4().hex[:8]
            label = f"{_label_timestamp(now)}-{session_id}"
            root = self._root / label
            try:
                root.mkdir(parents=False, exist_ok=False)
                break
            except FileExistsError:
                continue
            except OSError as exc:
                raise SessionHistoryError(f"failed to create session history directory `{root}`: {exc}") from exc
        workspace_root = root / _WORKSPACE_DIRNAME
        snippets_root = root / _SNIPPETS_DIRNAME
        try:
            workspace_root.mkdir(parents=True, exist_ok=True)
            snippets_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SessionHistoryError(f"failed to prepare session history layout under `{root}`: {exc}") from exc
        return SessionHistoryRecord(
            session_id=session_id,
            session_label=label,
            root=root,
            workspace_root=workspace_root,
            snippets_root=snippets_root,
            manifest_path=root / _MANIFEST_FILENAME,
            events_path=root / _EVENTS_FILENAME,
        )

    def _snapshot_workspace(
        self,
        record: SessionHistoryRecord,
        *,
        config: AppConfig,
        prepared_artifact: PreparedArtifactManifest | None,
    ) -> None:
        self._reset_directory(record.workspace_root)
        if prepared_artifact is not None:
            source_root = prepared_artifact.workspace_root
            filenames = {
                prepared_artifact.config_path.name,
                prepared_artifact.bundle_path.name,
                *_WORKSPACE_OPTIONAL_FILENAMES,
                _PREPARED_MANIFEST_FILENAME,
            }
            for filename in sorted(filenames):
                self._copy_if_exists(source_root / filename, record.workspace_root / filename)
            return

        if config.source_path is not None:
            self._copy_if_exists(config.source_path, record.workspace_root / config.source_path.name)
            source_root = config.source_path.parent
        else:
            source_root = config.jsfile.parent
        self._copy_if_exists(config.jsfile, record.workspace_root / config.jsfile.name)
        for filename in _WORKSPACE_OPTIONAL_FILENAMES[:3]:
            self._copy_if_exists(source_root / filename, record.workspace_root / filename)

    @staticmethod
    def _reset_directory(path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            for child in path.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
        except OSError as exc:
            raise SessionHistoryError(f"failed to reset session workspace snapshot directory `{path}`: {exc}") from exc

    @staticmethod
    def _copy_if_exists(source: Path, destination: Path) -> None:
        if not source.is_file():
            return
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as exc:
            raise SessionHistoryError(f"failed to copy `{source}` to `{destination}`: {exc}") from exc

    @staticmethod
    def _write_manifest(path: Path, manifest: SessionHistoryManifest) -> None:
        try:
            path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        except OSError as exc:
            raise SessionHistoryError(f"failed to write session history manifest `{path}`: {exc}") from exc

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise SessionHistoryError(f"failed to write session history file `{path}`: {exc}") from exc

    @staticmethod
    def _load_manifest(path: Path) -> SessionHistoryManifest:
        try:
            return SessionHistoryManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SessionHistoryError(f"failed to read session history manifest `{path}`: {exc}") from exc
        except Exception as exc:
            raise SessionHistoryError(f"failed to parse session history manifest `{path}`: {exc}") from exc

    def _append_event(
        self,
        record: SessionHistoryRecord,
        *,
        event: HistoryEventType,
        timestamp: datetime,
        detail: dict[str, object | None],
    ) -> None:
        payload = SessionHistoryEvent(timestamp=timestamp, event=event, detail=detail)
        try:
            with record.events_path.open("a", encoding="utf-8") as handle:
                handle.write(payload.model_dump_json())
                handle.write("\n")
        except OSError as exc:
            raise SessionHistoryError(f"failed to append session history event `{record.events_path}`: {exc}") from exc


def _label_timestamp(value: datetime) -> str:
    return value.astimezone().strftime("%Y%m%d-%H%M%S")


def _safe_snippet_name(name: str) -> str:
    cleaned = _SAFE_SNIPPET_CHARS.sub("_", name)
    if cleaned:
        return cleaned
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"snippet-{digest}"
