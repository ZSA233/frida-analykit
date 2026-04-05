from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ...config import AppConfig
from .output_paths import (
    OutputLeaf,
    resolve_configured_output_root,
    resolve_output_leaf,
    reset_output_leaf,
)
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
    effective_tag: str
    requested_dump_dir: str | None
    configured_output_root: str
    actual_relative_dir: str
    max_batch_bytes: int
    created_at_ms: int
    files: list[dict[str, object]] = field(default_factory=list)
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
        try:
            output_leaf = self._resolve_output_leaf(data)
        except ValueError as exc:
            self._emit_error(f"[dex] reject transfer {data.transfer_id}: {exc}")
            raise
        reset_output_leaf(
            output_leaf,
            cleanup_patterns=("classes*.dex", "classes*.dex.json", "classes.json", "*_classes.json", "manifest.json"),
        )
        state = DexDumpTransferState(
            transfer_id=data.transfer_id,
            directory=output_leaf.directory,
            expected_count=data.expected_count,
            total_bytes=data.total_bytes,
            tag=data.tag,
            effective_tag=output_leaf.effective_tag,
            requested_dump_dir=data.dump_dir,
            configured_output_root=str(output_leaf.root),
            actual_relative_dir=output_leaf.relative_dir,
            max_batch_bytes=data.max_batch_bytes,
            created_at_ms=int(time.time() * 1000),
        )
        self._states[data.transfer_id] = state
        self._write_manifest(state)
        self._emit_info(
            f"[dex] begin {data.transfer_id} -> {output_leaf.directory} "
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
        state.files.append({**data.info.model_dump(mode="json"), "output_name": output_name})
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

    def _resolve_output_leaf(self, data: RPCMsgDexDumpBegin) -> OutputLeaf:
        root = resolve_configured_output_root(
            configured_root=self._config.script.dextools.output_dir,
            agent_datadir=self._config.agent.datadir,
            fallback_child="dextools",
            missing_message="script.dextools.output_dir or agent.datadir is required for dex dumping",
        )
        return resolve_output_leaf(root, data.tag)

    @staticmethod
    def _write_manifest(state: DexDumpTransferState) -> None:
        manifest_path = state.directory / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "transfer_id": state.transfer_id,
                    "created_at_ms": state.created_at_ms,
                    "mode": "rpc",
                    "tag": state.tag,
                    "effective_tag": state.effective_tag,
                    "requested_dump_dir": state.requested_dump_dir,
                    "configured_output_root": state.configured_output_root,
                    "actual_relative_dir": state.actual_relative_dir,
                    "expected_count": state.expected_count,
                    "received_count": state.received_count,
                    "total_bytes": state.total_bytes,
                    "received_bytes": state.received_bytes,
                    "max_batch_bytes": state.max_batch_bytes,
                    "mismatched_files": list(state.mismatched_files),
                    "files": state.files,
                },
                ensure_ascii=False,
                indent=2,
            ),
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
