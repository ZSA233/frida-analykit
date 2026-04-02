from __future__ import annotations

import asyncio
import functools
import weakref
from threading import Lock
from typing import Any, Final, Protocol

from ..handle_ref import HandleRef
from ..message import RPCMsgEnumerateObjProps, RPCMsgScopeCall, RPCMsgScopeEval


class SyncHandleClient(Protocol):
    interactive: bool

    def enumerate_props(self, refs: HandleRef | list[HandleRef]) -> RPCMsgEnumerateObjProps: ...

    def get_value(self, ref: HandleRef) -> Any: ...

    def call(self, ref: HandleRef, args: tuple[object, ...]) -> RPCMsgScopeCall: ...

    def release_scope_ref(self, ref: HandleRef) -> None: ...


class AsyncHandleClient(Protocol):
    async def enumerate_props_async(self, refs: HandleRef | list[HandleRef]) -> RPCMsgEnumerateObjProps: ...

    async def get_value_async(self, ref: HandleRef) -> Any: ...

    async def call_async(self, ref: HandleRef, args: tuple[object, ...]) -> RPCMsgScopeCall: ...

    async def release_scope_ref_async(self, ref: HandleRef) -> None: ...


def _safe_scope_del(scope_del, ref: HandleRef) -> None:
    try:
        scope_del(ref)
    except Exception:
        # Handles may outlive the underlying Frida script during REPL/session teardown.
        pass


class Unset:
    def __init__(self, name: str) -> None:
        self.name = name


_UNSET_VALUE = Unset("any")


class _BaseJsHandle:
    __META_PROP__: Final[frozenset[str]] = frozenset()

    def __init__(
        self,
        ref: HandleRef,
        *,
        typ: str = "unknown",
        value: Any = _UNSET_VALUE,
    ) -> None:
        self._ref = ref
        self._typ = typ
        self._value = value

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: [{self._typ}] {self}>"

    def __str__(self) -> str:
        return self._ref.render()

    def __format__(self, format_spec: str) -> str:
        del format_spec
        return self._ref.to_js_expr()

    def __dir__(self) -> tuple[str, ...]:
        names = set(object.__dir__(self))
        names.update(self._props)
        names.update(type(self).__META_PROP__)
        return tuple(sorted(names))

    @property
    def type_(self) -> str:
        return self._typ

    def to_handle_ref(self) -> HandleRef:
        return self._ref


class SyncJsHandle(_BaseJsHandle):
    __META_PROP__: Final[frozenset[str]] = frozenset({"value_", "type_"})

    def __init__(
        self,
        ref: HandleRef,
        *,
        client: SyncHandleClient,
        typ: str = "unknown",
        props: dict[str, Any] | None = None,
        value: Any = _UNSET_VALUE,
        scope_owner: "SyncJsHandle | None" = None,
    ) -> None:
        super().__init__(ref, typ=typ, value=value)
        self._client = client
        self._lock = Lock()
        self._scope_owner = scope_owner
        self._finalizer: weakref.finalize | None = None

        if props is not None:
            self._props = props
        else:
            enumerated = self._client.enumerate_props(ref)
            mapping = enumerated.props[0] if enumerated.props else {}
            self._props = {name: Unset(prop_type) for name, prop_type in mapping.items()}

        if ref.owns_scope_slot:
            self._finalizer = weakref.finalize(
                self,
                functools.partial(_safe_scope_del, self._client.release_scope_ref, ref),
            )

    @classmethod
    def from_seed_path(cls, path: str, *, client: SyncHandleClient) -> "SyncJsHandle":
        return cls(HandleRef.from_seed_path(path), client=client)

    @classmethod
    def from_scope_result(
        cls,
        result: RPCMsgScopeCall | RPCMsgScopeEval,
        *,
        client: SyncHandleClient,
    ) -> "SyncJsHandle":
        value: Any = result.result if result.has_result else Unset(result.type)
        return cls(
            HandleRef.scope(result.id),
            client=client,
            typ=result.type,
            value=value,
        )

    def __call__(self, *args: Any) -> "SyncJsHandle":
        return SyncJsHandle.from_scope_result(self._client.call(self._ref, args), client=self._client)

    @property
    def value_(self) -> Any:
        if isinstance(self._value, Unset):
            self._value = self._client.get_value(self._ref)
        return self._value

    def release(self) -> None:
        if self._finalizer is not None and self._finalizer.alive:
            self._finalizer()
            return
        if self._scope_owner is not None:
            self._scope_owner.release()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return self._get_child(str(name))

    def __getitem__(self, key: Any) -> "SyncJsHandle":
        return self._get_child(str(key))

    def _get_child(self, key: str) -> "SyncJsHandle":
        current = self._props.get(key)
        if current is None:
            current = SyncJsHandle(
                self._ref.child(key),
                client=self._client,
                typ="unknown",
                scope_owner=self._scope_owner_token(),
            )
            self._props[key] = current
            return current
        if isinstance(current, Unset):
            if self._client.interactive:
                self._materialize_pending_children()
                resolved = self._props[key]
                if isinstance(resolved, SyncJsHandle):
                    return resolved
            current = SyncJsHandle(
                self._ref.child(key),
                client=self._client,
                typ=current.name,
                scope_owner=self._scope_owner_token(),
            )
            self._props[key] = current
        assert isinstance(current, SyncJsHandle)
        return current

    def _materialize_pending_children(self) -> None:
        with self._lock:
            pending_handles: list[SyncJsHandle] = []
            owner = self._scope_owner_token()
            for key, value in list(self._props.items()):
                if not isinstance(value, Unset):
                    continue
                handle = SyncJsHandle(
                    self._ref.child(key),
                    client=self._client,
                    typ=value.name,
                    props={},
                    scope_owner=owner,
                )
                self._props[key] = handle
                pending_handles.append(handle)
            if not pending_handles:
                return

            batch = self._client.enumerate_props([handle._ref for handle in pending_handles])
            for handle, mapping in zip(pending_handles, batch.props):
                handle._props.update({name: Unset(prop_type) for name, prop_type in mapping.items()})

    def _scope_owner_token(self) -> "SyncJsHandle | None":
        # Scope children must retain the owning root handle; otherwise a chained
        # temporary like `script.eval("Process").getCurrentThreadId()` releases
        # the remote slot before the child call reaches the agent.
        if self._ref.owns_scope_slot:
            return self
        return self._scope_owner


