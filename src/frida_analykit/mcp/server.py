from __future__ import annotations

import inspect
from collections.abc import Awaitable
from typing import Protocol, TypeVar, cast

from mcp.server.fastmcp import FastMCP

from .docs import MCPDocsProvider
from .models import EvalResult, SessionStatus, SnippetCollectionResult, SnippetMutationResult, TailLogsResult

T = TypeVar("T")


class MCPServiceProtocol(Protocol):
    def session_open(
        self,
        *,
        config_path: str,
        mode: str,
        pid: int | None = None,
        force_replace: bool = False,
    ) -> SessionStatus | Awaitable[SessionStatus]: ...

    def session_status(self) -> SessionStatus | Awaitable[SessionStatus]: ...

    def session_close(self) -> SessionStatus | Awaitable[SessionStatus]: ...

    def session_recover(self) -> SessionStatus | Awaitable[SessionStatus]: ...

    def eval_js(self, *, source: str) -> EvalResult | Awaitable[EvalResult]: ...

    def install_snippet(
        self,
        *,
        name: str,
        source: str,
        replace: bool = False,
    ) -> SnippetMutationResult | Awaitable[SnippetMutationResult]: ...

    def call_snippet(
        self,
        *,
        name: str,
        method: str | None = None,
        args: list | None = None,
    ) -> EvalResult | Awaitable[EvalResult]: ...

    def inspect_snippet(self, *, name: str) -> SnippetMutationResult | Awaitable[SnippetMutationResult]: ...

    def remove_snippet(self, *, name: str) -> SnippetMutationResult | Awaitable[SnippetMutationResult]: ...

    def list_snippets(self) -> SnippetCollectionResult | Awaitable[SnippetCollectionResult]: ...

    def tail_logs(self, *, limit: int = 50) -> TailLogsResult | Awaitable[TailLogsResult]: ...

    def resource_current_json(self) -> str | Awaitable[str]: ...

    def resource_snippets_json(self) -> str | Awaitable[str]: ...

    def resource_logs_json(self) -> str | Awaitable[str]: ...

 
class MCPDocsProtocol(Protocol):
    def resource_index_markdown(self) -> str | Awaitable[str]: ...

    def resource_workflow_markdown(self) -> str | Awaitable[str]: ...

    def resource_tools_markdown(self) -> str | Awaitable[str]: ...

    def resource_recovery_markdown(self) -> str | Awaitable[str]: ...


