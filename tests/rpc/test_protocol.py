import asyncio

import pytest

from frida_analykit.rpc.client import AsyncRPCClient, SyncRPCClient
from frida_analykit.rpc.handle_ref import HandleRef
from frida_analykit.rpc.message import RPCMsgEnumerateObjProps, RPCMsgType
from frida_analykit.rpc.protocol import RPC_PROTOCOL_VERSION, RPCCompatibilityError


class _FakeSyncExports:
    def __init__(self, runtime_info: object | None) -> None:
        self.runtime_info = runtime_info
        self.runtime_info_calls = 0
        self.enumerate_calls = 0
        self.scope_eval_calls = 0
        self.scope_call_calls = 0
        self.scope_get_calls = 0
        self.scope_clear_calls = 0
        self.scope_del_calls: list[object] = []

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

    def scope_eval(self, *args, **kwargs):
        del args, kwargs
        self.scope_eval_calls += 1
        return {
            "type": RPCMsgType.SCOPE_EVAL.value,
            "data": {
                "id": "slot-sync-eval",
                "type": "string",
                "result": "ok",
                "has_result": True,
            },
        }

    def scope_call(self, *args, **kwargs):
        del args, kwargs
        self.scope_call_calls += 1
        return {
            "type": RPCMsgType.SCOPE_CALL.value,
            "data": {
                "id": "slot-sync-call",
                "type": "string",
                "result": "ok",
                "has_result": True,
            },
        }

    def scope_get(self, *args, **kwargs):
        del args, kwargs
        self.scope_get_calls += 1
        return {
            "type": RPCMsgType.SCOPE_GET.value,
            "data": {
                "value": "ok",
                "has_value": True,
            },
        }

    def scope_clear(self, *args, **kwargs) -> None:
        del args, kwargs
        self.scope_clear_calls += 1

    def scope_del(self, ref: object, scope_id: object) -> None:
        self.scope_del_calls.append((ref, scope_id))


class _FakeAsyncExports:
    def __init__(self, runtime_info: object | None) -> None:
        self.runtime_info = runtime_info
        self.runtime_info_calls = 0
        self.scope_eval_calls = 0
        self.scope_call_calls = 0
        self.scope_get_calls = 0
        self.scope_clear_calls = 0
        self.enumerate_calls = 0
        self.scope_del_calls: list[object] = []

    async def rpc_runtime_info(self) -> object | None:
        self.runtime_info_calls += 1
        return self.runtime_info

    async def enumerate_obj_props(self, *args, **kwargs):
        del args, kwargs
        self.enumerate_calls += 1
        return {
            "type": RPCMsgType.ENUMERATE_OBJ_PROPS.value,
            "data": {"props": [{"arch": "string"}]},
        }

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

    async def scope_call_async(self, *args, **kwargs):
        del args, kwargs
        self.scope_call_calls += 1
        return {
            "type": RPCMsgType.SCOPE_CALL.value,
            "data": {
                "id": "slot-async-call",
                "type": "string",
                "result": "ok",
                "has_result": True,
            },
        }

    async def scope_get_async(self, *args, **kwargs):
        del args, kwargs
        self.scope_get_calls += 1
        return {
            "type": RPCMsgType.SCOPE_GET.value,
            "data": {
                "value": "ok",
                "has_value": True,
            },
        }

    async def scope_clear(self, *args, **kwargs) -> None:
        del args, kwargs
        self.scope_clear_calls += 1

    async def scope_del(self, ref: object, scope_id: object) -> None:
        self.scope_del_calls.append((ref, scope_id))


class _FakeScript:
    def __init__(
        self,
        *,
        sync_exports: list[str],
        async_exports: list[str],
        runtime_info: object | None,
    ) -> None:
        self._sync_exports = sync_exports
        self._async_exports = async_exports
        self.exports_sync = _FakeSyncExports(runtime_info)
        self.exports_async = _FakeAsyncExports(runtime_info)

    def list_exports_sync(self) -> list[str]:
        return list(self._sync_exports)

    async def list_exports_async(self) -> list[str]:
        return list(self._async_exports)


