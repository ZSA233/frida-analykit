from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Final, Literal, overload

from frida.core import Script, ScriptExportsAsync, Session, SessionDetachedCallback

from .config import AgentConfig, AppConfig
from .logging import build_loggers
from .rpc.exports import ScriptExportsSyncWrapper
from .rpc.handler.js_handle import JsHandle
from .rpc.message import RPCMessage, RPCMsgInitConfig, RPCPayload
from .rpc.registry import HandlerRegistry
from .rpc.resolver import RPCResolver

RPC_ENV_INJECT_SCRIPT_TEMPLATE: Final[str] = """
const INJECT_ENV = {inject_env};
globalThis.__FRIDA_ANALYKIT_CONFIG__ = {{
    ...(globalThis.__FRIDA_ANALYKIT_CONFIG__ || {{}}),
    ...INJECT_ENV,
}};
import("/index.js");
"""

REG_MAP_SOURCE: Final[re.Pattern[str]] = re.compile(r"^(\d+)\s+(.*?)$", re.MULTILINE)
ScriptEnv = RPCMsgInitConfig


def try_inject_environ(script_src: str, env: dict | None = None) -> str:
    if env is None:
        env = {}
    inject_source = RPC_ENV_INJECT_SCRIPT_TEMPLATE.format(
        inject_env=json.dumps(env, ensure_ascii=False),
    )
    codepos = script_src.find("✄")
    if codepos == -1:
        return script_src
    firstmap = REG_MAP_SOURCE.search(script_src)
    if firstmap is None:
        return script_src
    startpos, _ = firstmap.span()
    return (
        f"{script_src[:startpos]}{len(inject_source)} /__inject__.js\n"
        f"{script_src[startpos:codepos]}✄\n"
        f"{inject_source}\n"
        f"{script_src[codepos:]}"
    )


class ScriptWrapper:
    __SCRIPT_EXPORT__: Final[frozenset[str]] = frozenset(
        {
            "load",
            "unload",
            "eternalize",
            "enable_debugger",
            "disable_debugger",
            "exports_async",
            "list_exports_async",
            "set_log_handler",
        }
    )

    def __init__(self, script: Script, env: ScriptEnv, resolver: RPCResolver) -> None:
        self._script = script
        self._env = env
        self._resolver = resolver
        self._resolver.register_script(script)
        self.exports_sync = ScriptExportsSyncWrapper(script)

    def post(self, message: RPCMessage, data: bytes | None = None) -> None:
        self._script.post(message.to_mapping(), data)

    def __getattribute__(self, name: str):
        if name in ScriptWrapper.__SCRIPT_EXPORT__:
            return getattr(self._script, name)
        return object.__getattribute__(self, name)

    def __dir__(self):
        return tuple(object.__dir__(self)) + tuple(ScriptWrapper.__SCRIPT_EXPORT__)

    def set_logger(self, stdout: Path | None = None, stderr: Path | None = None) -> None:
        loggers = build_loggers(AgentConfig(stdout=stdout, stderr=stderr))

        def handler(level: str, text: str) -> None:
            stream = loggers.stdout if level == "info" else loggers.stderr
            print(text, file=stream)

        self.set_log_handler(handler)

    def list_exports_sync(self) -> list[str]:
        return self.exports_sync._list_exports()

    @property
    def scope_id(self) -> str:
        return hex(id(self))

    def jsh(self, path: str) -> JsHandle:
        return JsHandle(path, script=self, scope_id=self.scope_id)

    def eval(self, source: str) -> JsHandle:
        result = self.exports_sync.scope_eval(source, self.scope_id)
        return JsHandle.new_from_payload(result, script=self, scope_id=self.scope_id)


class SessionWrapper:
    __SESSION_EXPORT__: Final[frozenset[str]] = frozenset(
        {"detach", "resume", "on", "off", "enable_child_gating", "disable_child_gating"}
    )

    def __init__(self, session: Session, *, config: AppConfig) -> None:
        self._session = session
        self._config = config
        logs = build_loggers(config.agent)
        self._resolver = RPCResolver(HandlerRegistry(config, logs.stdout, logs.stderr))

    @property
    def is_detached(self) -> bool: ...

    @overload
    def on(self, signal: str, callback: Callable[..., Any]) -> None: ...

    @overload
    def on(self, signal: Literal["detached"], callback: SessionDetachedCallback) -> None: ...

    @overload
    def off(self, signal: str, callback: Callable[..., Any]) -> None: ...

    @overload
    def off(self, signal: Literal["detached"], callback: SessionDetachedCallback) -> None: ...

    def create_script(
        self,
        source: str,
        name: str | None = None,
        snapshot: bytes | None = None,
        runtime: str | None = None,
        env: ScriptEnv | None = None,
    ) -> ScriptWrapper:
        inject_env = env or ScriptEnv()
        script = self._session.create_script(
            try_inject_environ(source, inject_env.model_dump()),
            name,
            snapshot,
            runtime,
        )
        return ScriptWrapper(script, inject_env, self._resolver)

    def open_script(
        self,
        jsfile: str,
        name: str | None = None,
        snapshot: bytes | None = None,
        runtime: str | None = None,
        env: ScriptEnv | None = None,
    ) -> ScriptWrapper:
        path = Path(jsfile)
        stat = path.stat()
        updated = datetime.fromtimestamp(stat.st_mtime)
        print("=================== frida-analykit ===================")
        print(f"[jsfile]    {jsfile}")
        print(f"[update_at] {updated.strftime('%Y-%m-%d %H:%M:%S.%f')}")
        print("======================================================")
        source = path.read_text(encoding="utf-8")
        return self.create_script(source, name, snapshot, runtime, env)

    @classmethod
    def from_session(cls, session: Session, *, config: AppConfig) -> "SessionWrapper":
        return cls(session, config=config)

    def __getattribute__(self, name: str):
        if name in SessionWrapper.__SESSION_EXPORT__:
            return getattr(self._session, name)
        return object.__getattribute__(self, name)