async def _maybe_await(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await cast(Awaitable[T], value)
    return cast(T, value)


def build_mcp_server(
    manager: MCPServiceProtocol,
    *,
    name: str = "frida-analykit-mcp",
    docs_provider: MCPDocsProtocol | None = None,
) -> FastMCP:
    mcp = FastMCP(name)
    docs = docs_provider or MCPDocsProvider()

    @mcp.tool(
        description="Open or reuse the current Frida debug session. Start here, then reuse the same session for follow-up validation.",
        structured_output=True,
    )
    async def session_open(
        config_path: str,
        mode: str,
        pid: int | None = None,
        force_replace: bool = False,
    ) -> SessionStatus:
        return await _maybe_await(
            manager.session_open(
            config_path=config_path,
            mode=mode,
            pid=pid,
            force_replace=force_replace,
            )
        )

    @mcp.tool(
        description="Inspect the current Frida debug session before choosing whether to recover, reuse, or replace it.",
        structured_output=True,
    )
    async def session_status() -> SessionStatus:
        return await _maybe_await(manager.session_status())

    @mcp.tool(
        description="Close the current Frida debug session and release resources. Prefer this over waiting for idle timeout.",
        structured_output=True,
    )
    async def session_close() -> SessionStatus:
        return await _maybe_await(manager.session_close())

    @mcp.tool(
        description="Recover a broken Frida debug session without auto-replaying snippets. Reinstall required snippets explicitly after recovery.",
        structured_output=True,
    )
    async def session_recover() -> SessionStatus:
        return await _maybe_await(manager.session_recover())

    @mcp.tool(
        description="Evaluate one-off JavaScript in the current Frida session. Prefer this before promoting logic into a managed snippet.",
        structured_output=True,
    )
    async def eval_js(source: str) -> EvalResult:
        return await _maybe_await(manager.eval_js(source=source))

    @mcp.tool(
        description="Install a named JavaScript snippet and keep its root handle alive in the current session for repeated calls.",
        structured_output=True,
    )
    async def install_snippet(name: str, source: str, replace: bool = False) -> SnippetMutationResult:
        return await _maybe_await(manager.install_snippet(name=name, source=source, replace=replace))

    @mcp.tool(
        description="Call a named snippet root or one of its dotted methods after it has been installed.",
        structured_output=True,
    )
    async def call_snippet(name: str, method: str | None = None, args: list | None = None) -> EvalResult:
        return await _maybe_await(manager.call_snippet(name=name, method=method, args=args))

    @mcp.tool(
        description="Inspect a named snippet and its last known root snapshot before deciding whether it must be reinstalled.",
        structured_output=True,
    )
    async def inspect_snippet(name: str) -> SnippetMutationResult:
        return await _maybe_await(manager.inspect_snippet(name=name))

    @mcp.tool(
        description="Remove a named snippet and call its dispose method when available. Use this for deterministic cleanup.",
        structured_output=True,
    )
    async def remove_snippet(name: str) -> SnippetMutationResult:
        return await _maybe_await(manager.remove_snippet(name=name))

    @mcp.tool(
        description="List named snippets tracked in the current session, including inactive metadata after a broken detach.",
        structured_output=True,
    )
    async def list_snippets() -> SnippetCollectionResult:
        return await _maybe_await(manager.list_snippets())

    @mcp.tool(
        description="Read recent session log entries captured from the Frida script. Use this after risky injections or detach events.",
        structured_output=True,
    )
    async def tail_logs(limit: int = 50) -> TailLogsResult:
        return await _maybe_await(manager.tail_logs(limit=limit))

    @mcp.resource(
        "frida://session/current",
        name="current-session",
        description="Current Frida MCP session state.",
        mime_type="application/json",
    )
    async def current_session_resource() -> str:
        return await _maybe_await(manager.resource_current_json())

    @mcp.resource(
        "frida://session/snippets",
        name="session-snippets",
        description="Named snippets tracked in the current Frida MCP session.",
        mime_type="application/json",
    )
    async def session_snippets_resource() -> str:
        return await _maybe_await(manager.resource_snippets_json())

    @mcp.resource(
        "frida://session/logs",
        name="session-logs",
        description="Recent log entries captured from the current Frida MCP session.",
        mime_type="application/json",
    )
    async def session_logs_resource() -> str:
        return await _maybe_await(manager.resource_logs_json())

    @mcp.resource(
        "frida://docs/mcp/index",
        name="mcp-docs-index",
        description="High-level usage notes for the frida-analykit MCP server.",
        mime_type="text/markdown",
    )
    async def mcp_docs_index_resource() -> str:
        return await _maybe_await(docs.resource_index_markdown())

    @mcp.resource(
        "frida://docs/mcp/workflow",
        name="mcp-docs-workflow",
        description="Recommended long-session workflow for Frida MCP validation.",
        mime_type="text/markdown",
    )
    async def mcp_docs_workflow_resource() -> str:
        return await _maybe_await(docs.resource_workflow_markdown())

    @mcp.resource(
        "frida://docs/mcp/tools",
        name="mcp-docs-tools",
        description="Tool-by-tool guidance for the frida-analykit MCP server.",
        mime_type="text/markdown",
    )
    async def mcp_docs_tools_resource() -> str:
        return await _maybe_await(docs.resource_tools_markdown())

    @mcp.resource(
        "frida://docs/mcp/recovery",
        name="mcp-docs-recovery",
        description="Recovery guidance for detach, crash, and RPC mismatch scenarios.",
        mime_type="text/markdown",
    )
    async def mcp_docs_recovery_resource() -> str:
        return await _maybe_await(docs.resource_recovery_markdown())

    return mcp
