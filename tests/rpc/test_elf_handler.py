import io
import json
from pathlib import Path

import pytest

from frida_analykit.config import AppConfig
from frida_analykit.rpc.message import (
    RPCBatchSource,
    RPCMessage,
    RPCMsgBatch,
    RPCMsgElfModuleDumpBegin,
    RPCMsgElfModuleDumpChunk,
    RPCMsgElfModuleDumpEnd,
    RPCMsgElfSymbolCallLog,
    RPCMsgType,
    RPCPayload,
)
from frida_analykit.rpc.registry import HandlerRegistry


FIXUP_STAGE_ORDER = [
    "phdr-rebase",
    "dynamic-rebase",
    "dynsym-fixups",
    "relocation-fixups",
    "section-rebuild",
    "header-finalize",
]


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": str(tmp_path / "_agent.js"),
            "server": {"host": "local"},
            "agent": {"datadir": str(tmp_path / "data")},
            "script": {
                "elftools": {"output_dir": str(tmp_path / "elf")},
                "nettools": {"output_dir": str(tmp_path / "ssl")},
            },
        }
    ).resolve_paths(tmp_path)


def _chunk_payload(
    dump_id: str,
    artifact: str,
    output_name: str,
    data: bytes,
    *,
    tag: str = "demo",
    chunk_index: int = 0,
) -> RPCPayload:
    return RPCPayload(
        message=RPCMessage(
            type=RPCMsgType.ELF_MODULE_DUMP_CHUNK,
            data=RPCMsgElfModuleDumpChunk(
                dump_id=dump_id,
                tag=tag,
                artifact=artifact,
                output_name=output_name,
                chunk_index=chunk_index,
                total_size=len(data),
            ),
        ),
        data=data,
    )


def _begin_payload(
    dump_id: str,
    *,
    tag: str = "demo",
    output_dir: str | None = None,
    relative_dump_dir: str = "demo",
    module_size: int = 5,
    expected_files: list[str] | None = None,
    total_bytes: int = 0,
) -> RPCPayload:
    return RPCPayload(
        message=RPCMessage(
            type=RPCMsgType.ELF_MODULE_DUMP_BEGIN,
            data=RPCMsgElfModuleDumpBegin(
                dump_id=dump_id,
                tag=tag,
                output_dir=output_dir,
                relative_dump_dir=relative_dump_dir,
                module_name="libc.so",
                module_path="/apex/libc.so",
                module_base="0x1000",
                module_end=f"0x{0x1000 + module_size:x}",
                module_size=module_size,
                expected_files=expected_files or ["libc.raw.so"],
                total_bytes=total_bytes,
            ),
        )
    )


def _fixed_elf_header() -> bytes:
    data = bytearray(64)
    data[0:4] = b"\x7fELF"
    data[4] = 2
    data[5] = 1
    data[6] = 1
    data[7] = 0
    data[16:18] = (3).to_bytes(2, "little")
    data[18:20] = (183).to_bytes(2, "little")
    data[20:24] = (1).to_bytes(4, "little")
    return bytes(data)


def _fixups_payload(raw: bytes, fixed: bytes) -> bytes:
    stages = [
        {"name": "phdr-rebase", "detail": "synthetic phdr stage", "patches": []},
        {"name": "dynamic-rebase", "detail": "synthetic dynamic stage", "patches": []},
        {"name": "dynsym-fixups", "detail": "synthetic dynsym stage", "patches": []},
        {"name": "relocation-fixups", "detail": "synthetic relocation stage", "patches": []},
        {
            "name": "section-rebuild",
            "detail": "synthetic section stage",
            "patches": [
                {
                    "t": "x",
                    "n": "synthetic-fixed-image",
                    "o": 0,
                    "r": len(raw),
                    "x": fixed.hex(),
                }
            ],
        },
        {"name": "header-finalize", "detail": "synthetic header stage", "patches": []},
    ]
    return json.dumps(
        {
            "version": 2,
            "strategy": "raw-to-fixed-staged-v2",
            "raw_size": len(raw),
            "fixed_size": len(fixed),
            "stages": stages,
        }
    ).encode("utf-8")


def _scalar_hex_to_bytes(value: str, width: int) -> bytes:
    assert value.startswith("0x")
    hex_text = value[2:].rjust(width * 2, "0")
    return bytes.fromhex(hex_text)[::-1]


