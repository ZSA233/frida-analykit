import asyncio
import gc

from frida_analykit.rpc.handle_ref import HandleRef
from frida_analykit.rpc.handler.js_handle import AsyncJsHandle, SyncJsHandle
from frida_analykit.rpc.message import RPCMsgEnumerateObjProps, RPCMsgScopeCall


class _FakeRPCClient:
    def __init__(self, *, interactive: bool = False) -> None:
        self.interactive = interactive
        self.enumerations: list[HandleRef | list[HandleRef]] = []
        self.value_calls: list[str] = []
        self.call_calls: list[tuple[str, tuple[object, ...]]] = []
        self.released: list[str] = []
        self.async_released: list[str] = []
        self.prop_map: dict[str, dict[str, str]] = {}
        self.value_map: dict[str, object] = {}
        self.async_value_map: dict[str, object] = {}
        self.call_result = RPCMsgScopeCall(id="slot-1", type="object", has_result=False)
        self.async_call_result = RPCMsgScopeCall(id="slot-2", type="promise", has_result=False)

    def enumerate_props(self, refs: HandleRef | list[HandleRef]) -> RPCMsgEnumerateObjProps:
        self.enumerations.append(refs)
        items = refs if isinstance(refs, list) else [refs]
        return RPCMsgEnumerateObjProps(
            props=[self.prop_map.get(item.render(), {}) for item in items],
        )

    async def enumerate_props_async(self, refs: HandleRef | list[HandleRef]) -> RPCMsgEnumerateObjProps:
        return self.enumerate_props(refs)

    def get_value(self, ref: HandleRef) -> object:
        self.value_calls.append(ref.render())
        return self.value_map[ref.render()]

    async def get_value_async(self, ref: HandleRef) -> object:
        self.value_calls.append(ref.render())
        return self.async_value_map[ref.render()]

    def call(self, ref: HandleRef, args: tuple[object, ...]) -> RPCMsgScopeCall:
        self.call_calls.append((ref.render(), args))
        return self.call_result

    async def call_async(self, ref: HandleRef, args: tuple[object, ...]) -> RPCMsgScopeCall:
        self.call_calls.append((ref.render(), args))
        return self.async_call_result

    def release_scope_ref(self, ref: HandleRef) -> None:
        self.released.append(ref.render())

    async def release_scope_ref_async(self, ref: HandleRef) -> None:
        self.async_released.append(ref.render())


def test_handle_meta_suffixes_do_not_steal_real_value_or_type_properties() -> None:
    client = _FakeRPCClient()
    client.prop_map = {
        "Process": {
            "value": "string",
            "type": "string",
        },
        "Process/value": {},
        "Process/type": {},
    }
    client.value_map["Process"] = {"pid": 1}

    proc = SyncJsHandle.from_seed_path("Process", client=client)

    assert proc.value_ == {"pid": 1}
    assert str(proc.value) == "Process/value"
    assert str(proc["type"]) == "Process/type"
    assert proc.type_ == "unknown"
    assert "value_" in dir(proc)
    assert "value" in dir(proc)


def test_scope_backed_only_releases_owned_root_ref() -> None:
    client = _FakeRPCClient()
    child = SyncJsHandle(HandleRef.scope("slot-1", segments=("name",)), client=client, props={})

    del child
    gc.collect()

    assert client.released == []

    root = SyncJsHandle(HandleRef.scope("slot-1"), client=client, props={})

    del root
    gc.collect()

    assert client.released == ["scope[slot-1]"]


def test_scope_child_keeps_root_slot_alive_for_chained_calls() -> None:
    client = _FakeRPCClient()
    client.prop_map = {
        "scope[slot-1]": {"method": "function"},
        "scope[slot-1]/method": {},
    }

    def make_child() -> SyncJsHandle:
        return SyncJsHandle(HandleRef.scope("slot-1"), client=client).method

    child = make_child()

    assert client.released == []

    del child
    gc.collect()

    assert client.released == ["scope[slot-1]"]


def test_explicit_release_drops_owned_scope_slot_without_waiting_for_gc() -> None:
    client = _FakeRPCClient()
    root = SyncJsHandle(HandleRef.scope("slot-1"), client=client, props={})

    root.release()
    root.release()

    assert client.released == ["scope[slot-1]"]


def test_releasing_scope_child_releases_its_owned_root_slot() -> None:
    client = _FakeRPCClient()
    client.prop_map = {
        "scope[slot-1]": {"dispose": "function"},
        "scope[slot-1]/dispose": {},
    }
    child = SyncJsHandle(HandleRef.scope("slot-1"), client=client).dispose

    child.release()

    assert client.released == ["scope[slot-1]"]


def test_interactive_handle_prefetches_sibling_props_in_one_batch() -> None:
    client = _FakeRPCClient(interactive=True)
    client.prop_map = {
        "Process": {
            "alpha": "function",
            "beta": "object",
        },
        "Process/alpha": {"length": "number"},
        "Process/beta": {"name": "string"},
    }

    proc = SyncJsHandle.from_seed_path("Process", client=client)
    child = proc.alpha

    assert isinstance(child, SyncJsHandle)
    assert [ref.render() for ref in client.enumerations[1]] == ["Process/alpha", "Process/beta"]  # type: ignore[index]
    assert "length" in dir(child)


def test_call_async_and_resolve_async_use_async_rpc_path() -> None:
    client = _FakeRPCClient()
    client.prop_map["Process"] = {"fetch": "function"}
    client.prop_map["Process/fetch"] = {}
    client.prop_map["scope[slot-2]"] = {"then": "function"}
    client.async_value_map["scope[slot-2]"] = "done"

    proc = AsyncJsHandle.from_seed_path("Process", client=client)
    result = asyncio.run(proc.call_async("demo"))

    assert isinstance(result, AsyncJsHandle)
    assert client.call_calls == [("Process", ("demo",))]
    assert result.type_ == "promise"
    assert asyncio.run(result.resolve_async()) == "done"


def test_from_scope_result_async_hydrates_props_with_async_enumeration() -> None:
    client = _FakeRPCClient()
    client.prop_map["scope[slot-3]"] = {"dispose": "function"}

    handle = asyncio.run(
        AsyncJsHandle.from_scope_result_async(
            RPCMsgScopeCall(id="slot-3", type="object", has_result=False),
            client=client,
        )
    )

    assert "dispose" in dir(handle)
    assert client.enumerations == [HandleRef.scope("slot-3")]


def test_release_async_uses_async_scope_release() -> None:
    client = _FakeRPCClient()
    root = AsyncJsHandle(HandleRef.scope("slot-4"), client=client, props={})

    asyncio.run(root.release_async())

    assert client.async_released == ["scope[slot-4]"]
