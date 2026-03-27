from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Final, Literal, overload

from frida.core import Script, ScriptExportsAsync, Session, SessionDetachedCallback

from ._version import __version__
from .config import AgentConfig, AppConfig
from .logging import LoggerBundle, build_loggers
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
void (async () => {{
    try {{
        await import("/index.js");
    }} catch (error) {{
        const description = (() => {{
            if (error instanceof Error && typeof error.message === "string" && error.message) {{
                return error.message;
            }}
            if (typeof error === "string" && error.length > 0) {{
                return error;
            }}
            try {{
                return JSON.stringify(error);
            }} catch {{
                return String(error);
            }}
        }})();
        const stack = error instanceof Error && typeof error.stack === "string" ? error.stack : "";
        console.error(`[frida-analykit/bootstrap] ${{description}}`);
        if (stack) {{
            console.error(stack);
        }}
        throw error;
    }}
}})();
"""

REG_MAP_SOURCE: Final[re.Pattern[str]] = re.compile(r"^(\d+)\s+(.*?)$", re.MULTILINE)
ScriptEnv = RPCMsgInitConfig
SESSION_BANNER_LOGO: Final[str] = r"""
███████╗██████╗ ██╗██████╗  █████╗        █████╗ ███╗   ██╗ █████╗ ██╗     ██╗   ██╗██╗  ██╗██╗████████╗
██╔════╝██╔══██╗██║██╔══██╗██╔══██╗      ██╔══██╗████╗  ██║██╔══██╗██║     ╚██╗ ██╔╝██║ ██╔╝██║╚══██╔══╝
█████╗  ██████╔╝██║██║  ██║███████║█████╗███████║██╔██╗ ██║███████║██║      ╚████╔╝ █████═╝ ██║   ██║
██╔══╝  ██╔══██╗██║██║  ██║██╔══██║╚════╝██╔══██║██║╚██╗██║██╔══██║██║       ╚██╔╝  ██╔═██╗ ██║   ██║
██║     ██║  ██║██║██████╔╝██║  ██║      ██║  ██║██║ ╚████║██║  ██║███████╗   ██║   ██║  ██╗██║   ██║
╚═╝     ╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝      ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝   ╚═╝
""".strip("\n")


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


def render_session_banner(config: AppConfig, *, jsfile: Path, updated: datetime) -> str:
    base_dir = config.source_path.parent if config.source_path is not None else None

    def display_path(path: Path | None) -> str:
        if path is None:
            return "<unset>"
        candidate = Path(path)
        if base_dir is not None:
            try:
                relative = candidate.relative_to(base_dir)
            except ValueError:
                pass
            else:
                base = f".../{base_dir.name}"
                if str(relative) == ".":
                    return base
                return f"{base}/{relative.as_posix()}"
        parts = candidate.as_posix().split("/")
        if len(parts) > 4:
            return ".../" + "/".join(parts[-4:])
        return candidate.as_posix()

    def render_item(label: str, value: str) -> str:
        return f"  ➜  {label:<11} {value}"

    lines = [
        SESSION_BANNER_LOGO,
        "",
        f"  v{__version__} ready at {updated.strftime('%H:%M:%S')}",
        "",
        render_item("Host:", config.server.host),
        render_item("Target:", config.app or "<unset>"),
        render_item("Script:", display_path(jsfile)),
    ]
    stdout_path = config.agent.stdout
    stderr_path = config.agent.stderr
    if stdout_path is not None and stderr_path is not None and stdout_path == stderr_path:
        lines.append(render_item("Log Output:", display_path(stdout_path)))
    else:
        lines.append(render_item("Stdout:", display_path(stdout_path) if stdout_path is not None else "<stdout>"))
        lines.append(render_item("Stderr:", display_path(stderr_path) if stderr_path is not None else "<stderr>"))
    lines = [
        *lines,
        "",
    ]
    return "\n".join(lines)


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

    def __init__(
        self,
        script: Script,
        env: ScriptEnv,
        resolver: RPCResolver,
        *,
        loggers: LoggerBundle | None = None,
    ) -> None:
        self._script = script
        self._env = env
        self._resolver = resolver
        self._loggers = loggers
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

    def set_logger(self, loggers: LoggerBundle | None = None) -> None:
        active_loggers = loggers or self._loggers or build_loggers(AgentConfig())
        self._loggers = active_loggers

        def handler(level: str, text: str) -> None:
            stream = active_loggers.stdout if level == "info" else active_loggers.stderr
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
        self._logs = build_loggers(config.agent)
        self._resolver = RPCResolver(HandlerRegistry(config, self._logs.stdout, self._logs.stderr))

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
        return ScriptWrapper(script, inject_env, self._resolver, loggers=self._logs)

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
        print(render_session_banner(self._config, jsfile=path, updated=updated))
        source = path.read_text(encoding="utf-8")
        return self.create_script(source, name, snapshot, runtime, env)

    @classmethod
    def from_session(cls, session: Session, *, config: AppConfig) -> "SessionWrapper":
        return cls(session, config=config)

    def __getattribute__(self, name: str):
        if name in SessionWrapper.__SESSION_EXPORT__:
            return getattr(self._session, name)
        return object.__getattribute__(self, name)
