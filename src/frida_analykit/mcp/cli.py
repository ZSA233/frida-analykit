from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .._version import __version__
from .config import MCPStartupConfigError, load_mcp_startup_config
from .manager import DebugSessionManager
from .models import QuickPathReadinessSummary
from .prepared import PreparedWorkspaceManager
from .server import build_mcp_server
from .stdio import serve_stdio

MCP_BANNER_HEADER = """\
frida-analykit-mcp
=================="""
MCP_SHUTDOWN_MESSAGE = "[frida-analykit-mcp] received Ctrl+C, shutting down..."
MCP_STARTUP_FAILURE_PREFIX = "[frida-analykit-mcp] quick-path warmup failed:"
_ANSI_RESET = "\033[0m"
_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"
_ANSI_CYAN = "\033[36m"


def _display_path(path: Path | None) -> str:
    if path is None:
        return "<built-in defaults>"
    rendered = path.as_posix()
    if len(rendered) <= 72:
        return rendered
    return ".../" + "/".join(path.parts[-4:])


def _supports_color() -> bool:
    return bool(getattr(sys.stderr, "isatty", lambda: False)())


def _style(text: str, *, color: str, colorize: bool) -> str:
    if not colorize:
        return text
    return f"{color}{text}{_ANSI_RESET}"


def _state_badge(state: str, *, colorize: bool) -> str:
    normalized = state.lower()
    if normalized in {"ready", "installed", "compiled"}:
        return _style("✓", color=_ANSI_GREEN, colorize=colorize)
    if normalized in {"cache_hit", "skipped"}:
        return _style("●", color=_ANSI_CYAN, colorize=colorize)
    return _style("✗", color=_ANSI_RED, colorize=colorize)


def _render_quick_status_line(
    *,
    label: str,
    state: str,
    value: str | None,
    detail: str | None,
    colorize: bool,
) -> str:
    parts = [f"{_state_badge(state, colorize=colorize)} {state.replace('_', ' ')}"]
    if value:
        parts.append(value)
    if detail:
        parts.append(detail)
    return f"  - {label:<14} {' | '.join(parts)}"


def render_startup_banner(
    *,
    name: str,
    instance_id: str,
    config_path: Path | None,
    prepared_cache_root: Path,
    session_root: Path,
    host: str,
    device: str | None,
    server_path: str,
    idle_timeout_seconds: int,
    updated: datetime,
    quick_path: QuickPathReadinessSummary,
    colorize: bool = False,
) -> str:
    def item(label: str, value: str) -> str:
        return f"  - {label:<14} {value}"

    lines = [
        MCP_BANNER_HEADER,
        f"  v{__version__} ready at {updated.strftime('%H:%M:%S')}",
        "",
        item("Name:", name),
        item("Instance ID:", instance_id),
        item("Transport:", "stdio (stdin/stdout)"),
        item("Config:", _display_path(config_path)),
        item("Host:", host),
        item("Device:", device or "<default>"),
        item("Server Path:", server_path),
        item("Prepared Cache:", _display_path(prepared_cache_root)),
        item("Session Root:", _display_path(session_root)),
        item("Idle Timeout:", "disabled" if idle_timeout_seconds == 0 else f"{idle_timeout_seconds}s"),
        "",
        "Quick Path:",
        _render_quick_status_line(
            label="Overall:",
            state=quick_path.state,
            value=None,
            detail=quick_path.message,
            colorize=colorize,
        ),
        _render_quick_status_line(
            label="Cache Root:",
            state=quick_path.cache_root.state,
            value=_display_path(quick_path.cache_root.path),
            detail=quick_path.cache_root.detail,
            colorize=colorize,
        ),
        _render_quick_status_line(
            label="frida-compile:",
            state=quick_path.frida_compile.state,
            value=_display_path(quick_path.frida_compile.path),
            detail=quick_path.frida_compile.detail,
            colorize=colorize,
        ),
        _render_quick_status_line(
            label="npm:",
            state=quick_path.npm.state,
            value=_display_path(quick_path.npm.path),
            detail=quick_path.npm.detail,
            colorize=colorize,
        ),
        _render_quick_status_line(
            label="Toolchain:",
            state=quick_path.shared_toolchain.state,
            value=_display_path(quick_path.shared_toolchain.root),
            detail=quick_path.shared_toolchain.detail,
            colorize=colorize,
        ),
        _render_quick_status_line(
            label="Compile Probe:",
            state=quick_path.compile_probe.state,
            value=_display_path(quick_path.compile_probe.bundle_path),
            detail=quick_path.compile_probe.last_error or quick_path.compile_probe.detail,
            colorize=colorize,
        ),
        "",
        "  stderr is reserved for startup/log visibility; MCP protocol remains on stdin/stdout.",
        "",
    ]
    return "\n".join(lines)


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
    startup_started_at = datetime.now(timezone.utc)
    startup_instance_id = uuid4().hex[:12]
    prepared_workspace = PreparedWorkspaceManager(startup_config=startup_config)
    colorize = _supports_color()
    try:
        quick_path = prepared_workspace.startup_warmup()
    except KeyboardInterrupt:
        print(MCP_SHUTDOWN_MESSAGE, file=sys.stderr, flush=True)
        return 130
    print(
        render_startup_banner(
            name=args.name,
            instance_id=startup_instance_id,
            config_path=startup_config.source_path,
            prepared_cache_root=prepared_workspace.cache_root,
            session_root=startup_config.session_root(
                prepared_cache_root=prepared_workspace.cache_root
            ),
            host=startup_config.server.host,
            device=startup_config.server.device,
            server_path=startup_config.server.path,
            idle_timeout_seconds=idle_timeout,
            updated=startup_started_at.astimezone(),
            quick_path=quick_path,
            colorize=colorize,
        ),
        file=sys.stderr,
        flush=True,
    )
    if quick_path.state != "ready":
        if quick_path.message:
            print(f"{MCP_STARTUP_FAILURE_PREFIX} {quick_path.message}", file=sys.stderr, flush=True)
        return 1
    manager = DebugSessionManager(
        idle_timeout_seconds=idle_timeout,
        prepared_workspace=prepared_workspace,
        startup_config=startup_config,
        startup_instance_id=startup_instance_id,
        startup_started_at=startup_started_at,
        startup_quick_path_summary=quick_path,
    )
    server = build_mcp_server(manager, name=args.name)
    return serve_stdio(server, shutdown_message=MCP_SHUTDOWN_MESSAGE, stderr=sys.stderr)
