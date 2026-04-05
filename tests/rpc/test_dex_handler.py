import io
import json
from pathlib import Path

import pytest

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


def _config(tmp_path: Path, *, dextools_output_dir: Path | None = None, include_dextools: bool = True) -> AppConfig:
    script_config: dict[str, object] = {"nettools": {"output_dir": str(tmp_path / "ssl")}}
    if include_dextools:
        resolved_output_dir = dextools_output_dir or (tmp_path / "data" / "dextools")
        script_config["dextools"] = {"output_dir": str(resolved_output_dir)}
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": str(tmp_path / "_agent.js"),
            "server": {"host": "local"},
            "agent": {"datadir": str(tmp_path / "data")},
            "script": script_config,
        }
    ).resolve_paths(tmp_path)


def _dex_file_payload(
    transfer_id: str,
    output_name: str,
    data: bytes,
    *,
    tag: str = "demo",
    declared_size: int | None = None,
) -> RPCPayload:
    return RPCPayload(
        message=RPCMessage(
            type=RPCMsgType.DUMP_DEX_FILE,
            data=RPCMsgDumpDexFile(
                transfer_id=transfer_id,
                tag=tag,
                info=RPCMsgDexDumpFileInfo(
                    name=output_name,
                    base="0x1000",
                    size=len(data) if declared_size is None else declared_size,
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
    transfer_id = "dex-1"
    output_dir = tmp_path / "custom-dex"
    registry = HandlerRegistry(_config(tmp_path, dextools_output_dir=output_dir), stdout, stderr)
    target_dir = output_dir / "demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "classes00.dex").write_bytes(b"old")
    (target_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (target_dir / "20260330015015656963_classes.json").write_text("old", encoding="utf-8")

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_BEGIN,
                data=RPCMsgDexDumpBegin(
                    transfer_id=transfer_id,
                    tag="demo",
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
    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tag"] == "demo"
    assert manifest["effective_tag"] == "demo"
    assert manifest["actual_relative_dir"] == "demo"
    assert manifest["configured_output_root"] == str(output_dir.resolve())
    assert manifest["requested_dump_dir"] is None
    assert [item["output_name"] for item in manifest["files"]] == ["classes00.dex", "classes01.dex"]
    assert list(target_dir.glob("*_classes.json")) == []
    assert not (target_dir / "classes.json").exists()
    assert "[dex] begin dex-1" in stdout.getvalue()
    assert "classes00.dex" in stdout.getvalue()
    assert "classes01.dex" in stdout.getvalue()
    assert "[dex] complete dex-1" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_registry_falls_back_to_agent_datadir_for_dex_dump(tmp_path: Path) -> None:
    config = _config(tmp_path, include_dextools=False)
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


def test_registry_marks_partial_dex_dump_as_incomplete(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    transfer_id = "dex-partial"
    output_dir = tmp_path / "custom-dex"
    registry = HandlerRegistry(_config(tmp_path, dextools_output_dir=output_dir), stdout, stderr)
    target_dir = output_dir / "demo"

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_BEGIN,
                data=RPCMsgDexDumpBegin(
                    transfer_id=transfer_id,
                    tag="demo",
                    expected_count=2,
                    total_bytes=5,
                    max_batch_bytes=1024,
                ),
            )
        )
    )
    registry.handle(_dex_file_payload(transfer_id, "classes00.dex", b"abc"))
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_END,
                data=RPCMsgDexDumpEnd(
                    transfer_id=transfer_id,
                    tag="demo",
                    expected_count=2,
                    received_count=1,
                    total_bytes=5,
                ),
            )
        )
    )

    assert (target_dir / "classes00.dex").read_bytes() == b"abc"
    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [item["output_name"] for item in manifest["files"]] == ["classes00.dex"]
    assert manifest["received_count"] == 1
    assert "[dex] complete dex-partial" not in stdout.getvalue()
    assert "[dex] incomplete transfer dex-partial" in stderr.getvalue()


def test_registry_marks_size_mismatch_dex_dump_as_incomplete(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    transfer_id = "dex-size-mismatch"
    output_dir = tmp_path / "custom-dex"
    registry = HandlerRegistry(_config(tmp_path, dextools_output_dir=output_dir), stdout, stderr)
    target_dir = output_dir / "demo"

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_BEGIN,
                data=RPCMsgDexDumpBegin(
                    transfer_id=transfer_id,
                    tag="demo",
                    expected_count=1,
                    total_bytes=4,
                    max_batch_bytes=1024,
                ),
            )
        )
    )
    registry.handle(_dex_file_payload(transfer_id, "classes00.dex", b"abc", declared_size=4))
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_END,
                data=RPCMsgDexDumpEnd(
                    transfer_id=transfer_id,
                    tag="demo",
                    expected_count=1,
                    received_count=1,
                    total_bytes=4,
                ),
            )
        )
    )

    assert (target_dir / "classes00.dex").read_bytes() == b"abc"
    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"][0]["size"] == 4
    assert manifest["mismatched_files"] == ["classes00.dex"]
    assert "[dex] complete dex-size-mismatch" not in stdout.getvalue()
    assert "[dex] size mismatch dex-size-mismatch" in stderr.getvalue()
    assert "[dex] incomplete transfer dex-size-mismatch" in stderr.getvalue()


