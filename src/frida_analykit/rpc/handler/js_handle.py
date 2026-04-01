from __future__ import annotations

import functools
import weakref
from threading import Lock
from typing import Any, Final

from ..client import RPCClient
from ..handle_ref import HandleRef
from ..message import RPCMsgScopeCall, RPCMsgScopeEval


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


class JsHandle:
    __META_PROP__: Final[frozenset[str]] = frozenset({"value_", "type_"})

    def __init__(
        self,
        ref: HandleRef,
        *,
        client: RPCClient,
        typ: str = "unknown",
        props: dict[str, Any] | None = None,
        value: Any = _UNSET_VALUE,
        scope_owner: "JsHandle | None" = None,
    ) -> None:
        self._ref = ref
        self._client = client
        self._typ = typ
        self._value = value
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
    def from_seed_path(cls, path: str, *, client: RPCClient) -> "JsHandle":
        return cls(HandleRef.from_seed_path(path), client=client)

    @classmethod
    def from_scope_result(
        cls,
        result: RPCMsgScopeCall | RPCMsgScopeEval,
        *,
        client: RPCClient,
    ) -> "JsHandle":
        value: Any = result.result if result.has_result else Unset(result.type)
        return cls(
            HandleRef.scope(result.id),
            client=client,
            typ=result.type,
            value=value,
        )

    @classmethod
    async def from_scope_result_async(
        cls,
        result: RPCMsgScopeCall | RPCMsgScopeEval,
        *,
        client: RPCClient,
    ) -> "JsHandle":
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

    def __repr__(self) -> str:
        return f"<JsHandle: [{self._typ}] {self}>"

    def __str__(self) -> str:
        return self._ref.render()

    def __format__(self, format_spec: str) -> str:
        del format_spec
        return self._ref.to_js_expr()

    def __dir__(self) -> tuple[str, ...]:
        names = set(object.__dir__(self))
        names.update(self._props)
        names.update(JsHandle.__META_PROP__)
        return tuple(sorted(names))

    def __call__(self, *args: Any) -> "JsHandle":
        return JsHandle.from_scope_result(self._client.call(self._ref, args), client=self._client)

    async def call_async(self, *args: Any) -> "JsHandle":
        return await JsHandle.from_scope_result_async(await self._client.call_async(self._ref, args), client=self._client)

    @property
    def value_(self) -> Any:
        if isinstance(self._value, Unset):
            self._value = self._client.get_value(self._ref)
        return self._value

    @property
    def type_(self) -> str:
        return self._typ

    async def resolve_async(self) -> Any:
        if isinstance(self._value, Unset):
            self._value = await self._client.get_value_async(self._ref)
        return self._value

    async def resolve_path_async(self, path: str | None) -> "JsHandle":
        target = self
        if not path:
            return target
        for segment in path.split("."):
            clean = segment.strip()
            if not clean:
                continue
            target = await target._get_child_async(clean)
        return target

    def to_handle_ref(self) -> HandleRef:
        return self._ref

    def release(self) -> None:
        if self._finalizer is not None and self._finalizer.alive:
            self._finalizer()
            return
        if self._scope_owner is not None:
            self._scope_owner.release()

    async def release_async(self) -> None:
        if self._finalizer is not None and self._finalizer.alive:
            detached = self._finalizer.detach()
            if detached is not None:
                await self._client.release_scope_ref_async(self._ref)
            return
        if self._scope_owner is not None:
            await self._scope_owner.release_async()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return self._get_child(str(name))

    def __getitem__(self, key: Any) -> "JsHandle":
        return self._get_child(str(key))

    def _get_child(self, key: str) -> "JsHandle":
        current = self._props.get(key)
        if current is None:
            current = JsHandle(
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
                if isinstance(resolved, JsHandle):
                    return resolved
            current = JsHandle(
                self._ref.child(key),
                client=self._client,
                typ=current.name,
                scope_owner=self._scope_owner_token(),
            )
            self._props[key] = current
        assert isinstance(current, JsHandle)
        return current

    def _materialize_pending_children(self) -> None:
        with self._lock:
            pending_handles: list[JsHandle] = []
            owner = self._scope_owner_token()
            for key, value in list(self._props.items()):
                if not isinstance(value, Unset):
                    continue
                handle = JsHandle(
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

    async def _get_child_async(self, key: str) -> "JsHandle":
        current = self._props.get(key)
        if current is None:
            current = JsHandle(
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
            if self._client.interactive:
                await self._materialize_pending_children_async()
                resolved = self._props[key]
                if isinstance(resolved, JsHandle):
                    return resolved
            current = JsHandle(
                self._ref.child(key),
                client=self._client,
                typ=current.name,
                props={},
                scope_owner=self._scope_owner_token(),
            )
            self._props[key] = current
            await current._refresh_props_async()
        assert isinstance(current, JsHandle)
        return current

    async def _materialize_pending_children_async(self) -> None:
        pending_handles: list[JsHandle] = []
        with self._lock:
            owner = self._scope_owner_token()
            for key, value in list(self._props.items()):
                if not isinstance(value, Unset):
                    continue
                handle = JsHandle(
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
        batch = await self._client.enumerate_props_async([handle._ref for handle in pending_handles])
        for handle, mapping in zip(pending_handles, batch.props):
            handle._props.update({name: Unset(prop_type) for name, prop_type in mapping.items()})

    async def _refresh_props_async(self) -> None:
        batch = await self._client.enumerate_props_async(self._ref)
        mapping = batch.props[0] if batch.props else {}
        self._props.update({name: Unset(prop_type) for name, prop_type in mapping.items()})

    def _scope_owner_token(self) -> "JsHandle | None":
        # Scope children must retain the owning root handle; otherwise a chained
        # temporary like `script.eval("Process").getCurrentThreadId()` releases
        # the remote slot before the child call reaches the agent.
        if self._ref.owns_scope_slot:
            return self
        return self._scope_owner
