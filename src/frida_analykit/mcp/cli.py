from __future__ import annotations

import argparse
from collections.abc import Sequence

from .config import MCPStartupConfigError, load_mcp_startup_config
from .manager import DebugSessionManager
from .prepared import PreparedWorkspaceManager
from .server import build_mcp_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frida-analykit MCP server over stdio.")
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=None,
        help="Override the idle timeout from the MCP startup config; use 0 to disable idle cleanup.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Optional MCP startup TOML. Use this to pin server defaults and quick-session output paths.",
    )
    parser.add_argument(
        "--name",
        default="frida-analykit-mcp",
        help="Override the MCP server name advertised during initialization.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        startup_config = load_mcp_startup_config(args.config_path)
    except MCPStartupConfigError as exc:
        parser.error(str(exc))
    idle_timeout = startup_config.mcp.idle_timeout_seconds if args.idle_timeout is None else args.idle_timeout
    prepared_workspace = PreparedWorkspaceManager(startup_config=startup_config)
    manager = DebugSessionManager(
        idle_timeout_seconds=idle_timeout,
        prepared_workspace=prepared_workspace,
        startup_config=startup_config,
    )
    server = build_mcp_server(manager, name=args.name)
    server.run(transport="stdio")
    return 0
