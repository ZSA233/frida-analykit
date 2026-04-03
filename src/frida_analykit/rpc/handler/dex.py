from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ...config import AppConfig
from ..message import (
    RPCMsgDexDumpBegin,
    RPCMsgDexDumpEnd,
    RPCMsgDumpDexFile,
    RPCPayload,
    unpack_batch_payload,
)


@dataclass(slots=True)
class DexDumpTransferState:
    transfer_id: str
    directory: Path
    expected_count: int
    total_bytes: int
    tag: str
    manifest: list[dict[str, object]] = field(default_factory=list)
    received_count: int = 0
    received_bytes: int = 0
    mismatched_files: list[str] = field(default_factory=list)


class DexDumpHandler:
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
        self._states: dict[str, DexDumpTransferState] = {}

    def handle_begin(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgDexDumpBegin)
        directory = self._resolve_directory(data)
        self._cleanup_previous_outputs(directory)
        state = DexDumpTransferState(
            transfer_id=data.transfer_id,
            directory=directory,
            expected_count=data.expected_count,
            total_bytes=data.total_bytes,
            tag=data.tag,
        )
        self._states[data.transfer_id] = state
        self._emit_info(
            f"[dex] begin {data.transfer_id} -> {directory} "
            f"(expected={data.expected_count}, bytes={data.total_bytes}, max_batch={data.max_batch_bytes})"
        )

    def handle_file(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgDumpDexFile)
        state = self._require_state(data.transfer_id)
        output_name = Path(data.info.output_name).name
        filepath = self._prepare_output_path(state.directory / output_name)
        payload_bytes = payload.data or b""
        payload_size = len(payload_bytes)
        with open(filepath, "wb") as handle:
            handle.write(payload_bytes)
        state.received_count += 1
        state.received_bytes += payload_size
        if payload_size != data.info.size:
            state.mismatched_files.append(output_name)
            self._emit_error(
                f"[dex] size mismatch {state.transfer_id}: {output_name} "
                f"payload={payload_size}, declared={data.info.size}"
            )
        state.manifest.append({**data.info.model_dump(mode="json"), "output_name": output_name})
        self._write_manifest(state)
        self._emit_info(
            f"[dex] file {state.transfer_id}: {output_name} "
            f"size={payload_size} declared={data.info.size} "
            f"name={data.info.name} loader={data.info.loader_class}"
        )

    def handle_end(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgDexDumpEnd)
        state = self._states.pop(data.transfer_id, None)
        if state is None:
            self._emit_error(f"[dex] missing transfer state for {data.transfer_id}")
            return

        self._write_manifest(state)
        is_complete = (
            state.expected_count == data.expected_count
            and state.received_count == data.received_count == state.expected_count
            and state.received_bytes == state.total_bytes == data.total_bytes
            and not state.mismatched_files
        )
        if not is_complete:
            self._emit_error(
                f"[dex] incomplete transfer {data.transfer_id}: "
                f"expected={state.expected_count}/{data.expected_count}, "
                f"sender={data.received_count}, received={state.received_count}, "
                f"bytes={state.received_bytes}/{state.total_bytes}/{data.total_bytes}, "
                f"mismatched={state.mismatched_files}"
            )
            return
        self._emit_info(
            f"[dex] complete {data.transfer_id}: "
            f"files={state.received_count}, bytes={state.received_bytes}, dir={state.directory}"
        )

    def handle_batch(self, payload: RPCPayload) -> None:
        for item in unpack_batch_payload(payload):
            self.handle_file(item)

    def _resolve_directory(self, data: RPCMsgDexDumpBegin) -> Path:
        base_dir = self._config.script.dextools.output_dir
        if data.dump_dir:
            base_dir = Path(data.dump_dir).expanduser()
        elif base_dir is None and self._config.agent.datadir is not None:
            base_dir = self._config.agent.datadir / "dextools"
        if base_dir is None:
            raise RuntimeError("script.dextools.output_dir or agent.datadir is required for dex dumping")
        target = base_dir
        if data.tag:
            target = target / Path(data.tag).name
        target.mkdir(parents=True, exist_ok=True)
        return target.resolve()

    @staticmethod
    def _cleanup_previous_outputs(directory: Path) -> None:
        for pattern in ("classes*.dex", "classes*.dex.json", "classes.json", "*_classes.json"):
            for path in directory.glob(pattern):
                if path.is_file():
                    path.unlink()

    @staticmethod
    def _write_manifest(state: DexDumpTransferState) -> None:
        manifest_path = state.directory / "classes.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(state.manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _prepare_output_path(path: Path) -> Path:
        target = path.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _require_state(self, transfer_id: str) -> DexDumpTransferState:
        state = self._states.get(transfer_id)
        if state is None:
            raise RuntimeError(f"dex transfer {transfer_id} has not been started")
        return state
