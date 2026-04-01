from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TOOL_NAMES = [
    "session_open",
    "session_status",
    "session_close",
    "session_recover",
    "eval_js",
    "install_snippet",
    "call_snippet",
    "inspect_snippet",
    "remove_snippet",
    "list_snippets",
    "tail_logs",
]

EXPECTED_RESOURCE_URIS = [
    "frida://session/current",
    "frida://session/snippets",
    "frida://session/logs",
    "frida://docs/mcp/index",
    "frida://docs/mcp/workflow",
    "frida://docs/mcp/tools",
    "frida://docs/mcp/recovery",
]


def _run_async(coro):
    return asyncio.run(coro)


def test_entrypoint_exposes_expected_tools_and_resources_over_stdio() -> None:
    async def scenario() -> None:
        params = StdioServerParameters(
            command="uv",
            args=["run", "frida-analykit-mcp", "--idle-timeout", "1"],
            cwd=REPO_ROOT,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                resources = await session.list_resources()

        assert [tool.name for tool in tools.tools] == EXPECTED_TOOL_NAMES
        assert [str(resource.uri) for resource in resources.resources] == EXPECTED_RESOURCE_URIS

    _run_async(scenario())


def test_stdio_server_returns_structured_payloads_and_surfaces_runtime_mismatch(tmp_path: Path) -> None:
    server_script = tmp_path / "fake_mcp_server.py"
    server_script.write_text(
        textwrap.dedent(
            """
            from frida_analykit.mcp.models import SessionStatus, SnippetCollectionResult, TailLogsEntry, TailLogsResult
            from frida_analykit.mcp.server import build_mcp_server


            def _closed_status():
                return SessionStatus(
                    state="closed",
                    idle_timeout_seconds=1200,
                    closed_reason="not started",
                    snippet_count=0,
                    snippets=[],
                    log_count=0,
                )


            class FakeManager:
                def session_open(self, *, config_path, mode, pid=None, force_replace=False):
                    raise RuntimeError("RPC runtime mismatch: missing `/rpc`")

                def session_status(self):
                    return _closed_status()

                def session_close(self):
                    return _closed_status()

                def session_recover(self):
                    return _closed_status()

                def eval_js(self, *, source):
                    return {"source": source}

                def install_snippet(self, *, name, source, replace=False):
                    return {"name": name, "source": source, "replace": replace}

                def call_snippet(self, *, name, method=None, args=None):
                    return {"name": name, "method": method, "args": args or []}

                def inspect_snippet(self, *, name):
                    return {"name": name}

                def remove_snippet(self, *, name):
                    return {"name": name}

                def list_snippets(self):
                    return SnippetCollectionResult(session=_closed_status(), snippets=[])

                def tail_logs(self, *, limit=50):
                    return TailLogsResult(
                        session=_closed_status(),
                        entries=[TailLogsEntry(timestamp="2026-04-01T00:00:00Z", level="info", text=str(limit))],
                    )

                def resource_current_json(self):
                    return '{"state":"closed"}'

                def resource_snippets_json(self):
                    return '{"snippets":[]}'

                def resource_logs_json(self):
                    return '{"entries":[]}'


            build_mcp_server(FakeManager(), name="fake-frida-mcp").run(transport="stdio")
            """
        ),
        encoding="utf-8",
    )

    async def scenario() -> None:
        params = StdioServerParameters(
            command="uv",
            args=["run", "python", str(server_script)],
            cwd=REPO_ROOT,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                status = await session.call_tool("session_status")
                failure = await session.call_tool(
                    "session_open",
                    {"config_path": "config.yml", "mode": "attach", "pid": 1},
                )
                resource = await session.read_resource("frida://session/current")
                docs = await session.read_resource("frida://docs/mcp/index")

        assert status.structuredContent["state"] == "closed"
        assert status.structuredContent["closed_reason"] == "not started"
        assert failure.isError is True
        assert "missing `/rpc`" in failure.content[0].text
        assert resource.contents[0].text == '{"state":"closed"}'
        assert "session_open" in docs.contents[0].text

    _run_async(scenario())
