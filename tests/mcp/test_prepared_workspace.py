from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from frida_analykit.config import AppConfig
from frida_analykit.mcp.config import MCPStartupConfig
from frida_analykit.mcp.prepared import PreparedSessionOpenRequest, PreparedWorkspaceManager


def test_prepared_workspace_generates_bundle_config_and_cache_hit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[Path] = []

    def fake_build_agent_bundle(project, *, install=False, env=None):
        del install
        assert env is not None
        calls.append(project.project_dir)
        project.bundle_path.write_text("// built\n", encoding="utf-8")
        return project.bundle_path

    monkeypatch.setattr(
        "frida_analykit.mcp.prepared.service.build_agent_bundle",
        fake_build_agent_bundle,
    )

    manager = PreparedWorkspaceManager(
        startup_config=MCPStartupConfig.model_validate(
            {
                "server": {
                    "host": "usb",
                    "device": "SERIAL123",
                    "path": "/data/local/tmp/frida-server",
                },
                "agent": {
                    "datadir": str(tmp_path / "artifacts" / "data"),
                    "stdout": str(tmp_path / "artifacts" / "logs" / "outerr.log"),
                },
                "script": {
                    "dextools": {"output_dir": str(tmp_path / "artifacts" / "dex")},
                    "elftools": {"output_dir": str(tmp_path / "artifacts" / "elf")},
                    "nettools": {"ssl_log_secret": str(tmp_path / "artifacts" / "ssl")},
                },
            }
        ),
        cache_root=tmp_path / "prepared-cache",
        now_fn=lambda: datetime(2026, 4, 2, tzinfo=timezone.utc),
    )
    request = PreparedSessionOpenRequest(
        app="com.example.demo",
        mode="attach",
        template="dex_probe",
        capabilities=["helper"],
        bootstrap_source='console.log("bootstrap-ready")',
    )

    first = manager.prepare(request)
    second = manager.prepare(request)
    config = AppConfig.from_file(first.manifest.config_path)
    index_source = (first.manifest.workspace_root / "index.ts").read_text(encoding="utf-8")

    assert first.cache_hit is False
    assert first.build_performed is True
    assert second.cache_hit is True
    assert second.build_performed is False
    assert calls == [first.manifest.workspace_root]
    assert first.manifest.capabilities == ["rpc", "dex", "helper"]
    assert first.manifest.bootstrap_kind == "source"
    assert first.manifest.bootstrap_source == 'console.log("bootstrap-ready")'
    assert 'import "@zsa233/frida-analykit-agent/rpc"' in index_source
    assert 'import "@zsa233/frida-analykit-agent/dex"' in index_source
    assert 'import "@zsa233/frida-analykit-agent/helper"' in index_source
    assert 'import "./bootstrap.inline.ts"' in index_source
    assert 'console.log("bootstrap-ready")' in (first.manifest.workspace_root / "bootstrap.inline.ts").read_text(encoding="utf-8")
    assert config.app == "com.example.demo"
    assert config.server.host == "usb"
    assert config.server.device == "SERIAL123"
    assert config.server.path == "/data/local/tmp/frida-server"
    assert config.agent.datadir == (tmp_path / "artifacts" / "data").resolve()
    assert config.agent.stdout == (tmp_path / "artifacts" / "logs" / "outerr.log").resolve()
    assert config.agent.stderr == (tmp_path / "artifacts" / "logs" / "outerr.log").resolve()
    assert config.script.dextools.output_dir == (tmp_path / "artifacts" / "dex").resolve()
    assert config.script.elftools.output_dir == (tmp_path / "artifacts" / "elf").resolve()
    assert config.script.nettools.ssl_log_secret == (tmp_path / "artifacts" / "ssl").resolve()
    assert config.jsfile == first.manifest.bundle_path
    assert first.manifest.config_path.name == "config.toml"


def test_prepared_workspace_prune_respects_protected_signatures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_build_agent_bundle(project, *, install=False, env=None):
        del install, env
        project.bundle_path.write_text("// built\n", encoding="utf-8")
        return project.bundle_path

    monkeypatch.setattr(
        "frida_analykit.mcp.prepared.service.build_agent_bundle",
        fake_build_agent_bundle,
    )

    tick = {"value": 0}

    def now() -> datetime:
        tick["value"] += 1
        return datetime(2026, 4, 2, 0, 0, tick["value"], tzinfo=timezone.utc)

    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache", now_fn=now)
    first = manager.prepare(PreparedSessionOpenRequest(app="com.example.one", mode="attach"))
    second = manager.prepare(PreparedSessionOpenRequest(app="com.example.two", mode="attach"))

    deleted, skipped = manager.prune(all_unused=True, protected_signatures={second.manifest.signature})

    assert deleted == [first.manifest.signature]
    assert skipped == [second.manifest.signature]
    assert manager.inspect(first.manifest.signature) is None
    assert manager.inspect(second.manifest.signature) is not None


def test_prepared_workspace_accepts_bootstrap_path(tmp_path: Path, monkeypatch) -> None:
    def fake_build_agent_bundle(project, *, install=False, env=None):
        del install, env
        project.bundle_path.write_text("// built\n", encoding="utf-8")
        return project.bundle_path

    monkeypatch.setattr(
        "frida_analykit.mcp.prepared.service.build_agent_bundle",
        fake_build_agent_bundle,
    )

    bootstrap_path = tmp_path / "hooks.ts"
    bootstrap_path.write_text('console.log("from-file")\n', encoding="utf-8")
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    result = manager.prepare(
        PreparedSessionOpenRequest(
            app="com.example.demo",
            mode="spawn",
            bootstrap_path=str(bootstrap_path),
        )
    )
    index_source = (result.manifest.workspace_root / "index.ts").read_text(encoding="utf-8")
    copied_source = (result.manifest.workspace_root / "bootstrap.user.ts").read_text(encoding="utf-8")

    assert result.manifest.bootstrap_kind == "path"
    assert result.manifest.bootstrap_path == bootstrap_path.resolve()
    assert result.manifest.bootstrap_source is None
    assert 'import "./bootstrap.user.ts"' in index_source
    assert copied_source == 'console.log("from-file")\n'
