from __future__ import annotations

from typing import Callable

from ..message import RPCMsgProgressing, RPCPayload


class RuntimeHandler:
    def __init__(
        self,
        *,
        emit_info: Callable[[str], None],
        emit_error: Callable[[str], None],
    ) -> None:
        self._emit_info = emit_info
        self._emit_error = emit_error

    def handle_progressing(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgProgressing)
        if data.error:
            self._emit_error(f"[x] | {data.tag} | {data.step} => {data.error}")
            return
        intro = data.extra.get("intro", ",".join(data.extra.keys()))
        self._emit_info(f"[~] | {data.tag} | {data.step} => {intro}")
