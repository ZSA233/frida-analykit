import io
import json
from pathlib import Path

from frida_analykit.config import AppConfig
from frida_analykit.rpc.message import (
    RPCBatchSource,
    RPCMessage,
    RPCMsgBatch,
    RPCMsgDexDumpBegin,
    RPCMsgDexDumpEnd,
    RPCMsgDumpDexFile,
    RPCMsgDexDumpFileInfo,
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
            "script": {"nettools": {"ssl_log_secret": str(tmp_path / "ssl")}},
        }
    ).resolve_paths(tmp_path)


def _dex_file_payload(transfer_id: str, output_name: str, data: bytes) -> RPCPayload:
    return RPCPayload(
        message=RPCMessage(
            type=RPCMsgType.DUMP_DEX_FILE,
            data=RPCMsgDumpDexFile(
                transfer_id=transfer_id,
                tag="demo",
                info=RPCMsgDexDumpFileInfo(
                    name=output_name,
                    base="0x1000",
                    size=len(data),
                    loader="0x1",
                    loader_class="dalvik.system.PathClassLoader",
                    output_name=output_name,
                ),
            ),
        ),
        data=data,
    )


def test_registry_handles_streaming_dex_dump_batches(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)
    transfer_id = "dex-1"
    dex_dir = tmp_path / "custom-dex"
    target_dir = dex_dir / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "classes00.dex").write_bytes(b"old")
    (target_dir / "classes.json").write_text("[]", encoding="utf-8")
    (target_dir / "20260330015015656963_classes.json").write_text("old", encoding="utf-8")

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_BEGIN,
                data=RPCMsgDexDumpBegin(
                    transfer_id=transfer_id,
                    tag="demo",
                    dump_dir=str(dex_dir),
                    expected_count=2,
                    total_bytes=5,
                    max_batch_bytes=1024,
                ),
            )
        )
    )

    payload1 = _dex_file_payload(transfer_id, "classes00.dex", b"abc")
    payload2 = _dex_file_payload(transfer_id, "classes01.dex", b"de")
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.BATCH,
                source=RPCBatchSource.DEX_DUMP_FILES.value,
                data=RPCMsgBatch(
                    message_list=[payload1.message, payload2.message],
                    data_sizes=[3, 2],
                ),
            ),
            data=b"abcde",
        )
    )
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_END,
                data=RPCMsgDexDumpEnd(
                    transfer_id=transfer_id,
                    tag="demo",
                    expected_count=2,
                    received_count=2,
                    total_bytes=5,
                ),
            )
        )
    )

    assert (target_dir / "classes00.dex").read_bytes() == b"abc"
    assert (target_dir / "classes01.dex").read_bytes() == b"de"
    assert not (target_dir / "20260330015015656963_classes.json").exists()
    manifest = json.loads((target_dir / "classes.json").read_text(encoding="utf-8"))
    assert [item["output_name"] for item in manifest] == ["classes00.dex", "classes01.dex"]
    assert list(target_dir.glob("*_classes.json")) == []
    assert "[dex] begin dex-1" in stdout.getvalue()
    assert "classes00.dex" in stdout.getvalue()
    assert "classes01.dex" in stdout.getvalue()
    assert "[dex] complete dex-1" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_registry_falls_back_to_agent_datadir_for_dex_dump(tmp_path: Path) -> None:
    config = _config(tmp_path)
    registry = HandlerRegistry(config, io.StringIO(), io.StringIO())

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_BEGIN,
                data=RPCMsgDexDumpBegin(
                    transfer_id="dex-2",
                    expected_count=0,
                    total_bytes=0,
                    max_batch_bytes=1024,
                ),
            )
        )
    )

    assert (tmp_path / "data" / "dextools").exists()
