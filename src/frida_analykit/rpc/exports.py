from __future__ import annotations

import asyncio
import concurrent.futures
import re
import weakref
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Final, Protocol, TypeAlias

from .message import RPCMessage, RPCPayload

CAMEL_TO_SNAKE: Final[re.Pattern[str]] = re.compile(r"([A-Z])")
ArgumentSerializer: TypeAlias = Callable[[Any], Any]
ResponseAdapter: TypeAlias = Callable[[Any], Any]
BeforeCallHook: TypeAlias = Callable[[str], None]
AsyncBeforeCallHook: TypeAlias = Callable[[str], Awaitable[None]]


class ScriptExportCapabilityError(RuntimeError):
    """Raised when a script cannot satisfy the requested export capability surface."""


class ScriptLike(Protocol):
    exports_sync: object

    def list_exports_sync(self) -> list[str]: ...


class AsyncScriptLike(ScriptLike, Protocol):
    exports_async: object

    async def list_exports_async(self) -> list[str]: ...


class AsyncExportsBackend(Protocol):
    mode: str
    exports: object

    async def list_exports(self) -> list[str]: ...

    async def call_export(self, name: str, args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any: ...


def _identity_response(value: Any) -> Any:
    return value


def _as_rpc_message(value: Any) -> RPCMessage | None:
    if isinstance(value, RPCMessage):
        return value
    if isinstance(value, Mapping) and "type" in value:
        return RPCMessage.from_mapping(value)
    return None


def make_rpc_response(response: Any) -> Any:
    if isinstance(response, RPCPayload):
        return response

    if isinstance(response, (list, tuple)) and len(response) > 1 and isinstance(response[1], (bytes, bytearray)):
        message = _as_rpc_message(response[0])
        if message is None:
            return response
        return RPCPayload(message=message, data=bytes(response[1]))

    message = _as_rpc_message(response)
    if message is not None:
        return RPCPayload(message=message)
    return response


def _normalize_export_names(names: Sequence[str]) -> list[str]:
    return [_jsname_to_pyname(name) for name in names]


def _missing_exports(
    exports: object,
    export_names: Sequence[str],
    *,
    required: Sequence[str],
) -> list[str]:
    available = set(export_names)
    missing: list[str] = []
    for name in required:
        if name not in available or not callable(getattr(exports, name, None)):
            missing.append(name)
    return missing


class ScriptExportsSyncWrapper:
    def __init__(
        self,
        script: ScriptLike,
        *,
        serializer: ArgumentSerializer | None = None,
        response_adapter: ResponseAdapter | None = None,
        before_call: BeforeCallHook | None = None,
    ) -> None:
        self._script = script
        self._exports = script.exports_sync
        self._serializer = serializer or (lambda value: value)
        self._response_adapter = response_adapter or _identity_response
        self._before_call = before_call

    def _list_exports(self) -> list[str]:
        return _normalize_export_names(self._script.list_exports_sync())

    def __getattr__(self, name: str) -> "ScriptCallWrapper":
        return ScriptCallWrapper(
            self._exports,
            name,
            serializer=self._serializer,
            response_adapter=self._response_adapter,
            before_call=self._before_call,
        )

    def __dir__(self) -> list[str]:
        return self._list_exports()


class NativeAsyncExportsBackend:
    mode: Final[str] = "native"

    def __init__(self, script: AsyncScriptLike) -> None:
        self._script = script
        self.exports = script.exports_async

    async def list_exports(self) -> list[str]:
        return _normalize_export_names(await self._script.list_exports_async())

    async def call_export(self, name: str, args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any:
        return await getattr(self.exports, name)(*args, **dict(kwargs))


class ShimAsyncExportsBackend:
    mode: Final[str] = "shim"

    def __init__(
        self,
        script: ScriptLike,
        *,
        name_map: Mapping[str, str] | None = None,
    ) -> None:
        self._script = script
        self.exports = script.exports_sync
        self._name_map = dict(name_map or {})
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="frida-analykit-rpc-shim",
        )
        self._finalizer = weakref.finalize(
            self,
            lambda executor: executor.shutdown(wait=False, cancel_futures=True),
            self._executor,
        )

    async def list_exports(self) -> list[str]:
        return _normalize_export_names(await self._run_sync(self._script.list_exports_sync))

    async def call_export(self, name: str, args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any:
        method_name = self._name_map.get(name, name)
        return await self._run_sync(getattr(self.exports, method_name), *args, **dict(kwargs))

    async def _run_sync(self, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: func(*args, **kwargs),
        )


class ScriptExportsAsyncWrapper:
    def __init__(
        self,
        script: ScriptLike,
        *,
        serializer: ArgumentSerializer | None = None,
        response_adapter: ResponseAdapter | None = None,
        before_call: AsyncBeforeCallHook | None = None,
        required_native_exports: Sequence[str] | None = None,
        required_sync_exports: Sequence[str] | None = None,
        shim_name_map: Mapping[str, str] | None = None,
    ) -> None:
        self._script = script
        self._serializer = serializer or (lambda value: value)
        self._response_adapter = response_adapter or _identity_response
        self._before_call = before_call
        self._required_native_exports = tuple(required_native_exports or ())
        self._required_sync_exports = tuple(required_sync_exports or ())
        self._shim_name_map = dict(shim_name_map or {})
        self._backend: AsyncExportsBackend | None = None
        self._backend_lock: asyncio.Lock | None = None
        self._exports: object | None = None
        self._backend_mode: str | None = None

    @property
    def backend_mode(self) -> str | None:
        return self._backend_mode

    async def _list_exports(self) -> list[str]:
        backend = await self._ensure_backend()
        return await backend.list_exports()

    def __getattr__(self, name: str) -> "ScriptCallAsyncWrapper":
        return ScriptCallAsyncWrapper(
            self,
            name,
            serializer=self._serializer,
            response_adapter=self._response_adapter,
            before_call=self._before_call,
        )

    def __dir__(self) -> list[str]:
        list_exports_sync = getattr(self._script, "list_exports_sync", None)
        if not callable(list_exports_sync):
            return []
        return _normalize_export_names(list_exports_sync())

    async def _call_export(self, name: str, args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any:
        backend = await self._ensure_backend()
        return await backend.call_export(name, args, kwargs)

    async def _ensure_backend(self) -> AsyncExportsBackend:
        if self._backend is not None:
            return self._backend

        if self._backend_lock is None:
            self._backend_lock = asyncio.Lock()

        async with self._backend_lock:
            if self._backend is not None:
                return self._backend

            native_probe = await self._probe_native_backend()
            if native_probe is not None:
                self._backend = native_probe
                self._exports = native_probe.exports
                self._backend_mode = native_probe.mode
                return native_probe

            shim_probe = self._probe_shim_backend()
            self._backend = shim_probe
            self._exports = shim_probe.exports
            self._backend_mode = shim_probe.mode
            return shim_probe

    async def _probe_native_backend(self) -> NativeAsyncExportsBackend | None:
        list_exports_async = getattr(self._script, "list_exports_async", None)
        exports_async = getattr(self._script, "exports_async", None)
        if not callable(list_exports_async) or exports_async is None:
            return None

        export_names = _normalize_export_names(await list_exports_async())
        missing = _missing_exports(
            exports_async,
            export_names,
            required=self._required_native_exports,
        )
        if missing:
            return None
        return NativeAsyncExportsBackend(self._script)

    def _probe_shim_backend(self) -> ShimAsyncExportsBackend:
        list_exports_sync = getattr(self._script, "list_exports_sync", None)
        exports_sync = getattr(self._script, "exports_sync", None)
        if not callable(list_exports_sync) or exports_sync is None:
            raise ScriptExportCapabilityError(
                "script does not expose a usable sync export surface for async shim fallback"
            )

        export_names = _normalize_export_names(list_exports_sync())
        required_sync_exports = self._required_sync_exports or tuple(
            self._shim_name_map.get(name, name) for name in self._required_native_exports
        )
        missing = _missing_exports(
            exports_sync,
            export_names,
            required=required_sync_exports,
        )
        if missing:
            native_required = ", ".join(self._required_native_exports) or "<none>"
            sync_required = ", ".join(missing)
            raise ScriptExportCapabilityError(
                "script async capability probe failed; native async exports are unavailable or incomplete "
                f"(required async exports: {native_required}). Sync shim fallback is also missing: {sync_required}"
            )
        return ShimAsyncExportsBackend(self._script, name_map=self._shim_name_map)


class ScriptCallWrapper:
    def __init__(
        self,
        exports: object,
        name: str,
        *,
        serializer: ArgumentSerializer,
        response_adapter: ResponseAdapter,
        before_call: BeforeCallHook | None = None,
    ) -> None:
        self._exports = exports
        self._name = name
        self._serializer = serializer
        self._response_adapter = response_adapter
        self._before_call = before_call

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._before_call is not None:
            self._before_call(self._name)
        serialized_args = tuple(self._serializer(item) for item in args)
        serialized_kwargs = {key: self._serializer(value) for key, value in kwargs.items()}
        response = getattr(self._exports, self._name)(*serialized_args, **serialized_kwargs)
        return self._response_adapter(response)


class ScriptCallAsyncWrapper:
    def __init__(
        self,
        exports: ScriptExportsAsyncWrapper,
        name: str,
        *,
        serializer: ArgumentSerializer,
        response_adapter: ResponseAdapter,
        before_call: AsyncBeforeCallHook | None = None,
    ) -> None:
        self._exports = exports
        self._name = name
        self._serializer = serializer
        self._response_adapter = response_adapter
        self._before_call = before_call

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._before_call is not None:
            await self._before_call(self._name)
        serialized_args = tuple(self._serializer(item) for item in args)
        serialized_kwargs = {key: self._serializer(value) for key, value in kwargs.items()}
        response = await self._exports._call_export(self._name, serialized_args, serialized_kwargs)
        return self._response_adapter(response)


def _jsname_to_pyname(name: str) -> str:
    return CAMEL_TO_SNAKE.sub(lambda match: "_" + match.group(1).lower(), name)
