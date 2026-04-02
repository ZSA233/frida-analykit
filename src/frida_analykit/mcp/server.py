from __future__ import annotations

from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .manager import DebugSessionManager
from .docs import MCPDocsProvider
from .models import (
    EvalResult,
    PreparedSessionInspectResult,
    PreparedSessionPruneResult,
    SessionStatus,
    SnippetCollectionResult,
    SnippetMutationResult,
    TailLogsResult,
)
from .prepared import QuickCapability, QuickTemplate

class MCPServiceProtocol(Protocol):
    async def session_open(
        self,
        *,
        config_path: str,
        mode: str,
        pid: int | None = None,
        force_replace: bool = False,
    ) -> SessionStatus: ...

    async def session_status(self) -> SessionStatus: ...

    async def session_open_quick(
        self,
        *,
        app: str,
        mode: str,
        capabilities: list[QuickCapability] | None = None,
        template: QuickTemplate = "minimal",
        pid: int | None = None,
        bootstrap_path: str | None = None,
        bootstrap_source: str | None = None,
        force_replace: bool = False,
    ) -> SessionStatus: ...

    async def session_close(self) -> SessionStatus: ...

    async def session_recover(self) -> SessionStatus: ...

    async def eval_js(self, *, source: str) -> EvalResult: ...

    async def install_snippet(
        self,
        *,
        name: str,
        source: str,
        replace: bool = False,
    ) -> SnippetMutationResult: ...

    async def call_snippet(
        self,
        *,
        name: str,
        method: str | None = None,
        args: list | None = None,
    ) -> EvalResult: ...

    async def inspect_snippet(self, *, name: str) -> SnippetMutationResult: ...

    async def remove_snippet(self, *, name: str) -> SnippetMutationResult: ...

    async def list_snippets(self) -> SnippetCollectionResult: ...

    async def tail_logs(self, *, limit: int = 50) -> TailLogsResult: ...

    async def prepared_session_inspect(self, *, signature: str | None = None) -> PreparedSessionInspectResult: ...

    async def prepared_session_prune(
        self,
        *,
        signature: str | None = None,
        all_unused: bool = False,
        older_than_seconds: int | None = None,
    ) -> PreparedSessionPruneResult: ...

    async def resource_current_json(self) -> str: ...

    async def resource_service_config_json(self) -> str: ...

    async def resource_prepared_json(self) -> str: ...

    async def resource_snippets_json(self) -> str: ...

    async def resource_logs_json(self) -> str: ...

class MCPDocsProtocol(Protocol):
    def resource_index_markdown(self) -> str: ...

    def resource_config_markdown(self) -> str: ...

    def resource_quickstart_markdown(self) -> str: ...

    def resource_workflow_markdown(self) -> str: ...

    def resource_tools_markdown(self) -> str: ...

    def resource_recovery_markdown(self) -> str: ...


