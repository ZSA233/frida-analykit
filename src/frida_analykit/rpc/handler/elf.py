from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TextIO

from ...config import AppConfig
from .output_paths import (
    OutputLeaf,
    resolve_configured_output_root,
    resolve_output_leaf,
    reset_output_leaf,
)
from ..message import (
    RPCMsgElfModuleDumpBegin,
    RPCMsgElfModuleDumpChunk,
    RPCMsgElfModuleDumpEnd,
    RPCMsgElfSymbolCallLog,
    RPCPayload,
    unpack_batch_payload,
)

def _render_fields(fields: dict[str, object]) -> str:
    if not fields:
        return ""
    return " ".join(f"{key}={value}" for key, value in fields.items())


@dataclass(slots=True)
class ElfModuleDumpState:
    dump_id: str
    directory: Path
    module_name: str
    tag: str
    effective_tag: str
    requested_output_dir: str | None
    requested_relative_dump_dir: str
    configured_output_root: str
    actual_relative_dir: str
    expected_files: tuple[str, ...]
    total_bytes: int
    received_bytes: int = 0
    received_chunks: int = 0
    written_files: set[str] = field(default_factory=set)


class ElfModuleDumpHandler:
    def __init__(
        self,
        config: AppConfig,
        *,
        emit_info: Callable[[str], None],
        emit_error: Callable[[str], None],
    ) -> None:
        self._config = config
        self._emit_info = emit_info
        self._emit_error = emit_error
        self._states: dict[str, ElfModuleDumpState] = {}

    def handle_begin(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgElfModuleDumpBegin)
        try:
            output_leaf = self._resolve_output_leaf(data)
        except ValueError as exc:
            self._emit_error(f"[elf] reject dump {data.dump_id}: {exc}")
            raise
        reset_output_leaf(
            output_leaf,
            cleanup_patterns=tuple(Path(name).name for name in data.expected_files),
        )
        state = ElfModuleDumpState(
            dump_id=data.dump_id,
            directory=output_leaf.directory,
            module_name=data.module_name,
            tag=data.tag,
            effective_tag=output_leaf.effective_tag,
            requested_output_dir=data.output_dir,
            requested_relative_dump_dir=data.relative_dump_dir,
            configured_output_root=str(output_leaf.root),
            actual_relative_dir=output_leaf.relative_dir,
            expected_files=tuple(data.expected_files),
            total_bytes=data.total_bytes,
        )
        self._states[data.dump_id] = state
        self._emit_info(
            f"[elf] begin {data.dump_id} -> {output_leaf.directory} "
            f"(module={data.module_name}, bytes={data.total_bytes})"
        )

    def handle_chunk(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgElfModuleDumpChunk)
        state = self._require_state(data.dump_id)
        target = self._prepare_output_path(state.directory / Path(data.output_name).name)
        chunk = payload.data or b""
        with target.open("ab") as handle:
            handle.write(chunk)
        state.received_bytes += len(chunk)
        state.received_chunks += 1
        state.written_files.add(target.name)
        self._emit_info(
            f"[elf] chunk {state.dump_id}: {target.name} "
            f"artifact={data.artifact} chunk={data.chunk_index} size={len(chunk)}"
        )

    def handle_end(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgElfModuleDumpEnd)
        state = self._states.pop(data.dump_id, None)
        if state is None:
            self._emit_error(f"[elf] missing dump state for {data.dump_id}")
            return

        missing = [name for name in data.expected_files if name not in state.written_files]
        if missing or state.received_bytes != data.received_bytes or state.total_bytes != data.total_bytes:
            self._emit_error(
                f"[elf] incomplete dump {data.dump_id}: "
                f"missing={missing}, bytes={state.received_bytes}/{state.total_bytes}/{data.received_bytes}/{data.total_bytes}, "
                f"dir={state.directory}"
            )
            return
        if "manifest.json" in state.written_files:
            try:
                self._augment_manifest(state)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                self._emit_error(f"[elf] invalid manifest {data.dump_id}: {exc}")
                return

        self._emit_info(
            f"[elf] complete {data.dump_id}: "
            f"files={len(state.written_files)}, chunks={state.received_chunks}, "
            f"bytes={state.received_bytes}, dir={state.directory}"
        )

    def handle_batch(self, payload: RPCPayload) -> None:
        for item in unpack_batch_payload(payload):
            self.handle_chunk(item)

    def _resolve_output_root(self) -> Path:
        return resolve_configured_output_root(
            configured_root=self._config.script.elftools.output_dir,
            agent_datadir=self._config.agent.datadir,
            fallback_child="elftools",
            missing_message="script.elftools.output_dir or agent.datadir is required for ELF workflows",
        )

    def _resolve_output_leaf(self, data: RPCMsgElfModuleDumpBegin) -> OutputLeaf:
        root = self._resolve_output_root()
        return resolve_output_leaf(root, data.tag)

    @staticmethod
    def _augment_manifest(state: ElfModuleDumpState) -> None:
        manifest_path = state.directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest.json must contain a JSON object")
        manifest.update(
            {
                "tag": state.tag,
                "effective_tag": state.effective_tag,
                "requested_output_dir": state.requested_output_dir,
                "requested_relative_dump_dir": state.requested_relative_dump_dir,
                "configured_output_root": state.configured_output_root,
                "actual_relative_dir": state.actual_relative_dir,
            }
        )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _prepare_output_path(path: Path) -> Path:
        target = path.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _require_state(self, dump_id: str) -> ElfModuleDumpState:
        state = self._states.get(dump_id)
        if state is None:
            raise RuntimeError(f"elf dump {dump_id} has not been started")
        return state


