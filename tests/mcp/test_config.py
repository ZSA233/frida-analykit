from __future__ import annotations

from pathlib import Path

import pytest

from frida_analykit.mcp import cli
from frida_analykit.mcp.config import MCPStartupConfigError, load_mcp_startup_config


def test_load_mcp_startup_config_uses_defaults_without_file() -> None:
    config = load_mcp_startup_config(None)

    assert config.source_path is None
    assert config.mcp.idle_timeout_seconds == 1200
    assert config.server.host == "127.0.0.1:27042"
    assert config.server.path == "frida-server"


def test_load_mcp_startup_config_resolves_relative_paths_against_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.toml"
    config_path.write_text(
        """
[mcp]
prepared_cache_root = "./cache"

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
ssl_log_secret = "./ssl"
""".strip(),
        encoding="utf-8",
    )

    config = load_mcp_startup_config(config_path)

    assert config.source_path == config_path.resolve()
    assert config.mcp.prepared_cache_root == (tmp_path / "cache").resolve()
    assert config.agent.datadir == (tmp_path / "agent-data").resolve()
    assert config.agent.stdout == (tmp_path / "logs" / "out.log").resolve()
    assert config.agent.stderr == (tmp_path / "logs" / "err.log").resolve()
    assert config.script.dextools.output_dir == (tmp_path / "dex").resolve()
    assert config.script.elftools.output_dir == (tmp_path / "elf").resolve()
    assert config.script.nettools.ssl_log_secret == (tmp_path / "ssl").resolve()


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


def test_mcp_cli_loads_startup_config_and_builds_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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

    class FakeServer:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    def fake_build_mcp_server(manager, *, name: str):
        captured["manager"] = manager
        captured["name"] = name
        return FakeServer()

    monkeypatch.setattr(cli, "DebugSessionManager", FakeManager)
    monkeypatch.setattr(cli, "build_mcp_server", fake_build_mcp_server)

    exit_code = cli.main(["--config", str(config_path), "--name", "demo-mcp"])

    manager_kwargs = captured["manager_kwargs"]
    prepared_workspace = manager_kwargs["prepared_workspace"]
    startup_config = manager_kwargs["startup_config"]
    assert exit_code == 0
    assert manager_kwargs["idle_timeout_seconds"] == 33
    assert prepared_workspace.cache_root == (tmp_path / "prepared").resolve()
    assert startup_config.server.host == "local"
    assert captured["name"] == "demo-mcp"
    assert captured["transport"] == "stdio"