def build_mcp_server(
    manager: DebugSessionManager | MCPServiceProtocol,
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
        return await manager.session_open(
            config_path=config_path,
            mode=mode,
            pid=pid,
            force_replace=force_replace,
        )

    @mcp.tool(
        description="Inspect the current Frida debug session before choosing whether to recover, reuse, or replace it.",
        structured_output=True,
    )
    async def session_status() -> SessionStatus:
        return await manager.session_status()

    @mcp.tool(
        description="Recommended MCP entrypoint. Prepare or reuse a cached minimal agent workspace, optionally import `bootstrap_path` or compile `bootstrap_source`, write `config.toml` from the fixed MCP startup config, then open or reuse the session.",
        structured_output=True,
    )
    async def session_open_quick(
        app: str,
        mode: str,
        capabilities: list[QuickCapability] | None = None,
        template: QuickTemplate = "minimal",
        pid: int | None = None,
        bootstrap_path: str | None = None,
        bootstrap_source: str | None = None,
        force_replace: bool = False,
    ) -> SessionStatus:
        return await manager.session_open_quick(
            app=app,
            mode=mode,
            capabilities=capabilities,
            template=template,
            pid=pid,
            bootstrap_path=bootstrap_path,
            bootstrap_source=bootstrap_source,
            force_replace=force_replace,
        )

    @mcp.tool(
        description="Close the current Frida debug session and release resources. Prefer this over waiting for idle timeout.",
        structured_output=True,
    )
    async def session_close() -> SessionStatus:
        return await manager.session_close()

    @mcp.tool(
        description="Recover a broken Frida debug session without auto-replaying snippets. Reinstall required snippets explicitly after recovery.",
        structured_output=True,
    )
    async def session_recover() -> SessionStatus:
        return await manager.session_recover()

    @mcp.tool(
        description="Evaluate one-off JavaScript in the current Frida session. Prefer this before promoting logic into a managed snippet.",
        structured_output=True,
    )
    async def eval_js(source: str) -> EvalResult:
        return await manager.eval_js(source=source)

    @mcp.tool(
        description="Install a named JavaScript snippet and keep its root handle alive in the current session for repeated calls.",
        structured_output=True,
    )
    async def install_snippet(name: str, source: str, replace: bool = False) -> SnippetMutationResult:
        return await manager.install_snippet(name=name, source=source, replace=replace)

    @mcp.tool(
        description="Call a named snippet root or one of its dotted methods after it has been installed.",
        structured_output=True,
    )
    async def call_snippet(name: str, method: str | None = None, args: list | None = None) -> EvalResult:
        return await manager.call_snippet(name=name, method=method, args=args)

    @mcp.tool(
        description="Inspect a named snippet and its last known root snapshot before deciding whether it must be reinstalled.",
        structured_output=True,
    )
    async def inspect_snippet(name: str) -> SnippetMutationResult:
        return await manager.inspect_snippet(name=name)

    @mcp.tool(
        description="Remove a named snippet and call its dispose method when available. Use this for deterministic cleanup.",
        structured_output=True,
    )
    async def remove_snippet(name: str) -> SnippetMutationResult:
        return await manager.remove_snippet(name=name)

    @mcp.tool(
        description="List named snippets tracked in the current session, including inactive metadata after a broken detach.",
        structured_output=True,
    )
    async def list_snippets() -> SnippetCollectionResult:
        return await manager.list_snippets()

    @mcp.tool(
        description="Read recent session log entries captured from the Frida script. Use this after risky injections or detach events.",
        structured_output=True,
    )
    async def tail_logs(limit: int = 50) -> TailLogsResult:
        return await manager.tail_logs(limit=limit)

    @mcp.tool(
        description="Inspect the prepared quick-session workspace, generated imports, config summary, and recent build outcome for a signature or the current prepared session.",
        structured_output=True,
    )
    async def prepared_session_inspect(signature: str | None = None) -> PreparedSessionInspectResult:
        return await manager.prepared_session_inspect(signature=signature)

    @mcp.tool(
        description="Prune cached quick-session workspaces by signature or age. Active session artifacts are kept unless you close the session first.",
        structured_output=True,
    )
    async def prepared_session_prune(
        signature: str | None = None,
        all_unused: bool = False,
        older_than_seconds: int | None = None,
    ) -> PreparedSessionPruneResult:
        return await manager.prepared_session_prune(
            signature=signature,
            all_unused=all_unused,
            older_than_seconds=older_than_seconds,
        )

    @mcp.resource(
        "frida://session/current",
        name="current-session",
        description="Current Frida MCP session state.",
        mime_type="application/json",
    )
    async def current_session_resource() -> str:
        return await manager.resource_current_json()

    @mcp.resource(
        "frida://service/config",
        name="service-config",
        description="Effective MCP startup config loaded for this server process.",
        mime_type="application/json",
    )
    async def service_config_resource() -> str:
        return await manager.resource_service_config_json()

    @mcp.resource(
        "frida://session/prepared",
        name="prepared-session",
        description="Prepared quick-session workspace details for the active MCP session.",
        mime_type="application/json",
    )
    async def prepared_session_resource() -> str:
        return await manager.resource_prepared_json()

    @mcp.resource(
        "frida://session/snippets",
        name="session-snippets",
        description="Named snippets tracked in the current Frida MCP session.",
        mime_type="application/json",
    )
    async def session_snippets_resource() -> str:
        return await manager.resource_snippets_json()

    @mcp.resource(
        "frida://session/logs",
        name="session-logs",
        description="Recent log entries captured from the current Frida MCP session.",
        mime_type="application/json",
    )
    async def session_logs_resource() -> str:
        return await manager.resource_logs_json()

    @mcp.resource(
        "frida://docs/mcp/index",
        name="mcp-docs-index",
        description="High-level usage notes for the frida-analykit MCP server.",
        mime_type="text/markdown",
    )
    async def mcp_docs_index_resource() -> str:
        return docs.resource_index_markdown()

    @mcp.resource(
        "frida://docs/mcp/config",
        name="mcp-docs-config",
        description="MCP startup TOML config structure and how quick sessions inherit it.",
        mime_type="text/markdown",
    )
    async def mcp_docs_config_resource() -> str:
        return docs.resource_config_markdown()

    @mcp.resource(
        "frida://docs/mcp/quickstart",
        name="mcp-docs-quickstart",
        description="Quick-session usage notes for auto-prepared MCP workspaces.",
        mime_type="text/markdown",
    )
    async def mcp_docs_quickstart_resource() -> str:
        return docs.resource_quickstart_markdown()

    @mcp.resource(
        "frida://docs/mcp/workflow",
        name="mcp-docs-workflow",
        description="Recommended long-session workflow for Frida MCP validation.",
        mime_type="text/markdown",
    )
    async def mcp_docs_workflow_resource() -> str:
        return docs.resource_workflow_markdown()

    @mcp.resource(
        "frida://docs/mcp/tools",
        name="mcp-docs-tools",
        description="Tool-by-tool guidance for the frida-analykit MCP server.",
        mime_type="text/markdown",
    )
    async def mcp_docs_tools_resource() -> str:
        return docs.resource_tools_markdown()

    @mcp.resource(
        "frida://docs/mcp/recovery",
        name="mcp-docs-recovery",
        description="Recovery guidance for detach, crash, and RPC mismatch scenarios.",
        mime_type="text/markdown",
    )
    async def mcp_docs_recovery_resource() -> str:
        return docs.resource_recovery_markdown()

    return mcp