class AsyncJsHandle(_BaseJsHandle):
    __META_PROP__: Final[frozenset[str]] = frozenset({"type_"})

    def __init__(
        self,
        ref: HandleRef,
        *,
        client: AsyncHandleClient,
        typ: str = "unknown",
        props: dict[str, Any] | None = None,
        value: Any = _UNSET_VALUE,
        scope_owner: "AsyncJsHandle | None" = None,
    ) -> None:
        super().__init__(ref, typ=typ, value=value)
        self._client = client
        self._props = props or {}
        self._scope_owner = scope_owner
        self._released = False
        self._props_lock: asyncio.Lock | None = None

    @classmethod
    def from_seed_path(cls, path: str, *, client: AsyncHandleClient) -> "AsyncJsHandle":
        return cls(HandleRef.from_seed_path(path), client=client, props={})

    @classmethod
    async def from_scope_result_async(
        cls,
        result: RPCMsgScopeCall | RPCMsgScopeEval,
        *,
        client: AsyncHandleClient,
    ) -> "AsyncJsHandle":
        value: Any = result.result if result.has_result else Unset(result.type)
        handle = cls(
            HandleRef.scope(result.id),
            client=client,
            typ=result.type,
            value=value,
            props={},
        )
        await handle._refresh_props_async()
        return handle

    async def call_async(self, *args: Any) -> "AsyncJsHandle":
        return await AsyncJsHandle.from_scope_result_async(
            await self._client.call_async(self._ref, args),
            client=self._client,
        )

    async def resolve_async(self) -> Any:
        if isinstance(self._value, Unset):
            self._value = await self._client.get_value_async(self._ref)
        return self._value

    async def resolve_path_async(self, path: str | None) -> "AsyncJsHandle":
        target = self
        if not path:
            return target
        for segment in path.split("."):
            clean = segment.strip()
            if not clean:
                continue
            target = await target._get_child_async(clean)
        return target

    async def release_async(self) -> None:
        if self._released:
            return
        if self._ref.owns_scope_slot:
            self._released = True
            await self._client.release_scope_ref_async(self._ref)
            return
        if self._scope_owner is not None:
            await self._scope_owner.release_async()

    async def _get_child_async(self, key: str) -> "AsyncJsHandle":
        current = self._props.get(key)
        if current is None:
            current = AsyncJsHandle(
                self._ref.child(key),
                client=self._client,
                typ="unknown",
                props={},
                scope_owner=self._scope_owner_token(),
            )
            self._props[key] = current
            await current._refresh_props_async()
            return current
        if isinstance(current, Unset):
            current = AsyncJsHandle(
                self._ref.child(key),
                client=self._client,
                typ=current.name,
                props={},
                scope_owner=self._scope_owner_token(),
            )
            self._props[key] = current
            await current._refresh_props_async()
        assert isinstance(current, AsyncJsHandle)
        return current

    async def _refresh_props_async(self) -> None:
        if self._props_lock is None:
            self._props_lock = asyncio.Lock()
        async with self._props_lock:
            batch = await self._client.enumerate_props_async(self._ref)
            mapping = batch.props[0] if batch.props else {}
            self._props.update({name: Unset(prop_type) for name, prop_type in mapping.items()})

    def _scope_owner_token(self) -> "AsyncJsHandle | None":
        # Async handles intentionally avoid GC-triggered release because the
        # cleanup path must stay on the owning event loop.
        if self._ref.owns_scope_slot:
            return self
        return self._scope_owner
