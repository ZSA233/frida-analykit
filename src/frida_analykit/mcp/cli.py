from __future__ import annotations

import argparse
from collections.abc import Sequence

from .async_manager import AsyncDebugSessionManager
from .server import build_mcp_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frida-analykit MCP server over stdio.")
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=1200,
        help="Close the active Frida session after this many idle seconds; use 0 to disable idle cleanup.",
    )
    parser.add_argument(
        "--name",
        default="frida-analykit-mcp",
        help="Override the MCP server name advertised during initialization.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    manager = AsyncDebugSessionManager(idle_timeout_seconds=args.idle_timeout)
    server = build_mcp_server(manager, name=args.name)
    server.run(transport="stdio")
    return 0
