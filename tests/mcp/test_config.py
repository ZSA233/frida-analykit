from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from frida_analykit.mcp import cli
from frida_analykit.mcp.config import MCPStartupConfigError, load_mcp_startup_config
from frida_analykit.mcp.models import (
    QuickPathCheckSummary,
    QuickPathCompileProbeSummary,
    QuickPathReadinessSummary,
    QuickPathToolchainSummary,
)


def _quick_ready_summary(cache_root: Path) -> QuickPathReadinessSummary:
    return QuickPathReadinessSummary(
        state="ready",
        checked_at=datetime(2026, 4, 3),
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


def _quick_failed_summary(cache_root: Path, *, message: str) -> QuickPathReadinessSummary:
    return QuickPathReadinessSummary(
        state="failed",
        checked_at=datetime(2026, 4, 3),
        message=message,
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
            state="failed",
            path=None,
            detail=message,
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


def test_load_mcp_startup_config_uses_defaults_without_file() -> None:
    config = load_mcp_startup_config(None)

    assert config.source_path is None
    assert config.mcp.idle_timeout_seconds == 1200
    assert config.server.host == "127.0.0.1:27042"
    assert config.server.path == "frida-server"
    assert config.session_root(prepared_cache_root=Path("/tmp/prepared-cache")) == (
        Path("/tmp/prepared-cache") / "sessions"
    ).resolve()


def test_load_mcp_startup_config_resolves_relative_paths_against_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.toml"
    config_path.write_text(
        """
[mcp]
prepared_cache_root = "./cache"
session_root = "./root"

[server]
host = "usb"
device = "SERIAL123"
path = "/data/local/tmp/frida-server"

[agent]
datadir = "./agent-data"
stdout = "./logs/out.log"
stderr = "./logs/err.log"

[script.dextools]
output_dir = "./dex"

[script.elftools]
output_dir = "./elf"

[script.nettools]
output_dir = "./ssl"
""".strip(),
        encoding="utf-8",
    )

    config = load_mcp_startup_config(config_path)

    assert config.source_path == config_path.resolve()
    assert config.source_path_raw == str(config_path)
    assert config.mcp.prepared_cache_root == (tmp_path / "cache").resolve()
    assert config.mcp.session_root == (tmp_path / "root").resolve()
    assert config.agent.datadir == Path("agent-data")
    assert config.agent.stdout == Path("logs/out.log")
    assert config.agent.stderr == Path("logs/err.log")
    assert config.script.dextools.output_dir == Path("dex")
    assert config.script.elftools.output_dir == Path("elf")
    assert config.script.nettools.output_dir == Path("ssl")


def test_load_mcp_startup_config_rejects_duplicate_session_root_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "bad.toml"
    config_path.write_text(
        """
[mcp]
session_root = "./root"
session_history_root = "./legacy"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(MCPStartupConfigError, match="session_root"):
        load_mcp_startup_config(config_path)


def test_load_mcp_startup_config_rejects_unknown_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "bad.toml"
    config_path.write_text(
        """
[server]
host = "usb"
unexpected = "boom"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(MCPStartupConfigError, match="invalid MCP startup config"):
        load_mcp_startup_config(config_path)


def test_mcp_cli_loads_startup_config_and_builds_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "mcp.toml"
    config_path.write_text(
        """
[mcp]
idle_timeout_seconds = 33
prepared_cache_root = "./prepared"

[server]
host = "local"
""".strip(),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    class FakeManager:
        def __init__(self, **kwargs) -> None:
            captured["manager_kwargs"] = kwargs

        async def aclose(self) -> None:
            captured["closed"] = True

    def fake_build_mcp_server(manager, *, name: str):
        captured["manager"] = manager
        captured["name"] = name
        return object()

    def fake_serve_stdio(server, *, shutdown_message: str, stderr) -> int:
        captured["server"] = server
        captured["shutdown_message"] = shutdown_message
        captured["stderr"] = stderr
        return 0

    monkeypatch.setattr(
        cli.PreparedWorkspaceManager,
        "startup_warmup",
        lambda self: _quick_ready_summary(self.cache_root),
    )
    monkeypatch.setattr(cli, "DebugSessionManager", FakeManager)
    monkeypatch.setattr(cli, "build_mcp_server", fake_build_mcp_server)
    monkeypatch.setattr(cli, "serve_stdio", fake_serve_stdio)

    exit_code = cli.main(["--config", str(config_path), "--name", "demo-mcp"])

    manager_kwargs = captured["manager_kwargs"]
    prepared_workspace = manager_kwargs["prepared_workspace"]
    startup_config = manager_kwargs["startup_config"]
    streams = capsys.readouterr()
    assert exit_code == 0
    assert manager_kwargs["idle_timeout_seconds"] == 33
    assert isinstance(manager_kwargs["startup_started_at"], datetime)
    assert len(manager_kwargs["startup_instance_id"]) == 12
    assert manager_kwargs["startup_quick_path_summary"].state == "ready"
    assert prepared_workspace.cache_root == (tmp_path / "prepared").resolve()
    assert startup_config.session_root(prepared_cache_root=prepared_workspace.cache_root) == (
        tmp_path / "prepared" / "sessions"
    ).resolve()
    assert startup_config.server.host == "local"
    assert captured["name"] == "demo-mcp"
    assert captured["shutdown_message"] == cli.MCP_SHUTDOWN_MESSAGE
    assert captured.get("closed") is None
    assert streams.out == ""
    assert "\x1b[" not in streams.err
    for text in (
        "frida-analykit-mcp",
        "demo-mcp",
        "Instance ID:",
        "Session Root:",
        "Quick Path:",
        "✓ ready",
        "● cache hit",
    ):
        assert text in streams.err


def test_mcp_cli_handles_ctrl_c_without_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    class FakeManager:
        def __init__(self, **kwargs) -> None:
            del kwargs

        async def aclose(self) -> None:
            captured["closed"] = True

    def fake_build_mcp_server(manager, *, name: str):
        captured["manager"] = manager
        captured["name"] = name
        return object()

    def fake_serve_stdio(server, *, shutdown_message: str, stderr) -> int:
        captured["server"] = server
        captured["shutdown_message"] = shutdown_message
        print(shutdown_message, file=stderr, flush=True)
        return 130

    monkeypatch.setattr(
        cli.PreparedWorkspaceManager,
        "startup_warmup",
        lambda self: _quick_ready_summary(self.cache_root),
    )
    monkeypatch.setattr(cli, "DebugSessionManager", FakeManager)
    monkeypatch.setattr(cli, "build_mcp_server", fake_build_mcp_server)
    monkeypatch.setattr(cli, "serve_stdio", fake_serve_stdio)

    exit_code = cli.main(["--name", "demo-mcp"])

    streams = capsys.readouterr()
    assert exit_code == 130
    assert captured["shutdown_message"] == cli.MCP_SHUTDOWN_MESSAGE
    assert captured.get("closed") is None
    assert streams.out == ""
    assert "received Ctrl+C, shutting down" in streams.err
    assert "KeyboardInterrupt" not in streams.err


def test_mcp_cli_fails_fast_after_banner_when_quick_warmup_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_build_mcp_server(manager, *, name: str):
        captured["manager"] = manager
        captured["name"] = name
        raise AssertionError("server should not be built when startup warmup fails")

    monkeypatch.setattr(
        cli.PreparedWorkspaceManager,
        "startup_warmup",
        lambda self: _quick_failed_summary(
            self.cache_root,
            message="quick path requires `frida-compile` in the MCP environment PATH",
        ),
    )
    monkeypatch.setattr(cli, "build_mcp_server", fake_build_mcp_server)

    exit_code = cli.main(["--name", "demo-mcp"])

    streams = capsys.readouterr()
    assert exit_code == 1
    assert captured == {}
    assert streams.out == ""
    assert "Quick Path:" in streams.err
    assert "✗ failed" in streams.err
    assert "quick-path warmup failed" in streams.err
    assert "frida-compile" in streams.err


def test_render_startup_banner_only_uses_ansi_when_enabled(tmp_path: Path) -> None:
    quick_path = _quick_ready_summary(tmp_path / "prepared-cache")

    plain = cli.render_startup_banner(
        name="demo-mcp",
        instance_id="123456789abc",
        config_path=None,
        prepared_cache_root=tmp_path / "prepared-cache",
        session_root=tmp_path / "prepared-cache" / "sessions",
        host="127.0.0.1:27042",
        device=None,
        server_path="frida-server",
        idle_timeout_seconds=1200,
        updated=datetime(2026, 4, 3),
        quick_path=quick_path,
        colorize=False,
    )
    colored = cli.render_startup_banner(
        name="demo-mcp",
        instance_id="123456789abc",
        config_path=None,
        prepared_cache_root=tmp_path / "prepared-cache",
        session_root=tmp_path / "prepared-cache" / "sessions",
        host="127.0.0.1:27042",
        device=None,
        server_path="frida-server",
        idle_timeout_seconds=1200,
        updated=datetime(2026, 4, 3),
        quick_path=quick_path,
        colorize=True,
    )

    assert "\x1b[" not in plain
    assert "\x1b[" in colored
    assert "✓ ready" in plain
    assert "● cache hit" in plain
