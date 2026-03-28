import io
from pathlib import Path

from frida_analykit.config import AppConfig
from frida_analykit.rpc.message import RPCMessage, RPCMsgSaveFile, RPCMsgType, RPCPayload
from frida_analykit.rpc.registry import HandlerRegistry
from frida_analykit.rpc.resolver import RPCResolver


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
