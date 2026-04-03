import asyncio

import pytest

from frida_analykit.rpc.exports import (
    ScriptExportCapabilityError,
    ScriptExportsAsyncWrapper,
    ScriptExportsSyncWrapper,
    make_rpc_response,
)
from frida_analykit.rpc.handle_ref import HANDLE_REF_MARKER, HandleRef
from frida_analykit.rpc.message import RPCMsgEnumerateObjProps, RPCMsgType, RPCPayload
from frida_analykit.rpc.serialization import serialize_rpc_argument


class _FakeHandle:
    def __init__(self, path: str) -> None:
        self._ref = HandleRef.from_seed_path(path)

    def to_handle_ref(self) -> HandleRef:
        return self._ref


class _FakeSyncExports:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def ping(self, *args, **kwargs):
        self.calls.append(("ping", args, kwargs))
        return {
            "type": RPCMsgType.ENUMERATE_OBJ_PROPS.value,
            "data": {
                "props": [{"use": "function"}],
            },
        }

    def plain_payload(self, *args, **kwargs):
        self.calls.append(("plain_payload", args, kwargs))
        return {"type": "demo"}

    def binary_payload(self, *args, **kwargs):
        self.calls.append(("binary_payload", args, kwargs))
        return ({"type": "demo"}, b"demo")


class _FakeAsyncExports:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def ping(self, *args, **kwargs):
        self.calls.append(("ping", args, kwargs))
        return {
            "type": RPCMsgType.ENUMERATE_OBJ_PROPS.value,
            "data": {
                "props": [{"use": "function"}],
            },
        }

    async def plain_payload(self, *args, **kwargs):
        self.calls.append(("plain_payload", args, kwargs))
        return {"type": "demo"}

    async def binary_payload(self, *args, **kwargs):
        self.calls.append(("binary_payload", args, kwargs))
        return ({"type": "demo"}, b"demo")


class _FakeScript:
    def __init__(self) -> None:
        self.exports_sync = _FakeSyncExports()
        self.exports_async = _FakeAsyncExports()

    def list_exports_sync(self) -> list[str]:
        return ["ping", "scopeEvalAsync"]

    async def list_exports_async(self) -> list[str]:
        return ["ping", "scopeEvalAsync"]


class _FakeShimOnlyScript:
    def __init__(self) -> None:
        self.exports_sync = _FakeSyncExports()

    def list_exports_sync(self) -> list[str]:
        return ["ping"]


class _FakeIncompleteRPCScript:
    def __init__(self) -> None:
        self.exports_sync = _FakeSyncExports()
        self.exports_async = _FakeAsyncExports()

    def list_exports_sync(self) -> list[str]:
        return ["ping"]

    async def list_exports_async(self) -> list[str]:
        return ["scopeEvalAsync"]


def test_make_rpc_response_wraps_mapping_into_rpc_payload() -> None:
    payload = make_rpc_response(
        {
            "type": RPCMsgType.ENUMERATE_OBJ_PROPS.value,
            "data": {
                "props": [{"use": "function"}],
            },
        }
    )

    assert isinstance(payload, RPCPayload)
    assert payload.message.type == RPCMsgType.ENUMERATE_OBJ_PROPS
    assert isinstance(payload.message.data, RPCMsgEnumerateObjProps)
    assert payload.message.data.props == [{"use": "function"}]


def test_make_rpc_response_leaves_non_rpc_values_untouched() -> None:
    assert make_rpc_response("pong") == "pong"
    assert make_rpc_response({"hello": "world"}) == {"hello": "world"}


def test_sync_exports_wrapper_serializes_handle_arguments() -> None:
    script = _FakeScript()
    wrapper = ScriptExportsSyncWrapper(
        script,
        serializer=serialize_rpc_argument,
        response_adapter=make_rpc_response,
    )

    payload = wrapper.ping(
        _FakeHandle("Process"),
        {"target": _FakeHandle("Process/getCurrentThreadId")},
    )

    assert isinstance(payload, RPCPayload)
    _, args, kwargs = script.exports_sync.calls[0]
    assert kwargs == {}
    assert args[0][HANDLE_REF_MARKER] == "path"
    assert args[0]["segments"] == ["Process"]
    assert args[1]["target"][HANDLE_REF_MARKER] == "path"
    assert args[1]["target"]["segments"] == ["Process", "getCurrentThreadId"]
    assert wrapper._list_exports() == ["ping", "scope_eval_async"]


def test_async_exports_wrapper_normalizes_rpc_payloads() -> None:
    script = _FakeScript()
    wrapper = ScriptExportsAsyncWrapper(
        script,
        serializer=serialize_rpc_argument,
        response_adapter=make_rpc_response,
    )

    payload = asyncio.run(wrapper.ping(_FakeHandle("Process")))

    assert isinstance(payload, RPCPayload)
    assert payload.message.type == RPCMsgType.ENUMERATE_OBJ_PROPS
    _, args, kwargs = script.exports_async.calls[0]
    assert kwargs == {}
    assert args[0]["segments"] == ["Process"]
    assert asyncio.run(wrapper._list_exports()) == ["ping", "scope_eval_async"]


def test_public_sync_exports_wrapper_leaves_plain_type_mapping_untouched() -> None:
    script = _FakeScript()
    wrapper = ScriptExportsSyncWrapper(script)

    payload = wrapper.plain_payload()

    assert payload == {"type": "demo"}
    method, args, kwargs = script.exports_sync.calls[0]
    assert method == "plain_payload"
    assert args == ()
    assert kwargs == {}


def test_public_async_exports_wrapper_leaves_non_rpc_binary_tuple_untouched() -> None:
    script = _FakeScript()
    wrapper = ScriptExportsAsyncWrapper(script)

    payload = asyncio.run(wrapper.binary_payload())

    assert payload == ({"type": "demo"}, b"demo")
    method, args, kwargs = script.exports_async.calls[0]
    assert method == "binary_payload"
    assert args == ()
    assert kwargs == {}


def test_async_exports_wrapper_falls_back_to_shim_when_native_async_surface_is_missing() -> None:
    script = _FakeShimOnlyScript()
    wrapper = ScriptExportsAsyncWrapper(script, response_adapter=make_rpc_response)

    payload = asyncio.run(wrapper.ping())

    assert isinstance(payload, RPCPayload)
    assert wrapper.backend_mode == "shim"
    assert script.exports_sync.calls == [("ping", (), {})]


def test_async_exports_wrapper_reports_missing_sync_fallback_exports() -> None:
    script = _FakeIncompleteRPCScript()
    wrapper = ScriptExportsAsyncWrapper(
        script,
        required_native_exports=("scope_eval_async", "scope_call_async"),
        required_sync_exports=("scope_eval", "scope_call"),
        shim_name_map={"scope_eval_async": "scope_eval", "scope_call_async": "scope_call"},
    )

    with pytest.raises(ScriptExportCapabilityError, match="scope_eval, scope_call"):
        asyncio.run(wrapper.scope_eval_async("Process.arch"))
