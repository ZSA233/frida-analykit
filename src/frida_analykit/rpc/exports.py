from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final, TypeAlias

from frida.core import Script, ScriptExportsAsync, ScriptExportsSync

from .message import RPCMessage, RPCPayload

CAMEL_TO_SNAKE: Final[re.Pattern[str]] = re.compile(r"([A-Z])")
ArgumentSerializer: TypeAlias = Callable[[Any], Any]
ResponseAdapter: TypeAlias = Callable[[Any], Any]
BeforeCallHook: TypeAlias = Callable[[str], None]
AsyncBeforeCallHook: TypeAlias = Callable[[str], Awaitable[None]]


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


class ScriptExportsSyncWrapper:
    def __init__(
        self,
        script: Script,
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
        return [_jsname_to_pyname(name) for name in self._script.list_exports_sync()]

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


class ScriptExportsAsyncWrapper:
    def __init__(
        self,
        script: Script,
        *,
        serializer: ArgumentSerializer | None = None,
        response_adapter: ResponseAdapter | None = None,
        before_call: AsyncBeforeCallHook | None = None,
    ) -> None:
        self._script = script
        self._exports = script.exports_async
        self._serializer = serializer or (lambda value: value)
        self._response_adapter = response_adapter or _identity_response
        self._before_call = before_call

    async def _list_exports(self) -> list[str]:
        return [_jsname_to_pyname(name) for name in await self._script.list_exports_async()]

    def __getattr__(self, name: str) -> "ScriptCallAsyncWrapper":
        return ScriptCallAsyncWrapper(
            self._exports,
            name,
            serializer=self._serializer,
            response_adapter=self._response_adapter,
            before_call=self._before_call,
        )

    def __dir__(self) -> list[str]:
        return [_jsname_to_pyname(name) for name in self._script.list_exports_sync()]


class ScriptCallWrapper:
    def __init__(
        self,
        exports: ScriptExportsSync,
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
        serialized = tuple(self._serializer(item) for item in args)
        response = getattr(self._exports, self._name)(*serialized, **kwargs)
        return self._response_adapter(response)


class ScriptCallAsyncWrapper:
    def __init__(
        self,
        exports: ScriptExportsAsync,
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
        serialized = tuple(self._serializer(item) for item in args)
        response = await getattr(self._exports, self._name)(*serialized, **kwargs)
        return self._response_adapter(response)


def _jsname_to_pyname(name: str) -> str:
    return CAMEL_TO_SNAKE.sub(lambda match: "_" + match.group(1).lower(), name)