def _assert_mismatch_message(exc: RPCCompatibilityError) -> None:
    text = str(exc)
    assert "runtime mismatch" in text
    assert "rebuild" in text
    assert "_agent.js" in text
    assert "local packed runtime" in text


def test_missing_runtime_info_export_raises_readable_mismatch() -> None:
    client = SyncRPCClient(
        _FakeScript(
            sync_exports=["enumerateObjProps"],
            async_exports=["enumerateObjProps"],
            runtime_info=None,
        ),
        scope_id="scope-1",
    )

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
    client = AsyncRPCClient(
        _FakeScript(
            sync_exports=["rpcRuntimeInfo", "scopeEval", "scopeCall", "scopeGet", "scopeClear", "scopeDel", "enumerateObjProps"],
            async_exports=[
                "rpcRuntimeInfo",
                "scopeEvalAsync",
                "scopeCallAsync",
                "scopeGetAsync",
                "scopeClear",
                "scopeDel",
                "enumerateObjProps",
            ],
            runtime_info=runtime_info,
        ),
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
    client = SyncRPCClient(
        _FakeScript(
            sync_exports=["rpcRuntimeInfo", "enumerateObjProps"],
            async_exports=["rpcRuntimeInfo", "enumerateObjProps"],
            runtime_info=runtime_info,
        ),
        scope_id="scope-1",
    )

    first = client.enumerate_props(HandleRef.from_seed_path("Process"))
    second = client.enumerate_props(HandleRef.from_seed_path("Process"))

    assert isinstance(first, RPCMsgEnumerateObjProps)
    assert isinstance(second, RPCMsgEnumerateObjProps)
    assert client._rpc_exports_sync._exports.runtime_info_calls == 1
    assert client._rpc_exports_sync._exports.enumerate_calls == 2


def test_enumerate_props_async_prefers_native_async_when_capability_is_complete() -> None:
    runtime_info = {
        "protocol_version": RPC_PROTOCOL_VERSION,
        "features": ["handle_ref", "async_scope"],
    }
    client = AsyncRPCClient(
        _FakeScript(
            sync_exports=["rpcRuntimeInfo", "scopeEval", "scopeCall", "scopeGet", "scopeClear", "scopeDel", "enumerateObjProps"],
            async_exports=[
                "rpcRuntimeInfo",
                "scopeEvalAsync",
                "scopeCallAsync",
                "scopeGetAsync",
                "scopeClear",
                "scopeDel",
                "enumerateObjProps",
            ],
            runtime_info=runtime_info,
        ),
        scope_id="scope-1",
    )

    result = asyncio.run(client.enumerate_props_async(HandleRef.from_seed_path("Process")))

    assert isinstance(result, RPCMsgEnumerateObjProps)
    assert client._rpc_exports_async.backend_mode == "native"
    exports = client._rpc_exports_async._exports
    assert exports is not None
    assert exports.runtime_info_calls == 1
    assert exports.enumerate_calls == 1


def test_async_client_falls_back_to_shim_when_native_async_is_incomplete() -> None:
    runtime_info = {
        "protocol_version": RPC_PROTOCOL_VERSION,
        "features": ["handle_ref", "async_scope"],
    }
    client = AsyncRPCClient(
        _FakeScript(
            sync_exports=["rpcRuntimeInfo", "scopeEval", "scopeCall", "scopeGet", "scopeClear", "scopeDel", "enumerateObjProps"],
            async_exports=["rpcRuntimeInfo", "enumerateObjProps"],
            runtime_info=runtime_info,
        ),
        scope_id="scope-1",
    )

    result = asyncio.run(client.enumerate_props_async(HandleRef.from_seed_path("Process")))

    assert isinstance(result, RPCMsgEnumerateObjProps)
    assert client._rpc_exports_async.backend_mode == "shim"
    exports = client._rpc_exports_async._exports
    assert exports is not None
    assert exports.runtime_info_calls == 1
    assert exports.enumerate_calls == 1
