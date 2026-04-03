from __future__ import annotations

import asyncio
import json
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from frida_analykit.mcp.server import build_mcp_server

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TOOL_NAMES = [
    "session_open",
    "session_status",
    "session_open_quick",
    "session_close",
    "session_recover",
    "eval_js",
    "install_snippet",
    "call_snippet",
    "inspect_snippet",
    "remove_snippet",
    "list_snippets",
    "tail_logs",
    "prepared_session_inspect",
    "prepared_session_prune",
]

EXPECTED_RESOURCE_URIS = [
    "frida://session/current",
    "frida://service/config",
    "frida://session/prepared",
    "frida://session/snippets",
    "frida://session/logs",
    "frida://docs/mcp/index",
    "frida://docs/mcp/config",
    "frida://docs/mcp/quickstart",
    "frida://docs/mcp/workflow",
    "frida://docs/mcp/tools",
    "frida://docs/mcp/recovery",
]


def _run_async(coro):
    return asyncio.run(coro)


def test_entrypoint_exposes_expected_tools_and_resources_over_stdio(tmp_path: Path) -> None:
    server_script = tmp_path / "mcp_entrypoint.py"
    server_script.write_text(
        textwrap.dedent(
            """
            from datetime import datetime, timezone
            from pathlib import Path

            from frida_analykit.mcp import cli
            from frida_analykit.mcp.models import (
                QuickPathCheckSummary,
                QuickPathCompileProbeSummary,
                QuickPathReadinessSummary,
                QuickPathToolchainSummary,
            )


            def _quick_ready(cache_root: Path) -> QuickPathReadinessSummary:
                return QuickPathReadinessSummary(
                    state="ready",
                    checked_at=datetime.now(timezone.utc),
                    message="quick path toolchain is ready",
                    cache_root=QuickPathCheckSummary(
                        state="ready",
                        path=cache_root,
                        detail="prepared cache root is writable",
                    ),
                    npm=QuickPathCheckSummary(
                        state="ready",
                        path=Path("/usr/bin/npm"),
                        detail="found in MCP PATH",
                    ),
                    frida_compile=QuickPathCheckSummary(
                        state="ready",
                        path=Path("/usr/bin/frida-compile"),
                        detail="found in MCP PATH",
                    ),
                    shared_toolchain=QuickPathToolchainSummary(
                        state="cache_hit",
                        root=cache_root / "_toolchains" / "demo",
                        agent_package_spec="@zsa233/frida-analykit-agent@1.0.0",
                        detail="reused shared quick runtime toolchain",
                    ),
                    compile_probe=QuickPathCompileProbeSummary(
                        state="compiled",
                        workspace_root=cache_root / "_startup_probe" / "demo",
                        bundle_path=cache_root / "_startup_probe" / "demo" / "_agent.js",
                        detail="compile sanity probe succeeded",
                        last_error=None,
                    ),
                )


            cli.PreparedWorkspaceManager.startup_warmup = lambda self: _quick_ready(self.cache_root)
            raise SystemExit(cli.main(["--idle-timeout", "1"]))
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
                tools = await session.list_tools()
                resources = await session.list_resources()
                service_config = await session.read_resource("frida://service/config")

        assert {tool.name for tool in tools.tools} == set(EXPECTED_TOOL_NAMES)
        assert {str(resource.uri) for resource in resources.resources} == set(EXPECTED_RESOURCE_URIS)
        quick_tool = next(tool for tool in tools.tools if tool.name == "session_open_quick")
        capability_enum = quick_tool.inputSchema["properties"]["capabilities"]["anyOf"][0]["items"]["enum"]
        assert "elf_enhanced" not in capability_enum
        summary = json.loads(service_config.contents[0].text)
        assert len(summary["service_instance_id"]) == 12
        assert "service_started_at" in summary
        assert "session_history_root" in summary
        assert summary["quick_path"]["state"] == "ready"

    _run_async(scenario())


def test_cli_exits_before_stdio_serve_when_startup_warmup_fails(tmp_path: Path) -> None:
    server_script = tmp_path / "mcp_fail.py"
    server_script.write_text(
        textwrap.dedent(
            """
            from datetime import datetime, timezone

            from frida_analykit.mcp import cli
            from frida_analykit.mcp.models import (
                QuickPathCheckSummary,
                QuickPathCompileProbeSummary,
                QuickPathReadinessSummary,
                QuickPathToolchainSummary,
            )


            def _quick_failed(cache_root):
                return QuickPathReadinessSummary(
                    state="failed",
                    checked_at=datetime.now(timezone.utc),
                    message="quick path requires `frida-compile` in the MCP environment PATH",
                    cache_root=QuickPathCheckSummary(
                        state="ready",
                        path=cache_root,
                        detail="prepared cache root is writable",
                    ),
                    npm=QuickPathCheckSummary(
                        state="ready",
                        path=None,
                        detail="found in MCP PATH",
                    ),
                    frida_compile=QuickPathCheckSummary(
                        state="failed",
                        path=None,
                        detail="quick path requires `frida-compile` in the MCP environment PATH",
                    ),
                    shared_toolchain=QuickPathToolchainSummary(
                        state="skipped",
                        root=cache_root / "_toolchains" / "demo",
                        agent_package_spec="@zsa233/frida-analykit-agent@1.0.0",
                        detail="shared toolchain warmup was not attempted",
                    ),
                    compile_probe=QuickPathCompileProbeSummary(
                        state="skipped",
                        workspace_root=cache_root / "_startup_probe" / "demo",
                        bundle_path=cache_root / "_startup_probe" / "demo" / "_agent.js",
                        detail="compile probe was not attempted",
                        last_error=None,
                    ),
                )


            cli.PreparedWorkspaceManager.startup_warmup = lambda self: _quick_failed(self.cache_root)
            raise SystemExit(cli.main(["--idle-timeout", "1"]))
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["uv", "run", "python", str(server_script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "quick-path warmup failed" in result.stderr
    assert "frida-compile" in result.stderr


def test_cli_exits_promptly_after_single_sigint(tmp_path: Path) -> None:
    server_script = tmp_path / "mcp_sigint.py"
    server_script.write_text(
        textwrap.dedent(
            """
            from datetime import datetime, timezone
            from pathlib import Path

            from frida_analykit.mcp import cli
            from frida_analykit.mcp.models import (
                QuickPathCheckSummary,
                QuickPathCompileProbeSummary,
                QuickPathReadinessSummary,
                QuickPathToolchainSummary,
            )


            def _quick_ready(cache_root: Path) -> QuickPathReadinessSummary:
                return QuickPathReadinessSummary(
                    state="ready",
                    checked_at=datetime.now(timezone.utc),
                    message="quick path toolchain is ready",
                    cache_root=QuickPathCheckSummary(
                        state="ready",
                        path=cache_root,
                        detail="prepared cache root is writable",
                    ),
                    npm=QuickPathCheckSummary(
                        state="ready",
                        path=Path("/usr/bin/npm"),
                        detail="found in MCP PATH",
                    ),
                    frida_compile=QuickPathCheckSummary(
                        state="ready",
                        path=Path("/usr/bin/frida-compile"),
                        detail="found in MCP PATH",
                    ),
                    shared_toolchain=QuickPathToolchainSummary(
                        state="cache_hit",
                        root=cache_root / "_toolchains" / "demo",
                        agent_package_spec="@zsa233/frida-analykit-agent@1.0.0",
                        detail="reused shared quick runtime toolchain",
                    ),
                    compile_probe=QuickPathCompileProbeSummary(
                        state="compiled",
                        workspace_root=cache_root / "_startup_probe" / "demo",
                        bundle_path=cache_root / "_startup_probe" / "demo" / "_agent.js",
                        detail="compile sanity probe succeeded",
                        last_error=None,
                    ),
                )


            cli.PreparedWorkspaceManager.startup_warmup = lambda self: _quick_ready(self.cache_root)
            raise SystemExit(cli.main(["--idle-timeout", "1"]))
            """
        ),
        encoding="utf-8",
    )

    process = subprocess.Popen(
        [sys.executable, str(server_script)],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.5)
        process.send_signal(signal.SIGINT)
        return_code = process.wait(timeout=5)
        _, stderr = process.communicate(timeout=1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert return_code == 130
    assert "received Ctrl+C, shutting down" in stderr
    assert "KeyboardInterrupt" not in stderr


def test_build_mcp_server_closes_manager_via_server_lifespan() -> None:
    events: list[str] = []

    class FakeManager:
        async def aclose(self) -> None:
            events.append("closed")

    server = build_mcp_server(FakeManager(), name="fake-frida-mcp")

    async def scenario() -> None:
        async with server._mcp_server.lifespan(server._mcp_server):
            events.append("entered")

    _run_async(scenario())

    assert events == ["entered", "closed"]


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
                async def session_open(self, *, config_path, mode, pid=None, force_replace=False):
                    raise RuntimeError("RPC runtime mismatch: missing `/rpc`")

                async def session_status(self):
                    return _closed_status()

                async def session_open_quick(
                    self,
                    *,
                    app,
                    mode,
                    capabilities=None,
                    template="minimal",
                    pid=None,
                    bootstrap_path=None,
                    bootstrap_source=None,
                    force_replace=False,
                ):
                    raise RuntimeError("RPC runtime mismatch: missing `/rpc`")

                async def session_close(self):
                    return _closed_status()

                async def session_recover(self):
                    return _closed_status()

                async def eval_js(self, *, source):
                    return {"source": source}

                async def install_snippet(self, *, name, source, replace=False):
                    return {"name": name, "source": source, "replace": replace}

                async def call_snippet(self, *, name, method=None, args=None):
                    return {"name": name, "method": method, "args": args or []}

                async def inspect_snippet(self, *, name):
                    return {"name": name}

                async def remove_snippet(self, *, name):
                    return {"name": name}

                async def list_snippets(self):
                    return SnippetCollectionResult(session=_closed_status(), snippets=[])

                async def tail_logs(self, *, limit=50):
                    return TailLogsResult(
                        session=_closed_status(),
                        entries=[TailLogsEntry(timestamp="2026-04-01T00:00:00Z", level="info", text=str(limit))],
                    )

                async def prepared_session_inspect(self, *, signature=None):
                    return {"prepared": False, "signature": signature}

                async def prepared_session_prune(self, *, signature=None, all_unused=False, older_than_seconds=None):
                    return {
                        "deleted_signatures": [],
                        "skipped_active_signatures": [],
                        "message": "noop",
                    }

                async def resource_current_json(self):
                    return '{"state":"closed"}'

                async def resource_service_config_json(self):
                    return '{"server":{"host":"127.0.0.1:27042"}}'

                async def resource_prepared_json(self):
                    return '{"prepared":false}'

                async def resource_snippets_json(self):
                    return '{"snippets":[]}'

                async def resource_logs_json(self):
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
                    {"config_path": "config.toml", "mode": "attach", "pid": 1},
                )
                quick_failure = await session.call_tool(
                    "session_open_quick",
                    {"app": "com.example.demo", "mode": "attach"},
                )
                service_config = await session.read_resource("frida://service/config")
                resource = await session.read_resource("frida://session/current")

        assert status.structuredContent["state"] == "closed"
        assert status.structuredContent["closed_reason"] == "not started"
        assert failure.isError is True
        assert "missing `/rpc`" in failure.content[0].text
        assert quick_failure.isError is True
        assert "missing `/rpc`" in quick_failure.content[0].text
        assert "127.0.0.1:27042" in service_config.contents[0].text
        assert resource.contents[0].text == '{"state":"closed"}'

    _run_async(scenario())
