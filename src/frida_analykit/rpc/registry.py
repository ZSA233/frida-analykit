from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

import colorama

from ..config import AppConfig
from ..utils import ensure_filepath
from .handler.output_paths import resolve_configured_output_root, resolve_output_leaf
from .handler.dex import DexDumpHandler
from .handler.elf import ElfHandler
from .message import RPCBatchSource, RPCMsgBatch, RPCMsgProgressing, RPCMsgSSLSecret, RPCMsgType, RPCPayload, unpack_batch_payload


MessageHandler = Callable[[RPCPayload], None]
ExceptionHandler = Callable[[dict, bytes | None], None]
HostLogHandler = Callable[[str, str], None]


@dataclass(slots=True)
class SSLSecretOutputState:
    directory: Path
    logger: TextIO
    tag: str
    effective_tag: str
    actual_relative_dir: str
    configured_output_root: str


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
        self._ssl_secret_outputs: dict[str, SSLSecretOutputState] = {}
        self._dex_handler = DexDumpHandler(config, emit_info=self._emit_info, emit_error=self._emit_error)
        self._elf_handler = ElfHandler(config, emit_info=self._emit_info, emit_error=self._emit_error)
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
        self.on_message(RPCMsgType.PROGRESSING, self._handle_progressing)
        self.on_message(RPCMsgType.SSL_SECRET, self._handle_ssl_secret)
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

    def _handle_progressing(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgProgressing)
        if data.error:
            self._emit_error(f"[x] | {data.tag} | {data.step} => {data.error}")
            return
        intro = data.extra.get("intro", ",".join(data.extra.keys()))
        self._emit_info(f"[~] | {data.tag} | {data.step} => {intro}")

    def _ssl_secret_output(self, tag: str) -> SSLSecretOutputState:
        root = resolve_configured_output_root(
            configured_root=self._config.script.nettools.output_dir,
            agent_datadir=self._config.agent.datadir,
            fallback_child="nettools",
            missing_message="script.nettools.output_dir or agent.datadir is required for SSL_SECRET handling",
        )
        output_leaf = resolve_output_leaf(root, tag)
        key = output_leaf.relative_dir or "__root__"
        if key not in self._ssl_secret_outputs:
            output_leaf.directory.mkdir(parents=True, exist_ok=True)
            log_path = output_leaf.directory / "sslkey.log"
            logger = open(log_path, "a", buffering=1, encoding="utf-8")
            state = SSLSecretOutputState(
                directory=output_leaf.directory,
                logger=logger,
                tag=output_leaf.tag,
                effective_tag=output_leaf.effective_tag,
                actual_relative_dir=output_leaf.relative_dir,
                configured_output_root=str(output_leaf.root),
            )
            self._write_ssl_secret_manifest(state)
            self._ssl_secret_outputs[key] = state
        return self._ssl_secret_outputs[key]

    @staticmethod
    def _write_ssl_secret_manifest(state: SSLSecretOutputState) -> None:
        manifest_path = state.directory / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "created_at_ms": int(time.time() * 1000),
                    "mode": "rpc",
                    "tag": state.tag,
                    "effective_tag": state.effective_tag,
                    "configured_output_root": state.configured_output_root,
                    "actual_relative_dir": state.actual_relative_dir,
                    "output_name": "sslkey.log",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _handle_ssl_secret(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgSSLSecret)
        output = self._ssl_secret_output(data.tag)
        print(f"{data.label} {data.client_random} {data.secret}", file=output.logger)

    def _emit(self, level: str, text: str, stream: TextIO) -> None:
        print(text, file=stream)
        if self._log_sink is not None:
            self._log_sink(level, text)

    def _emit_info(self, text: str) -> None:
        self._emit("info", text, self._stdout)

    def _emit_error(self, text: str) -> None:
        self._emit("error", text, self._stderr)
