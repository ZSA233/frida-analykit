import io
from pathlib import Path

from frida_analykit.config import AppConfig
from frida_analykit.rpc.message import (
    RPCBatchSource,
    RPCMessage,
    RPCMsgBatch,
    RPCMsgElfSnapshotBegin,
    RPCMsgElfSnapshotChunk,
    RPCMsgElfSnapshotEnd,
    RPCMsgElfSymbolCallLog,
    RPCMsgType,
    RPCPayload,
)
from frida_analykit.rpc.registry import HandlerRegistry


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": str(tmp_path / "_agent.js"),
            "server": {"host": "local"},
            "agent": {"datadir": str(tmp_path / "data")},
            "script": {
                "elftools": {"output_dir": str(tmp_path / "elf")},
                "nettools": {"ssl_log_secret": str(tmp_path / "ssl")},
            },
        }
    ).resolve_paths(tmp_path)


def _chunk_payload(snapshot_id: str, artifact: str, output_name: str, data: bytes, *, chunk_index: int = 0) -> RPCPayload:
    return RPCPayload(
        message=RPCMessage(
            type=RPCMsgType.ELF_SNAPSHOT_CHUNK,
            data=RPCMsgElfSnapshotChunk(
                snapshot_id=snapshot_id,
                tag="demo",
                artifact=artifact,
                output_name=output_name,
                chunk_index=chunk_index,
                total_size=len(data),
            ),
        ),
        data=data,
    )


def test_registry_handles_streaming_elf_snapshot_and_symbol_logs(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)
    snapshot_id = "elf-1"
    snapshot_root = tmp_path / "elf" / "snapshots" / "demo" / snapshot_id
    snapshot_root.mkdir(parents=True, exist_ok=True)
    (snapshot_root / "stale.bin").write_bytes(b"stale")

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.ELF_SNAPSHOT_BEGIN,
                data=RPCMsgElfSnapshotBegin(
                    snapshot_id=snapshot_id,
                    tag="demo",
                    module_name="libc.so",
                    module_path="/apex/libc.so",
                    module_base="0x1000",
                    module_size=5,
                    expected_files=["libc.so", "symbols.json", "proc_maps.txt", "info.json"],
                    total_bytes=13,
                ),
            )
        )
    )

    payloads = [
        _chunk_payload(snapshot_id, "module", "libc.so", b"abc", chunk_index=0),
        _chunk_payload(snapshot_id, "module", "libc.so", b"de", chunk_index=1),
        _chunk_payload(snapshot_id, "symbols", "symbols.json", b"[]"),
        _chunk_payload(snapshot_id, "proc_maps", "proc_maps.txt", b"maps"),
        _chunk_payload(snapshot_id, "info", "info.json", b"{}"),
    ]
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.BATCH,
                source=RPCBatchSource.ELF_SNAPSHOT_CHUNKS.value,
                data=RPCMsgBatch(
                    message_list=[item.message for item in payloads],
                    data_sizes=[3, 2, 2, 4, 2],
                ),
            ),
            data=b"abcde[]maps{}",
        )
    )
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.ELF_SNAPSHOT_END,
                data=RPCMsgElfSnapshotEnd(
                    snapshot_id=snapshot_id,
                    tag="demo",
                    module_name="libc.so",
                    expected_files=["libc.so", "symbols.json", "proc_maps.txt", "info.json"],
                    total_bytes=13,
                    received_bytes=13,
                ),
            )
        )
    )
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.ELF_SYMBOL_CALL_LOG,
                data=RPCMsgElfSymbolCallLog(
                    tag="demo",
                    module_name="libc.so",
                    module_base="0x1000",
                    symbol="getpid",
                    fields={"pid": 1234},
                ),
            )
        )
    )

    assert not (snapshot_root / "stale.bin").exists()
    assert (snapshot_root / "libc.so").read_bytes() == b"abcde"
    assert (snapshot_root / "symbols.json").read_bytes() == b"[]"
    assert (snapshot_root / "proc_maps.txt").read_bytes() == b"maps"
    assert (snapshot_root / "info.json").read_bytes() == b"{}"
    log_path = tmp_path / "elf" / "logs" / "demo.log"
    assert "getpid" in log_path.read_text(encoding="utf-8")
    assert "[elf] begin elf-1" in stdout.getvalue()
    assert "[elf] complete elf-1" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_registry_preserves_multiple_snapshots_for_same_tag(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)

    for snapshot_id, payload_bytes in (("elf-keep-1", b"one"), ("elf-keep-2", b"two")):
        registry.handle(
            RPCPayload(
                message=RPCMessage(
                    type=RPCMsgType.ELF_SNAPSHOT_BEGIN,
                    data=RPCMsgElfSnapshotBegin(
                        snapshot_id=snapshot_id,
                        tag="same-tag",
                        module_name="libc.so",
                        module_path="/apex/libc.so",
                        module_base="0x1000",
                        module_size=len(payload_bytes),
                        expected_files=["libc.so"],
                        total_bytes=len(payload_bytes),
                    ),
                )
            )
        )
        registry.handle(_chunk_payload(snapshot_id, "module", "libc.so", payload_bytes))
        registry.handle(
            RPCPayload(
                message=RPCMessage(
                    type=RPCMsgType.ELF_SNAPSHOT_END,
                    data=RPCMsgElfSnapshotEnd(
                        snapshot_id=snapshot_id,
                        tag="same-tag",
                        module_name="libc.so",
                        expected_files=["libc.so"],
                        total_bytes=len(payload_bytes),
                        received_bytes=len(payload_bytes),
                    ),
                )
            )
        )

    first_dir = tmp_path / "elf" / "snapshots" / "same-tag" / "elf-keep-1"
    second_dir = tmp_path / "elf" / "snapshots" / "same-tag" / "elf-keep-2"

    assert (first_dir / "libc.so").read_bytes() == b"one"
    assert (second_dir / "libc.so").read_bytes() == b"two"
    assert "[elf] complete elf-keep-1" in stdout.getvalue()
    assert "[elf] complete elf-keep-2" in stdout.getvalue()
    assert stderr.getvalue() == ""