def _apply_raw_to_fixed_fixups(raw: bytes, fixups: dict[str, object]) -> bytes:
    raw_size = int(fixups["raw_size"])
    fixed_size = int(fixups["fixed_size"])
    stages = fixups["stages"]
    assert isinstance(stages, list)
    assert raw_size == len(raw)

    output = bytearray(raw)
    assert [stage["name"] for stage in stages] == FIXUP_STAGE_ORDER

    for stage in stages:
        assert isinstance(stage, dict)
        patches = stage["patches"]
        assert isinstance(patches, list)
        for patch in patches:
            assert isinstance(patch, dict)
            patch_type = str(patch["t"])
            if patch_type == "f":
                width = int(patch["w"])
                offset = int(patch["o"])
                output[offset:offset + width] = _scalar_hex_to_bytes(str(patch["a"]), width)
                continue
            if patch_type == "s":
                width = int(patch["w"])
                values = patch["v"]
                assert isinstance(values, list)
                for slot in values:
                    assert isinstance(slot, list)
                    assert len(slot) == 3
                    offset = int(slot[0])
                    output[offset:offset + width] = _scalar_hex_to_bytes(str(slot[2]), width)
                continue
            if patch_type == "x":
                offset = int(patch["o"])
                replace_size = int(patch["r"])
                data = bytes.fromhex(str(patch["x"]))
                if replace_size == 0 and offset == len(output):
                    output.extend(data)
                else:
                    output[offset:offset + replace_size] = data
                continue
            raise AssertionError(f"unsupported fixup patch type: {patch_type}")

    assert len(output) == fixed_size
    return bytes(output)


def test_registry_handles_streaming_elf_dump_and_symbol_logs(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)
    dump_id = "elf-1"
    dump_root = tmp_path / "elf" / "demo"
    dump_root.mkdir(parents=True, exist_ok=True)
    (dump_root / "stale.bin").write_bytes(b"stale")

    raw_bytes = b"abcde"
    fixed_header = _fixed_elf_header()
    fixups_bytes = _fixups_payload(raw_bytes, fixed_header)
    total_bytes = len(raw_bytes) + len(fixed_header) + len(fixups_bytes) + 2 + 4 + 2

    registry.handle(
        _begin_payload(
            dump_id,
            relative_dump_dir="demo",
            module_size=5,
            expected_files=[
                "libc.raw.so",
                "libc.fixed.so",
                "fixups.json",
                "symbols.json",
                "proc_maps.txt",
                "manifest.json",
            ],
            total_bytes=total_bytes,
        )
    )

    payloads = [
        _chunk_payload(dump_id, "raw", "libc.raw.so", b"abc", chunk_index=0),
        _chunk_payload(dump_id, "raw", "libc.raw.so", b"de", chunk_index=1),
        _chunk_payload(dump_id, "fixed", "libc.fixed.so", fixed_header),
        _chunk_payload(dump_id, "fixups", "fixups.json", fixups_bytes),
        _chunk_payload(dump_id, "symbols", "symbols.json", b"[]"),
        _chunk_payload(dump_id, "proc_maps", "proc_maps.txt", b"maps"),
        _chunk_payload(dump_id, "manifest", "manifest.json", b"{}"),
    ]
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.BATCH,
                source=RPCBatchSource.ELF_MODULE_DUMP_CHUNKS.value,
                data=RPCMsgBatch(
                    message_list=[item.message for item in payloads],
                    data_sizes=[3, 2, len(fixed_header), len(fixups_bytes), 2, 4, 2],
                ),
            ),
            data=b"".join([b"abc", b"de", fixed_header, fixups_bytes, b"[]", b"maps", b"{}"]),
        )
    )
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.ELF_MODULE_DUMP_END,
                data=RPCMsgElfModuleDumpEnd(
                    dump_id=dump_id,
                    tag="demo",
                    module_name="libc.so",
                    relative_dump_dir="demo",
                    expected_files=[
                        "libc.raw.so",
                        "libc.fixed.so",
                        "fixups.json",
                        "symbols.json",
                        "proc_maps.txt",
                        "manifest.json",
                    ],
                    total_bytes=total_bytes,
                    received_bytes=total_bytes,
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

    assert not (dump_root / "stale.bin").exists()
    assert (dump_root / "libc.raw.so").read_bytes() == raw_bytes
    fixed_bytes = (dump_root / "libc.fixed.so").read_bytes()
    fixups = json.loads((dump_root / "fixups.json").read_text(encoding="utf-8"))
    assert fixed_bytes == fixed_header
    assert [stage["name"] for stage in fixups["stages"]] == FIXUP_STAGE_ORDER
    assert _apply_raw_to_fixed_fixups(raw_bytes, fixups) == fixed_header
    assert fixed_bytes[7] == 0
    assert int.from_bytes(fixed_bytes[16:18], "little") == 3
    assert int.from_bytes(fixed_bytes[18:20], "little") == 183
    assert int.from_bytes(fixed_bytes[20:24], "little") == 1
    assert (dump_root / "symbols.json").read_bytes() == b"[]"
    assert (dump_root / "proc_maps.txt").read_bytes() == b"maps"
    manifest = json.loads((dump_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tag"] == "demo"
    assert manifest["effective_tag"] == "demo"
    assert manifest["requested_output_dir"] is None
    assert manifest["requested_relative_dump_dir"] == "demo"
    assert manifest["configured_output_root"] == str((tmp_path / "elf").resolve())
    assert manifest["actual_relative_dir"] == "demo"
    log_path = tmp_path / "elf" / "demo" / "symbols.log"
    assert "getpid" in log_path.read_text(encoding="utf-8")
    assert "[elf] begin elf-1" in stdout.getvalue()
    assert "[elf] complete elf-1" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_registry_reuses_same_tag_leaf_for_multiple_elf_dumps(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)
    target_dir = tmp_path / "elf" / "same-tag"

    for dump_id, payload_bytes in (("elf-keep-1", b"one"), ("elf-keep-2", b"two")):
        registry.handle(
            _begin_payload(
                dump_id,
                tag="same-tag",
                relative_dump_dir=f"ignored/{dump_id}",
                module_size=len(payload_bytes),
                expected_files=["libc.raw.so"],
                total_bytes=len(payload_bytes),
            )
        )
        registry.handle(_chunk_payload(dump_id, "raw", "libc.raw.so", payload_bytes))
        registry.handle(
            RPCPayload(
                message=RPCMessage(
                    type=RPCMsgType.ELF_MODULE_DUMP_END,
                    data=RPCMsgElfModuleDumpEnd(
                        dump_id=dump_id,
                        tag="same-tag",
                        module_name="libc.so",
                        relative_dump_dir=f"ignored/{dump_id}",
                        expected_files=["libc.raw.so"],
                        total_bytes=len(payload_bytes),
                        received_bytes=len(payload_bytes),
                    ),
                )
            )
        )

    assert (target_dir / "libc.raw.so").read_bytes() == b"two"
    assert not (target_dir / "elf-keep-1").exists()
    assert "[elf] complete elf-keep-1" in stdout.getvalue()
    assert "[elf] complete elf-keep-2" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_registry_ignores_runtime_elf_output_metadata_but_records_request(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)
    dump_id = "elf-requested-paths"
    target_dir = tmp_path / "elf" / "demo"

    registry.handle(
        _begin_payload(
            dump_id,
            output_dir="/tmp/evil",
            relative_dump_dir="../../ignored",
            expected_files=["libc.raw.so", "manifest.json"],
            total_bytes=6,
        )
    )
    registry.handle(_chunk_payload(dump_id, "raw", "libc.raw.so", b"abcd"))
    registry.handle(_chunk_payload(dump_id, "manifest", "manifest.json", b"{}"))
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.ELF_MODULE_DUMP_END,
                data=RPCMsgElfModuleDumpEnd(
                    dump_id=dump_id,
                    tag="demo",
                    module_name="libc.so",
                    relative_dump_dir="../../ignored",
                    expected_files=["libc.raw.so", "manifest.json"],
                    total_bytes=6,
                    received_bytes=6,
                ),
            )
        )
    )

    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["requested_output_dir"] == "/tmp/evil"
    assert manifest["requested_relative_dump_dir"] == "../../ignored"
    assert manifest["configured_output_root"] == str((tmp_path / "elf").resolve())
    assert manifest["actual_relative_dir"] == "demo"
    assert (target_dir / "libc.raw.so").read_bytes() == b"abcd"
    assert "[elf] reject dump" not in stderr.getvalue()


