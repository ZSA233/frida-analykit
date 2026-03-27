from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from frida.core import Script

from .message import RPCMessage, RPCPayload

CAMEL_TO_SNAKE: Final[re.Pattern[str]] = re.compile(r"([A-Z])")


def _as_rpc_message(value):
    if isinstance(value, RPCMessage):
        return value
    if isinstance(value, Mapping) and "type" in value:
        return RPCMessage.from_mapping(value)
    return None


def make_rpc_response(response):
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
    __EXPORT__: Final[frozenset[str]] = frozenset(
        {
            "_list_exports",
            "_ScriptExportsSyncWrapper__script",
            "_ScriptExportsSyncWrapper__jsname2pyname",
            "_ScriptExportsSyncWrapper__EXPORT__",
        }
    )

    def __init__(self, script: Script) -> None:
        self.__script = script

    def _list_exports(self) -> list[str]:
        return [self.__jsname2pyname(name) for name in self.__script.list_exports_sync()]

    @staticmethod
    def __jsname2pyname(name: str) -> str:
        return CAMEL_TO_SNAKE.sub(lambda match: "_" + match.group(1).lower(), name)

    def __getattribute__(self, name: str):
        if name in ScriptExportsSyncWrapper.__EXPORT__:
            return object.__getattribute__(self, name)
        return ScriptCallWrapper(self.__script, name)

    def __dir__(self):
        return self._list_exports()


class ScriptCallWrapper:
    def __init__(self, script: Script, name: str) -> None:
        self.__script = script
        self.__name = name

    def __call__(self, *args, **kwargs):
        response = getattr(self.__script.exports_sync, self.__name)(*args, **kwargs)
        return make_rpc_response(response)
