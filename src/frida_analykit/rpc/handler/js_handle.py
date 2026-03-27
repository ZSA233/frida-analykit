from __future__ import annotations

import functools
import json
import os
import weakref
from threading import Lock
from typing import TYPE_CHECKING, Any, Final

from ..message import RPCMsgEnumerateObjProps, RPCMsgScopeCall, RPCMsgScopeEval, RPCMsgScopeGet, RPCPayload

if TYPE_CHECKING:
    from ...session import ScriptWrapper


_default_jsonenc = json.JSONEncoder.default


def _patched(self, obj):
    if isinstance(obj, JsHandle):
        return str(obj)
    return _default_jsonenc(self, obj)


json.JSONEncoder.default = _patched
REPL = os.environ.get("REPL", False)
_SCOPE_GET_PREFIX = "__get__$$"


def _safe_scope_del(scope_del, inst_id: str, scope_id: str) -> None:
    try:
        scope_del(inst_id, scope_id)
    except Exception:
        # Handles may outlive the underlying Frida script during REPL/session teardown.
        pass


class Unset:
    def __init__(self, name: str) -> None:
        self.name = name


class JsHandle:
    __INTERNAL_PROP__: Final[frozenset[str]] = frozenset(
        {"_JsHandle" + value for value in ("__path", "__parent", "__script", "__props", "__typ", "__scope_id", "__inst_id", "__value", "__lock")}
    )
    __LATER_PROP__: Final[frozenset[str]] = frozenset({"value", "type"})

    @staticmethod
    def _render_path(path: str, parent: "JsHandle" | None, inst_id: str | None) -> str:
        if parent is None:
            return path
        if inst_id is not None and inst_id.startswith(_SCOPE_GET_PREFIX):
            return inst_id
        return f"{str(parent)}/{path}"

    def __init__(
        self,
        path: str,
        parent: "JsHandle" | None = None,
        *,
        script: "ScriptWrapper",
        typ: str = "unknown",
        scope_id: str = "",
        inst_id: str | bool | None = None,
        props: dict[str, Any] | None = None,
        value: Any = Unset("any"),
    ) -> None:
        self.__parent = parent
        self.__path = path
        self.__script = script
        self.__typ = typ
        self.__scope_id = scope_id
        self.__value = value
        self.__lock = Lock()
        if isinstance(inst_id, str):
            resolved_id = inst_id
        elif inst_id is True:
            resolved_id = f"{_SCOPE_GET_PREFIX}{hex(id(self))}"
        elif inst_id is None:
            resolved_id = JsHandle._render_path(path, parent, None)
        else:  # pragma: no cover - defensive
            raise TypeError(f"unexpected type of {type(inst_id)!r}")
        self.__inst_id = resolved_id

        if props is not None:
            self.__props = props
        else:
            enumerated = self.__script.exports_sync.enumerate_obj_props(resolved_id, scope_id).message.data
            assert isinstance(enumerated, RPCMsgEnumerateObjProps)
            self.__props = {name: Unset(prop_type) for name, prop_type in enumerated.props[0].items()}

        weakref.finalize(
            self,
            functools.partial(_safe_scope_del, self.__script.exports_sync.scope_del, resolved_id, scope_id),
        )

    def __repr__(self) -> str:
        return f"<JsHandle: [{self.__typ}] {self}>"

    def __str__(self) -> str:
        return JsHandle._render_path(self.__path, self.__parent, self.__inst_id)

    def __dir__(self):
        return tuple(self.__props) + tuple(JsHandle.__LATER_PROP__)

    def __call__(self, *args):
        converted = []
        for item in args:
            if isinstance(item, JsHandle):
                handle_id = item._JsHandle__inst_id
                if not handle_id.startswith(_SCOPE_GET_PREFIX):
                    handle_id = _SCOPE_GET_PREFIX + handle_id
                converted.append(handle_id)
            else:
                converted.append(item)
        message = self.__script.exports_sync.scope_call(self.__inst_id, converted, self.__scope_id).message
        data = message.data
        assert isinstance(data, RPCMsgScopeCall)
        return JsHandle(
            data.id,
            self,
            script=self.__script,
            typ=data.type,
            scope_id=self.__scope_id,
            inst_id=data.id,
            value=data.result,
        )

    def __format__(self, format_spec: str) -> str:
        del format_spec
        inst_id = self.__inst_id
        if not inst_id.startswith(_SCOPE_GET_PREFIX):
            inst_id = _SCOPE_GET_PREFIX + inst_id
        return inst_id

    @classmethod
    def new_from_payload(cls, payload: RPCPayload, script: "ScriptWrapper", scope_id: str):
        data = payload.message.data
        assert isinstance(data, (RPCMsgScopeCall, RPCMsgScopeEval))
        return cls(
            data.id,
            None,
            script=script,
            scope_id=scope_id,
            typ=data.type,
            inst_id=data.id,
            value=data.result,
        )

    @property
    def value(self):
        if isinstance(self.__value, Unset):
            result = self.__script.exports_sync.scope_get(self.__inst_id, self.__scope_id).message.data
            assert isinstance(result, RPCMsgScopeGet)
            self.__value = result.value
        return self.__value

    @property
    def type(self) -> str:
        return self.__typ

    def __getattribute__(self, name: str):
        if name.startswith("__") or name in JsHandle.__INTERNAL_PROP__:
            return object.__getattribute__(self, name)
        props = self.__props
        current = props.get(name)
        if current is None:
            if name in JsHandle.__LATER_PROP__:
                return object.__getattribute__(self, name)
            current = JsHandle(name, self, script=self.__script, typ="unknown", scope_id=self.__scope_id, inst_id=None)
            props[name] = current
        if isinstance(current, Unset):
            if REPL:
                with self.__lock:
                    pending_ids: list[str] = []
                    pending_props: dict[str, dict[str, Any]] = {}
                    for key, value in list(props.items()):
                        if not isinstance(value, Unset):
                            continue
                        child_props: dict[str, Any] = {}
                        handle = JsHandle(
                            key,
                            self,
                            script=self.__script,
                            typ=value.name,
                            scope_id=self.__scope_id,
                            inst_id=None,
                            props=child_props,
                        )
                        props[key] = handle
                        pending_ids.append(handle._JsHandle__inst_id)
                        pending_props[handle._JsHandle__inst_id] = child_props
                batch_result = self.__script.exports_sync.enumerate_obj_props(pending_ids, self.__scope_id).message.data
                assert isinstance(batch_result, RPCMsgEnumerateObjProps)
                for key, mapping in zip(pending_ids, batch_result.props):
                    pending_props[key].update({prop: Unset(prop_type) for prop, prop_type in mapping.items()})
                current = props[name]
            else:
                current = JsHandle(name, self, script=self.__script, typ=current.name, scope_id=self.__scope_id, inst_id=None)
                props[name] = current
        return current

    def __getitem__(self, key):
        return self.__getattribute__(str(key))
