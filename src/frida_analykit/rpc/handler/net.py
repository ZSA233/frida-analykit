from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from ...config import AppConfig
from .output_paths import resolve_configured_output_root, resolve_output_leaf
from ..message import RPCMsgSSLSecret, RPCPayload


@dataclass(slots=True)
class SSLSecretOutputState:
    directory: Path
    logger: TextIO
    tag: str
    effective_tag: str
    actual_relative_dir: str
    configured_output_root: str


class NetHandler:
    def __init__(
        self,
        config: AppConfig,
        *,
        emit_info: Callable[[str], None],
        emit_error: Callable[[str], None],
    ) -> None:
        self._config = config
        self._emit_info = emit_info
        self._emit_error = emit_error
        self._ssl_secret_outputs: dict[str, SSLSecretOutputState] = {}

    def handle_ssl_secret(self, payload: RPCPayload) -> None:
        data = payload.message.data
        assert isinstance(data, RPCMsgSSLSecret)
        try:
            output = self._ssl_secret_output(data.tag)
        except (OSError, RuntimeError, ValueError) as exc:
            self._emit_error(f"[net] reject SSL_SECRET tag={data.tag!r}: {exc}")
            raise
        print(f"{data.label} {data.client_random} {data.secret}", file=output.logger)

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
            logger = log_path.open("a", buffering=1, encoding="utf-8")
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
            self._emit_info(f"[net] sslkey.log -> {log_path}")
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
