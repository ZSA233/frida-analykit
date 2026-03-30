from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

import colorama

from ..config import AppConfig
from ..utils import ensure_filepath
from .handler.dex import DexDumpHandler
from .message import RPCBatchSource, RPCMsgBatch, RPCMsgProgressing, RPCMsgSSLSecret, RPCMsgType, RPCPayload, unpack_batch_payload


MessageHandler = Callable[[RPCPayload], None]
ExceptionHandler = Callable[[dict, bytes | None], None]


class HandlerRegistry:
    def __init__(self, config: AppConfig, stdout: TextIO, stderr: TextIO) -> None:
        self._config = config
        self._stdout = stdout
        self._stderr = stderr
        self._message_handlers: dict[str, MessageHandler] = {}
        self._batch_handlers: dict[str, MessageHandler] = {}
        self._exception_handler: ExceptionHandler = self._default_exception_handler
        self._ssl_secret_loggers: dict[str, TextIO] = {}
        self._dex_handler = DexDumpHandler(config, stdout, stderr)
        self._register_defaults()

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
        self.on_message(RPCMsgType.PROGRESSING, self._handle_progressing)
        self.on_message(RPCMsgType.SSL_SECRET, self._handle_ssl_secret)
        self.on_message(RPCMsgType.DEX_DUMP_BEGIN, self._dex_handler.handle_begin)
        self.on_message(RPCMsgType.DUMP_DEX_FILE, self._dex_handler.handle_file)
        self.on_message(RPCMsgType.DEX_DUMP_END, self._dex_handler.handle_end)
        self.on_batch(RPCBatchSource.DEX_DUMP_FILES, self._dex_handler.handle_batch)

    def _default_exception_handler(self, message: dict, data: bytes | None) -> None:
        del data
        description = message.get("description")
        stack = message.get("stack")
        file_name = message.get("fileName")
        line = message.get("lineNumber")
        column = message.get("columnNumber")

        if not any(value is not None for value in (description, stack, file_name, line, column)):
            print(json.dumps(message, ensure_ascii=False), file=self._stderr)
            return

        if file_name:
            location = str(file_name)
            if line is not None:
                location = f"{location}:{line}"
                if column is not None:
                    location = f"{location}:{column}"
            print(f"[script-error] {location}", file=self._stderr)

        if description:
            print(f"[script-error] {description}", file=self._stderr)

        if stack:
            print(stack, file=self._stderr)

    def _default_batch_handler(self, payload: RPCPayload) -> None:
        for item in unpack_batch_payload(payload):
            self.handle(item)

    def _default_message_handler(self, payload: RPCPayload) -> None:
        suffix = datetime.now().strftime("%Y%m%d%H%M%S%f")
        print(
            f"{colorama.Fore.MAGENTA}[{payload.message.type.value}]{suffix} "
            f"{payload.message.data.model_dump_json()}{colorama.Fore.RESET}",
            file=self._stdout,
        )

        if not payload.data:
            return
        filename = f"{payload.message.type.value}_{suffix}"
        if self._config.agent.datadir:
            path = ensure_filepath(self._config.agent.datadir / filename)
            with open(path, "wb") as handle:
                handle.write(payload.data)
            print(
                f"{colorama.Fore.GREEN}[{path}] {len(payload.data)}{colorama.Fore.RESET}",
                file=self._stdout,
            )
            return
        print(
            f"{colorama.Fore.MAGENTA}[{filename}] {len(payload.data)} <drop>{colorama.Fore.RESET}",
            file=self._stderr,
        )

    def _handle_progressing(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgProgressing)
        if data.error:
            print(f"[x] | {data.tag} | {data.step} => {data.error}", file=self._stderr)
            return
        intro = data.extra.get("intro", ",".join(data.extra.keys()))
        print(f"[~] | {data.tag} | {data.step} => {intro}", file=self._stdout)

    def _ssl_secret_logger(self, tag: str) -> TextIO:
        safe_tag = Path(tag or "sslkey.log").name
        if safe_tag not in self._ssl_secret_loggers:
            base_dir = self._config.script.nettools.ssl_log_secret
            if base_dir is None:
                raise RuntimeError("script.nettools.ssl_log_secret is required for SSL_SECRET handling")
            path = ensure_filepath(base_dir / safe_tag)
            self._ssl_secret_loggers[safe_tag] = open(path, "a", buffering=1, encoding="utf-8")
        return self._ssl_secret_loggers[safe_tag]

    def _handle_ssl_secret(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgSSLSecret)
        logger = self._ssl_secret_logger(data.tag)
        print(f"{data.label} {data.client_random} {data.secret}", file=logger)
