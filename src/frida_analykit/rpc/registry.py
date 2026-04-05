from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, TextIO

import colorama

from ..config import AppConfig
from ..utils import ensure_filepath
from .handler.dex import DexDumpHandler
from .handler.elf import ElfHandler
from .handler.net import NetHandler
from .handler.runtime import RuntimeHandler
from .message import RPCBatchSource, RPCMsgType, RPCPayload, unpack_batch_payload


MessageHandler = Callable[[RPCPayload], None]
ExceptionHandler = Callable[[dict, bytes | None], None]
HostLogHandler = Callable[[str, str], None]


class HandlerRegistry:
    def __init__(
        self,
        config: AppConfig,
        stdout: TextIO,
        stderr: TextIO,
        log_sink: HostLogHandler | None = None,
    ) -> None:
        self._config = config
        self._stdout = stdout
        self._stderr = stderr
        self._log_sink = log_sink
        self._message_handlers: dict[str, MessageHandler] = {}
        self._batch_handlers: dict[str, MessageHandler] = {}
        self._exception_handler: ExceptionHandler = self._default_exception_handler
        self._dex_handler = DexDumpHandler(config, emit_info=self._emit_info, emit_error=self._emit_error)
        self._elf_handler = ElfHandler(config, emit_info=self._emit_info, emit_error=self._emit_error)
        self._net_handler = NetHandler(config, emit_info=self._emit_info, emit_error=self._emit_error)
        self._runtime_handler = RuntimeHandler(emit_info=self._emit_info, emit_error=self._emit_error)
        self._register_defaults()

    def set_log_sink(self, log_sink: HostLogHandler | None) -> None:
        self._log_sink = log_sink

    def on_message(self, msg_type: RPCMsgType | str, func: MessageHandler | None = None):
        key = msg_type.value if isinstance(msg_type, RPCMsgType) else str(msg_type)
        if func is not None:
            self._message_handlers[key] = func
            return func

        def wrapper(callback: MessageHandler) -> MessageHandler:
            self._message_handlers[key] = callback
            return callback

        return wrapper

    def on_batch(self, source: RPCBatchSource | str, func: MessageHandler | None = None):
        key = source.value if isinstance(source, RPCBatchSource) else str(source)
        if func is not None:
            self._batch_handlers[key] = func
            return func

        def wrapper(callback: MessageHandler) -> MessageHandler:
            self._batch_handlers[key] = callback
            return callback

        return wrapper

    def on_exception(self, func: ExceptionHandler) -> ExceptionHandler:
        self._exception_handler = func
        return func

    def handle(self, payload: RPCPayload) -> None:
        if payload.message.type == RPCMsgType.BATCH:
            handler = self._batch_handlers.get(payload.message.source or "", self._default_batch_handler)
            handler(payload)
            return
        handler = self._message_handlers.get(payload.message.type.value, self._default_message_handler)
        handler(payload)

    def handle_exception(self, message: dict, data: bytes | None) -> None:
        self._exception_handler(message, data)

    def _register_defaults(self) -> None:
        self.on_message(RPCMsgType.PROGRESSING, self._runtime_handler.handle_progressing)
        self.on_message(RPCMsgType.SSL_SECRET, self._net_handler.handle_ssl_secret)
        self.on_message(RPCMsgType.DEX_DUMP_BEGIN, self._dex_handler.handle_begin)
        self.on_message(RPCMsgType.DUMP_DEX_FILE, self._dex_handler.handle_file)
        self.on_message(RPCMsgType.DEX_DUMP_END, self._dex_handler.handle_end)
        self.on_batch(RPCBatchSource.DEX_DUMP_FILES, self._dex_handler.handle_batch)
        self.on_message(RPCMsgType.ELF_MODULE_DUMP_BEGIN, self._elf_handler.handle_dump_begin)
        self.on_message(RPCMsgType.ELF_MODULE_DUMP_CHUNK, self._elf_handler.handle_dump_chunk)
        self.on_message(RPCMsgType.ELF_MODULE_DUMP_END, self._elf_handler.handle_dump_end)
        self.on_message(RPCMsgType.ELF_SYMBOL_CALL_LOG, self._elf_handler.handle_symbol_log)
        self.on_batch(RPCBatchSource.ELF_MODULE_DUMP_CHUNKS, self._elf_handler.handle_dump_batch)

    def _default_exception_handler(self, message: dict, data: bytes | None) -> None:
        del data
        description = message.get("description")
        stack = message.get("stack")
        file_name = message.get("fileName")
        line = message.get("lineNumber")
        column = message.get("columnNumber")

        if not any(value is not None for value in (description, stack, file_name, line, column)):
            self._emit_error(json.dumps(message, ensure_ascii=False))
            return

        if file_name:
            location = str(file_name)
            if line is not None:
                location = f"{location}:{line}"
                if column is not None:
                    location = f"{location}:{column}"
            self._emit_error(f"[script-error] {location}")

        if description:
            self._emit_error(f"[script-error] {description}")

        if stack:
            self._emit_error(stack)

    def _default_batch_handler(self, payload: RPCPayload) -> None:
        for item in unpack_batch_payload(payload):
            self.handle(item)

    def _default_message_handler(self, payload: RPCPayload) -> None:
        suffix = datetime.now().strftime("%Y%m%d%H%M%S%f")
        self._emit_info(
            f"{colorama.Fore.MAGENTA}[{payload.message.type.value}]{suffix} "
            f"{payload.message.data.model_dump_json()}{colorama.Fore.RESET}"
        )

        if not payload.data:
            return
        filename = f"{payload.message.type.value}_{suffix}"
        if self._config.agent.datadir:
            path = ensure_filepath(self._config.agent.datadir / filename)
            with open(path, "wb") as handle:
                handle.write(payload.data)
            self._emit_info(f"{colorama.Fore.GREEN}[{path}] {len(payload.data)}{colorama.Fore.RESET}")
            return
        self._emit_error(f"{colorama.Fore.MAGENTA}[{filename}] {len(payload.data)} <drop>{colorama.Fore.RESET}")

    def _emit(self, level: str, text: str, stream: TextIO) -> None:
        print(text, file=stream)
        if self._log_sink is not None:
            self._log_sink(level, text)

    def _emit_info(self, text: str) -> None:
        self._emit("info", text, self._stdout)

    def _emit_error(self, text: str) -> None:
        self._emit("error", text, self._stderr)