@pytest.mark.parametrize(
    ("tag", "effective_tag"),
    [
        ("..", "default"),
        ("测试", "default"),
        ("alpha/beta", "alpha_beta"),
    ],
)
def test_registry_normalizes_elf_tag_into_single_leaf(
    tmp_path: Path,
    tag: str,
    effective_tag: str,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)
    dump_id = "elf-safe-tag"
    target_dir = tmp_path / "elf" / effective_tag

    registry.handle(
        _begin_payload(
            dump_id,
            tag=tag,
            relative_dump_dir=effective_tag,
            expected_files=["libc.raw.so", "manifest.json"],
            total_bytes=6,
        )
    )
    registry.handle(_chunk_payload(dump_id, "raw", "libc.raw.so", b"abcd"))
    registry.handle(_chunk_payload(dump_id, "manifest", "manifest.json", b"{}"))
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.ELF_MODULE_DUMP_END,
                data=RPCMsgElfModuleDumpEnd(
                    dump_id=dump_id,
                    tag=tag,
                    module_name="libc.so",
                    relative_dump_dir=effective_tag,
                    expected_files=["libc.raw.so", "manifest.json"],
                    total_bytes=6,
                    received_bytes=6,
                ),
            )
        )
    )

    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tag"] == tag
    assert manifest["effective_tag"] == effective_tag
    assert manifest["actual_relative_dir"] == effective_tag
    assert (target_dir / "libc.raw.so").read_bytes() == b"abcd"
    assert "[elf] reject dump" not in stderr.getvalue()
