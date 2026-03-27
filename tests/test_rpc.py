import io
from pathlib import Path

from frida_analykit.config import AppConfig
from frida_analykit.rpc.message import RPCMessage, RPCMsgBatch, RPCMsgSaveFile, RPCMsgType, RPCPayload, unpack_batch_payload
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


def test_unpack_batch_payload_splits_data_stream() -> None:
    payload = RPCPayload(
        message=RPCMessage(
            type=RPCMsgType.BATCH,
            data=RPCMsgBatch(
                message_list=[
                    RPCMessage(type=RPCMsgType.SAVE_FILE, data=RPCMsgSaveFile(source="a", filepath="x", mode="wb")),
                    RPCMessage(type=RPCMsgType.SAVE_FILE, data=RPCMsgSaveFile(source="b", filepath="y", mode="wb")),
                ],
                data_sizes=[3, 2],
            ),
        ),
        data=b"abcde",
    )

    chunks = unpack_batch_payload(payload)

    assert [chunk.data for chunk in chunks] == [b"abc", b"de"]


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
