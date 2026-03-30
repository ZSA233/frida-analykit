from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from ...config import AppConfig
from ..message import (
    RPCMsgElfSnapshotBegin,
    RPCMsgElfSnapshotChunk,
    RPCMsgElfSnapshotEnd,
    RPCMsgElfSymbolCallLog,
    RPCPayload,
    unpack_batch_payload,
)


def _safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "default"


def _render_fields(fields: dict[str, object]) -> str:
    if not fields:
        return ""
    return " ".join(f"{key}={value}" for key, value in fields.items())


@dataclass(slots=True)
class ElfSnapshotState:
    snapshot_id: str
    directory: Path
    module_name: str
    tag: str
    expected_files: tuple[str, ...]
    total_bytes: int
    received_bytes: int = 0
    received_chunks: int = 0
    written_files: set[str] = field(default_factory=set)


class ElfSnapshotHandler:
    def __init__(self, config: AppConfig, stdout: TextIO, stderr: TextIO) -> None:
        self._config = config
        self._stdout = stdout
        self._stderr = stderr
        self._states: dict[str, ElfSnapshotState] = {}

    def handle_begin(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgElfSnapshotBegin)
        directory = self._resolve_snapshot_directory(data)
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
        state = ElfSnapshotState(
            snapshot_id=data.snapshot_id,
            directory=directory,
            module_name=data.module_name,
            tag=data.tag,
            expected_files=tuple(data.expected_files),
            total_bytes=data.total_bytes,
        )
        self._states[data.snapshot_id] = state
        print(
            (
                f"[elf] begin {data.snapshot_id} -> {directory} "
                f"(module={data.module_name}, bytes={data.total_bytes})"
            ),
            file=self._stdout,
        )

    def handle_chunk(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgElfSnapshotChunk)
        state = self._require_state(data.snapshot_id)
        target = self._prepare_output_path(state.directory / Path(data.output_name).name)
        chunk = payload.data or b""
        with target.open("ab") as handle:
            handle.write(chunk)
        state.received_bytes += len(chunk)
        state.received_chunks += 1
        state.written_files.add(target.name)
        print(
            (
                f"[elf] chunk {state.snapshot_id}: {target.name} "
                f"artifact={data.artifact} chunk={data.chunk_index} size={len(chunk)}"
            ),
            file=self._stdout,
        )

    def handle_end(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgElfSnapshotEnd)
        state = self._states.pop(data.snapshot_id, None)
        if state is None:
            print(f"[elf] missing snapshot state for {data.snapshot_id}", file=self._stderr)
            return

        missing = [name for name in data.expected_files if name not in state.written_files]
        if missing or state.received_bytes != data.received_bytes or state.total_bytes != data.total_bytes:
            print(
                (
                    f"[elf] incomplete snapshot {data.snapshot_id}: "
                    f"missing={missing}, bytes={state.received_bytes}/{state.total_bytes}/{data.received_bytes}/{data.total_bytes}, "
                    f"dir={state.directory}"
                ),
                file=self._stderr,
            )
            return

        print(
            (
                f"[elf] complete {data.snapshot_id}: "
                f"files={len(state.written_files)}, chunks={state.received_chunks}, "
                f"bytes={state.received_bytes}, dir={state.directory}"
            ),
            file=self._stdout,
        )

    def handle_batch(self, payload: RPCPayload) -> None:
        for item in unpack_batch_payload(payload):
            self.handle_chunk(item)

    def _resolve_output_root(self, override: str | None = None) -> Path:
        root = Path(override).expanduser() if override else self._config.script.elftools.output_dir
        if root is None and self._config.agent.datadir is not None:
            root = self._config.agent.datadir / "elftools"
        if root is None:
            raise RuntimeError("script.elftools.output_dir or agent.datadir is required for ELF workflows")
        return root.resolve()

    def _resolve_snapshot_directory(self, data: RPCMsgElfSnapshotBegin) -> Path:
        root = self._resolve_output_root(data.output_dir)
        snapshots_root = root / "snapshots"
        if data.tag:
            return (snapshots_root / _safe_name(data.tag) / data.snapshot_id).resolve()
        return (snapshots_root / data.snapshot_id).resolve()

    @staticmethod
    def _prepare_output_path(path: Path) -> Path:
        target = path.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _require_state(self, snapshot_id: str) -> ElfSnapshotState:
        state = self._states.get(snapshot_id)
        if state is None:
            raise RuntimeError(f"elf snapshot {snapshot_id} has not been started")
        return state


class ElfSymbolLogWriter:
    def __init__(self, config: AppConfig, stdout: TextIO) -> None:
        self._config = config
        self._stdout = stdout
        self._log_handles: dict[str, TextIO] = {}

    def handle(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgElfSymbolCallLog)
        handle = self._log_file(data.tag or data.module_name)
        fields = _render_fields(data.fields)
        line = f"[elf][{data.tag}] {data.module_name}@{data.module_base}!{data.symbol}"
        if fields:
            line = f"{line} {fields}"
        print(line, file=handle)
        print(line, file=self._stdout)

    def _log_file(self, tag: str) -> TextIO:
        safe_tag = _safe_name(tag)
        if safe_tag not in self._log_handles:
            root = self._resolve_output_root()
            path = (root / "logs" / f"{safe_tag}.log").resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handles[safe_tag] = path.open("a", buffering=1, encoding="utf-8")
        return self._log_handles[safe_tag]

    def _resolve_output_root(self) -> Path:
        root = self._config.script.elftools.output_dir
        if root is None and self._config.agent.datadir is not None:
            root = self._config.agent.datadir / "elftools"
        if root is None:
            raise RuntimeError("script.elftools.output_dir or agent.datadir is required for ELF logs")
        return root.resolve()


class ElfHandler:
    def __init__(self, config: AppConfig, stdout: TextIO, stderr: TextIO) -> None:
        self.snapshot = ElfSnapshotHandler(config, stdout, stderr)
        self.symbol_log = ElfSymbolLogWriter(config, stdout)

    def handle_snapshot_begin(self, payload: RPCPayload) -> None:
        self.snapshot.handle_begin(payload)

    def handle_snapshot_chunk(self, payload: RPCPayload) -> None:
        self.snapshot.handle_chunk(payload)

    def handle_snapshot_end(self, payload: RPCPayload) -> None:
        self.snapshot.handle_end(payload)

    def handle_snapshot_batch(self, payload: RPCPayload) -> None:
        self.snapshot.handle_batch(payload)

    def handle_symbol_log(self, payload: RPCPayload) -> None:
        self.symbol_log.handle(payload)
