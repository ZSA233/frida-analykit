import io
import json
from pathlib import Path

import pytest

from frida_analykit.config import AppConfig
from frida_analykit.rpc.message import (
    RPCMessage,
    RPCMsgDexDumpBegin,
    RPCMsgDexDumpEnd,
    RPCMsgDumpDexFile,
    RPCMsgDexDumpFileInfo,
    RPCMsgSaveFile,
    RPCMsgSSLSecret,
    RPCMsgType,
    RPCPayload,
)
from frida_analykit.rpc.registry import HandlerRegistry
from frida_analykit.rpc.resolver import RPCResolver


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": str(tmp_path / "_agent.js"),
            "server": {"host": "local"},
            "agent": {"datadir": str(tmp_path / "data")},
            "script": {
                "nettools": {"output_dir": str(tmp_path / "ssl")},
                "dextools": {"output_dir": str(tmp_path / "dex")},
            },
        }
    ).resolve_paths(tmp_path)


class _FakeRegistry:
    def __init__(self) -> None:
        self.handled: list[RPCPayload] = []
        self.exceptions: list[tuple[dict, bytes | None]] = []

    def handle(self, payload: RPCPayload) -> None:
        self.handled.append(payload)

    def handle_exception(self, message: dict, data: bytes | None) -> None:
        self.exceptions.append((message, data))


class _FakeScript:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on(self, signal: str, callback) -> None:
        self.handlers[signal] = callback


def test_default_handler_writes_binary_payload(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)
    payload = RPCPayload(
        message=RPCMessage(
            type=RPCMsgType.SAVE_FILE,
            data=RPCMsgSaveFile(source="demo", filepath="demo.bin", mode="wb"),
        ),
        data=b"hello",
    )

    registry.handle(payload)

    written = list((tmp_path / "data").glob("SAVE_FILE_*"))
    assert len(written) == 1
    assert written[0].read_bytes() == b"hello"


def test_default_exception_handler_formats_script_errors(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    registry = HandlerRegistry(_config(tmp_path), stdout, stderr)

    registry.handle_exception(
        {
            "description": "Unable to load module",
            "stack": "Error: Unable to load module\n    at /__inject__.js:1:1",
            "fileName": "/__inject__.js",
            "lineNumber": 1,
            "columnNumber": 1,
        },
        None,
    )

    output = stderr.getvalue()
    assert "[script-error] /__inject__.js:1:1" in output
    assert "[script-error] Unable to load module" in output
    assert "Error: Unable to load module" in output


def test_registry_forwards_host_handler_logs_to_sink(tmp_path: Path) -> None:
    emitted: list[tuple[str, str]] = []
    registry = HandlerRegistry(
        _config(tmp_path),
        io.StringIO(),
        io.StringIO(),
        log_sink=lambda level, text: emitted.append((level, text)),
    )

    transfer_id = "dex-1"
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_BEGIN,
                data=RPCMsgDexDumpBegin(
                    transfer_id=transfer_id,
                    tag="demo",
                    expected_count=1,
                    total_bytes=3,
                    max_batch_bytes=1024,
                ),
            )
        )
    )
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DUMP_DEX_FILE,
                data=RPCMsgDumpDexFile(
                    transfer_id=transfer_id,
                    tag="demo",
                    info=RPCMsgDexDumpFileInfo(
                        name="classes00.dex",
                        base="0x1000",
                        size=3,
                        loader="0x1",
                        loader_class="dalvik.system.PathClassLoader",
                        output_name="classes00.dex",
                    ),
                ),
            ),
            data=b"abc",
        )
    )
    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.DEX_DUMP_END,
                data=RPCMsgDexDumpEnd(
                    transfer_id=transfer_id,
                    tag="demo",
                    expected_count=1,
                    received_count=1,
                    total_bytes=3,
                ),
            )
        )
    )

    assert any(level == "info" and text.startswith("[dex] begin dex-1") for level, text in emitted)
    assert any(level == "info" and text.startswith("[dex] complete dex-1") for level, text in emitted)


def test_registry_writes_ssl_secrets_into_tagged_nettools_leaf(tmp_path: Path) -> None:
    registry = HandlerRegistry(_config(tmp_path), io.StringIO(), io.StringIO())

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.SSL_SECRET,
                data=RPCMsgSSLSecret(
                    tag="demo",
                    label="CLIENT_RANDOM",
                    client_random="abcd",
                    secret="1234",
                ),
            )
        )
    )

    target_dir = tmp_path / "ssl" / "demo"
    assert (target_dir / "sslkey.log").read_text(encoding="utf-8").strip() == "CLIENT_RANDOM abcd 1234"
    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tag"] == "demo"
    assert manifest["effective_tag"] == "demo"
    assert manifest["actual_relative_dir"] == "demo"
    assert manifest["configured_output_root"] == str((tmp_path / "ssl").resolve())
    assert manifest["output_name"] == "sslkey.log"


@pytest.mark.parametrize(
    ("tag", "effective_tag"),
    [
        ("..", "default"),
        ("测试", "default"),
        ("alpha/beta", "alpha_beta"),
    ],
)
def test_registry_normalizes_ssl_secret_tags_into_single_leaf(
    tmp_path: Path,
    tag: str,
    effective_tag: str,
) -> None:
    registry = HandlerRegistry(_config(tmp_path), io.StringIO(), io.StringIO())

    registry.handle(
        RPCPayload(
            message=RPCMessage(
                type=RPCMsgType.SSL_SECRET,
                data=RPCMsgSSLSecret(
                    tag=tag,
                    label="CLIENT_RANDOM",
                    client_random="abcd",
                    secret="1234",
                ),
            )
        )
    )

    target_dir = tmp_path / "ssl" / effective_tag
    assert (target_dir / "sslkey.log").read_text(encoding="utf-8").strip() == "CLIENT_RANDOM abcd 1234"
    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tag"] == tag
    assert manifest["effective_tag"] == effective_tag
    assert manifest["actual_relative_dir"] == effective_tag


def test_resolver_dispatches_send_and_error_messages() -> None:
    registry = _FakeRegistry()
    resolver = RPCResolver(registry)  # type: ignore[arg-type]
    script = _FakeScript()

    resolver.register_script(script)  # type: ignore[arg-type]
    handler = script.handlers["message"]
    handler(  # type: ignore[operator]
        {
            "type": "send",
            "payload": {
                "type": RPCMsgType.SAVE_FILE.value,
                "data": {
                    "source": "demo",
                    "filepath": "demo.bin",
                    "mode": "wb",
                },
            },
        },
        b"abc",
    )
    handler({"type": "error", "description": "boom"}, None)  # type: ignore[operator]

    assert registry.handled[0].message.type == RPCMsgType.SAVE_FILE
    assert registry.handled[0].data == b"abc"
    assert registry.exceptions == [({"type": "error", "description": "boom"}, None)]
