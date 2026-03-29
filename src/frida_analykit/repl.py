from __future__ import annotations

import keyword
from collections.abc import Mapping, Sequence
from typing import Any, Final, Protocol

from .rpc.handler.js_handle import JsHandle

REPL_RESERVED_NAMES: Final[frozenset[str]] = frozenset({"config", "device", "pid", "session", "script"})


class ScriptHandleFactory(Protocol):
    def jsh(self, path: str) -> JsHandle: ...


class LazyJsHandleProxy:
    def __init__(self, script: ScriptHandleFactory, path: str) -> None:
        self._script = script
        self._path = path
        self._handle: JsHandle | None = None

    def _materialize(self) -> JsHandle:
        if self._handle is None:
            self._handle = self._script.jsh(self._path)
        return self._handle

    def __repr__(self) -> str:
        if self._handle is None:
            return f"<LazyJsHandleProxy: {self._path}>"
        return repr(self._handle)

    def __str__(self) -> str:
        if self._handle is None:
            return self._path
        return str(self._handle)

    def __format__(self, format_spec: str) -> str:
        if self._handle is None:
            return format(self._path, format_spec)
        return format(self._handle, format_spec)

    def __dir__(self) -> list[str]:
        return dir(self._materialize())

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._materialize(), name)

    def __getitem__(self, key: Any) -> JsHandle:
        return self._materialize()[key]

    def __call__(self, *args: Any, **kwargs: Any) -> JsHandle:
        if kwargs:
            raise TypeError("REPL lazy handles do not support keyword arguments")
        return self._materialize()(*args)


def _validate_repl_global_name(name: str, *, reserved: set[str], seen: set[str]) -> None:
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(
            f"`script.repl.globals` entry `{name}` must be a valid Python identifier without path separators"
        )
    if name in reserved:
        raise ValueError(f"`script.repl.globals` entry `{name}` conflicts with an existing REPL name")
    if name in seen:
        raise ValueError(f"`script.repl.globals` contains duplicate entry `{name}`")


def build_repl_namespace(
    base_namespace: Mapping[str, object],
    *,
    script: ScriptHandleFactory,
    global_names: Sequence[str],
) -> dict[str, object]:
    namespace = dict(base_namespace)
    reserved = set(namespace)
    reserved.update(REPL_RESERVED_NAMES)
    seen: set[str] = set()

    for name in global_names:
        _validate_repl_global_name(name, reserved=reserved, seen=seen)
        namespace[name] = LazyJsHandleProxy(script, name)
        seen.add(name)

    return namespace
