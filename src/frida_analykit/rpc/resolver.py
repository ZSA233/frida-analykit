from __future__ import annotations

from typing import Any

from frida.core import Script, ScriptErrorMessage, ScriptMessage

from .message import RPCMessage, RPCPayload
from .registry import HandlerRegistry


class RPCResolver:
    def __init__(self, registry: HandlerRegistry) -> None:
        self._registry = registry
        self._scripts: set[Script] = set()

    def register_script(self, script: Script) -> None:
        if script in self._scripts:
            return
        script.on("message", self._on_message_handler)
        self._scripts.add(script)

    def _on_message_handler(self, message: ScriptMessage, data: bytes | None) -> None:
        if message["type"] == "send":
            payload = RPCPayload(message=RPCMessage.from_mapping(message.get("payload", {})), data=data)
            self._registry.handle(payload)
            return
        if message["type"] == "error":
            self._registry.handle_exception(message, data)