def test_registry_ignores_runtime_dex_dump_dir_override_but_records_request(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)
    transfer_id = "dex-requested-dir"
    target_dir = tmp_path / "data" / "dextools" / "demo"

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_BEGIN,
                data=RPCMsgDexDumpBegin(
                    transfer_id=transfer_id,
                    tag="demo",
                    dump_dir="../sentinel",
                    expected_count=1,
                    total_bytes=1,
                    max_batch_bytes=1024,
                ),
            )
        )
    )
    registry.handle(_dex_file_payload(transfer_id, "classes00.dex", b"a"))
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_END,
                data=RPCMsgDexDumpEnd(
                    transfer_id=transfer_id,
                    tag="demo",
                    expected_count=1,
                    received_count=1,
                    total_bytes=1,
                ),
            )
        )
    )

    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["requested_dump_dir"] == "../sentinel"
    assert manifest["configured_output_root"] == str((tmp_path / "data" / "dextools").resolve())
    assert manifest["actual_relative_dir"] == "demo"
    assert (target_dir / "classes00.dex").read_bytes() == b"a"
    assert "[dex] reject transfer" not in stderr.getvalue()


@pytest.mark.parametrize(
    ("tag", "effective_tag"),
    [
        ("..", "default"),
        ("测试", "default"),
        ("alpha/beta", "alpha_beta"),
    ],
)
def test_registry_normalizes_dex_tag_into_single_leaf(
    tmp_path: Path,
    tag: str,
    effective_tag: str,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    transfer_id = "dex-safe-tag"
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)
    target_dir = tmp_path / "data" / "dextools" / effective_tag

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_BEGIN,
                data=RPCMsgDexDumpBegin(
                    transfer_id=transfer_id,
                    tag=tag,
                    expected_count=1,
                    total_bytes=1,
                    max_batch_bytes=1024,
                ),
            )
        )
    )
    registry.handle(_dex_file_payload(transfer_id, "classes00.dex", b"a", tag=tag))
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_END,
                data=RPCMsgDexDumpEnd(
                    transfer_id=transfer_id,
                    tag=tag,
                    expected_count=1,
                    received_count=1,
                    total_bytes=1,
                ),
            )
        )
    )

    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tag"] == tag
    assert manifest["effective_tag"] == effective_tag
    assert manifest["actual_relative_dir"] == effective_tag
    assert (target_dir / "classes00.dex").read_bytes() == b"a"
    assert "[dex] reject transfer" not in stderr.getvalue()
