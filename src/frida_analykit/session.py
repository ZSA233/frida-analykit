from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Final, Literal, overload

from frida.core import Script, Session, SessionDetachedCallback

from ._version import __version__
from .config import AgentConfig, AppConfig
from .logging import LoggerBundle, build_loggers
from .rpc.client import RPCClient
from .rpc.exports import ScriptExportsAsyncWrapper, ScriptExportsSyncWrapper
from .rpc.handler.js_handle import JsHandle
from .rpc.message import RPCMessage, RPCMsgInitConfig
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


@dataclass(slots=True)
class SessionRuntime:
    config: AppConfig
    loggers: LoggerBundle
    resolver: RPCResolver
    interactive: bool = False


@dataclass(slots=True)
class ScriptRuntime:
    env: ScriptEnv
    rpc: RPCClient
    loggers: LoggerBundle | None = None


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
    lines.extend([""])
    return "\n".join(lines)


class ScriptWrapper:
    def __init__(self, script: Script, runtime: ScriptRuntime) -> None:
        self._script = script
        self._runtime = runtime
        self._scope_id = runtime.rpc.scope_id
        # Public script exports should stay close to Frida's native semantics.
        # RPC payload normalization belongs to RPCClient only.
        self.exports_sync: ScriptExportsSyncWrapper = ScriptExportsSyncWrapper(script)
        self.exports_async: ScriptExportsAsyncWrapper = ScriptExportsAsyncWrapper(script)

    @property
    def scope_id(self) -> str:
        return self._scope_id

    def load(self) -> None:
        self._script.load()

    def unload(self) -> None:
        self._script.unload()

    def eternalize(self) -> None:
        self._script.eternalize()

    def enable_debugger(self, port: int | None = None) -> None:
        if port is None:
            self._script.enable_debugger()
            return
        self._script.enable_debugger(port)

    def disable_debugger(self) -> None:
        self._script.disable_debugger()

    def list_exports_sync(self) -> list[str]:
        return self.exports_sync._list_exports()

    async def list_exports_async(self) -> list[str]:
        return await self.exports_async._list_exports()

    def set_log_handler(self, handler: Callable[[str, str], None] | None) -> None:
        self._script.set_log_handler(handler)

    def post(self, message: RPCMessage, data: bytes | None = None) -> None:
        self._script.post(message.to_mapping(), data)

    def set_logger(self, loggers: LoggerBundle | None = None) -> None:
        active_loggers = loggers or self._runtime.loggers or build_loggers(AgentConfig())
        self._runtime.loggers = active_loggers

        def handler(level: str, text: str) -> None:
            stream = active_loggers.stdout if level == "info" else active_loggers.stderr
            print(text, file=stream)

        self.set_log_handler(handler)

    def jsh(self, path: str) -> JsHandle:
        return JsHandle.from_seed_path(path, client=self._runtime.rpc)

    def eval(self, source: str) -> JsHandle:
        return JsHandle.from_scope_result(self._runtime.rpc.eval(source), client=self._runtime.rpc)

    async def eval_async(self, source: str) -> JsHandle:
        return JsHandle.from_scope_result(await self._runtime.rpc.eval_async(source), client=self._runtime.rpc)


class SessionWrapper:
    def __init__(self, session: Session, *, config: AppConfig, interactive: bool = False) -> None:
        self._session = session
        self._config = config
        loggers = build_loggers(config.agent)
        registry = HandlerRegistry(config, loggers.stdout, loggers.stderr)
        resolver = RPCResolver(registry)
        self._runtime = SessionRuntime(config=config, loggers=loggers, resolver=resolver, interactive=interactive)

    @property
    def is_detached(self) -> bool:
        return self._session.is_detached

    @overload
    def on(self, signal: str, callback: Callable[..., Any]) -> None: ...

    @overload
    def on(self, signal: Literal["detached"], callback: SessionDetachedCallback) -> None: ...

    def on(self, signal: str, callback: Callable[..., Any]) -> None:
        self._session.on(signal, callback)

    @overload
    def off(self, signal: str, callback: Callable[..., Any]) -> None: ...

    @overload
    def off(self, signal: Literal["detached"], callback: SessionDetachedCallback) -> None: ...

    def off(self, signal: str, callback: Callable[..., Any]) -> None:
        self._session.off(signal, callback)

    def detach(self) -> None:
        self._session.detach()

    def resume(self) -> None:
        self._session.resume()

    def enable_child_gating(self) -> None:
        self._session.enable_child_gating()

    def disable_child_gating(self) -> None:
        self._session.disable_child_gating()

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
        self._runtime.resolver.register_script(script)
        scope_id = uuid.uuid4().hex
        script_runtime = ScriptRuntime(
            env=inject_env,
            rpc=RPCClient(script, scope_id=scope_id, interactive=self._runtime.interactive),
            loggers=self._runtime.loggers,
        )
        return ScriptWrapper(script, script_runtime)

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
    def from_session(
        cls,
        session: Session,
        *,
        config: AppConfig,
        interactive: bool = False,
    ) -> "SessionWrapper":
        return cls(session, config=config, interactive=interactive)