class ElfSymbolLogWriter:
    def __init__(self, config: AppConfig, emit_info: Callable[[str], None]) -> None:
        self._config = config
        self._emit_info = emit_info
        self._log_handles: dict[str, tuple[TextIO, Path]] = {}

    def handle(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgElfSymbolCallLog)
        handle = self._log_file(data.tag or data.module_name)
        fields = _render_fields(data.fields)
        line = f"[elf][{data.tag}] {data.module_name}@{data.module_base}!{data.symbol}"
        if fields:
            line = f"{line} {fields}"
        print(line, file=handle)
        self._emit_info(line)

    def _log_file(self, tag: str) -> TextIO:
        output_leaf = resolve_output_leaf(self._resolve_output_root(), tag)
        handle_key = output_leaf.relative_dir or "__root__"
        path = (output_leaf.directory / "symbols.log").resolve()
        cached = self._log_handles.get(handle_key)
        if cached is not None:
            handle, cached_path = cached
            if cached_path.exists():
                return handle
            handle.close()
            self._log_handles.pop(handle_key, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", buffering=1, encoding="utf-8")
        self._log_handles[handle_key] = (handle, path)
        return handle

    def _resolve_output_root(self) -> Path:
        return resolve_configured_output_root(
            configured_root=self._config.script.elftools.output_dir,
            agent_datadir=self._config.agent.datadir,
            fallback_child="elftools",
            missing_message="script.elftools.output_dir or agent.datadir is required for ELF logs",
        )


class ElfHandler:
    def __init__(
        self,
        config: AppConfig,
        *,
        emit_info: Callable[[str], None],
        emit_error: Callable[[str], None],
    ) -> None:
        self.dump = ElfModuleDumpHandler(config, emit_info=emit_info, emit_error=emit_error)
        self.symbol_log = ElfSymbolLogWriter(config, emit_info=emit_info)

    def handle_dump_begin(self, payload: RPCPayload) -> None:
        self.dump.handle_begin(payload)

    def handle_dump_chunk(self, payload: RPCPayload) -> None:
        self.dump.handle_chunk(payload)

    def handle_dump_end(self, payload: RPCPayload) -> None:
        self.dump.handle_end(payload)

    def handle_dump_batch(self, payload: RPCPayload) -> None:
        self.dump.handle_batch(payload)

    def handle_symbol_log(self, payload: RPCPayload) -> None:
        self.symbol_log.handle(payload)
