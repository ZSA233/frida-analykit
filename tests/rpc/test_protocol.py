import asyncio

import pytest

from frida_analykit.rpc.client import RPCClient
from frida_analykit.rpc.handle_ref import HandleRef
from frida_analykit.rpc.message import RPCMsgEnumerateObjProps, RPCMsgType
from frida_analykit.rpc.protocol import RPC_PROTOCOL_VERSION, RPCCompatibilityError


class _FakeSyncExports:
    def __init__(self, runtime_info: object | None) -> None:
        self.runtime_info = runtime_info
        self.runtime_info_calls = 0
        self.enumerate_calls = 0

    def rpc_runtime_info(self) -> object | None:
        self.runtime_info_calls += 1
        return self.runtime_info

    def enumerate_obj_props(self, *args, **kwargs):
        del args, kwargs
        self.enumerate_calls += 1
        return {
            "type": RPCMsgType.ENUMERATE_OBJ_PROPS.value,
            "data": {"props": [{"arch": "string"}]},
        }


class _FakeAsyncExports:
    def __init__(self, runtime_info: object | None) -> None:
        self.runtime_info = runtime_info
        self.runtime_info_calls = 0
        self.scope_eval_calls = 0

    async def rpc_runtime_info(self) -> object | None:
        self.runtime_info_calls += 1
        return self.runtime_info

    async def scope_eval_async(self, *args, **kwargs):
        del args, kwargs
        self.scope_eval_calls += 1
        return {
            "type": RPCMsgType.SCOPE_EVAL.value,
            "data": {
                "id": "slot-1",
                "type": "string",
                "result": "ok",
                "has_result": True,
            },
        }


class _FakeScript:
    def __init__(self, exports: list[str], runtime_info: object | None) -> None:
        self._exports = exports
        self.exports_sync = _FakeSyncExports(runtime_info)
        self.exports_async = _FakeAsyncExports(runtime_info)

    def list_exports_sync(self) -> list[str]:
        return list(self._exports)

    async def list_exports_async(self) -> list[str]:
        return list(self._exports)


def _assert_mismatch_message(exc: RPCCompatibilityError) -> None:
    text = str(exc)
    assert "runtime mismatch" in text
    assert "rebuild" in text
    assert "_agent.js" in text
    assert "local packed runtime" in text


def test_missing_runtime_info_export_raises_readable_mismatch() -> None:
    client = RPCClient(_FakeScript(["enumerateObjProps"], runtime_info=None), scope_id="scope-1")

    with pytest.raises(RPCCompatibilityError) as exc_info:
        client.enumerate_props(HandleRef.from_seed_path("Process"))

    _assert_mismatch_message(exc_info.value)
    assert "rpcRuntimeInfo()" in str(exc_info.value)
    assert client._rpc_exports_sync._exports.enumerate_calls == 0


def test_async_protocol_version_mismatch_raises_before_scope_eval() -> None:
    runtime_info = {
        "protocol_version": RPC_PROTOCOL_VERSION - 1,
        "features": ["handle_ref", "async_scope"],
    }
    client = RPCClient(
        _FakeScript(["rpcRuntimeInfo", "scopeEvalAsync"], runtime_info=runtime_info),
        scope_id="scope-1",
    )

    with pytest.raises(RPCCompatibilityError) as exc_info:
        asyncio.run(client.eval_async("Promise.resolve(1)"))

    _assert_mismatch_message(exc_info.value)
    assert f"requires {RPC_PROTOCOL_VERSION}" in str(exc_info.value)
    assert client._rpc_exports_async._exports.scope_eval_calls == 0


def test_runtime_info_is_cached_after_first_successful_check() -> None:
    runtime_info = {
        "protocol_version": RPC_PROTOCOL_VERSION,
        "features": ["handle_ref", "async_scope"],
    }
    client = RPCClient(
        _FakeScript(["rpcRuntimeInfo", "enumerateObjProps"], runtime_info=runtime_info),
        scope_id="scope-1",
    )

    first = client.enumerate_props(HandleRef.from_seed_path("Process"))
    second = client.enumerate_props(HandleRef.from_seed_path("Process"))

    assert isinstance(first, RPCMsgEnumerateObjProps)
    assert isinstance(second, RPCMsgEnumerateObjProps)
    assert client._rpc_exports_sync._exports.runtime_info_calls == 1
    assert client._rpc_exports_sync._exports.enumerate_calls == 2
