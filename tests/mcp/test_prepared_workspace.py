from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from frida_analykit.config import AppConfig
from frida_analykit.mcp.config import MCPStartupConfig
from frida_analykit.mcp.prepared import PreparedSessionOpenRequest, PreparedWorkspaceError, PreparedWorkspaceManager
from frida_analykit.mcp.prepared import service as prepared_service
from frida_analykit.workspace import workspace_build_resources

REPO_ROOT = Path(__file__).resolve().parents[2]

_EXPECTED_RETAIN_IMPORTS = {
    "config": ("@zsa233/frida-analykit-agent/config", "Config"),
    "bridges": ("@zsa233/frida-analykit-agent/bridges", "Java"),
    "helper": ("@zsa233/frida-analykit-agent/helper", "help"),
    "process": ("@zsa233/frida-analykit-agent/process", "proc"),
    "jni": ("@zsa233/frida-analykit-agent/jni", "JNIEnv"),
    "ssl": ("@zsa233/frida-analykit-agent/ssl", "SSLTools"),
    "elf": ("@zsa233/frida-analykit-agent/elf", "ElfTools"),
    "dex": ("@zsa233/frida-analykit-agent/dex", "DexTools"),
    "native_libssl": ("@zsa233/frida-analykit-agent/native/libssl", "Libssl"),
    "native_libart": ("@zsa233/frida-analykit-agent/native/libart", "Libart"),
    "native_libc": ("@zsa233/frida-analykit-agent/native/libc", "Libc"),
}


def _patch_quick_build(
    monkeypatch: pytest.MonkeyPatch,
    *,
    calls: list[tuple[str, Path]] | None = None,
    fail_compile: str | None = None,
) -> None:
    original_which = prepared_service.shutil.which

    def fake_which(command: str) -> str | None:
        if command == "npm":
            return "/usr/bin/npm"
        if command == "frida-compile":
            return "/usr/bin/frida-compile"
        return original_which(command)

    def fake_run_subprocess(
        command: list[str],
        *,
        cwd: Path,
        env,
        error_prefix: str,
    ) -> None:
        del env, error_prefix
        executable = Path(command[0]).name
        if calls is not None:
            calls.append((executable, cwd))
        if executable == "npm":
            node_modules = cwd / "node_modules"
            prepared_service._package_install_path(node_modules, prepared_service.AGENT_PACKAGE_NAME).mkdir(
                parents=True, exist_ok=True
            )
            prepared_service._package_install_path(node_modules, "@types/frida-gum").mkdir(
                parents=True, exist_ok=True
            )
            prepared_service._package_install_path(node_modules, "typescript").mkdir(parents=True, exist_ok=True)
            return
        if executable == "frida-compile":
            if fail_compile is not None:
                raise PreparedWorkspaceError(fail_compile)
            (cwd / "_agent.js").write_text("// built\n", encoding="utf-8")
            return
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(prepared_service.shutil, "which", fake_which)
    monkeypatch.setattr(PreparedWorkspaceManager, "_run_subprocess", staticmethod(fake_run_subprocess))


def _quick_npm_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    npm_cache_dir = tmp_path / ".npm-cache"
    npm_cache_dir.mkdir(parents=True, exist_ok=True)
    env["npm_config_cache"] = str(npm_cache_dir)
    return env


def _pack_local_runtime(tmp_path: Path, *, npm_env: dict[str, str]) -> Path:
    package_name = (
        subprocess.check_output(
            ["npm", "pack", "./packages/frida-analykit-agent"],
            cwd=REPO_ROOT,
            env=npm_env,
            text=True,
        )
        .strip()
        .splitlines()[-1]
    )
    source = REPO_ROOT / package_name
    destination = tmp_path / package_name
    shutil.move(source, destination)
    return destination


def _startup_config(tmp_path: Path) -> MCPStartupConfig:
    del tmp_path
    return MCPStartupConfig.model_validate(
        {
            "server": {
                "host": "usb",
                "device": "SERIAL123",
                "path": "/data/local/tmp/frida-server",
            },
            "agent": {
                "datadir": "./data",
                "stdout": "./logs/outerr.log",
            },
            "script": {
                "dextools": {"output_dir": "./data/dextools"},
                "elftools": {"output_dir": "./data/elftools"},
                "nettools": {"output_dir": "./data/nettools"},
            },
        }
    )


def _configured_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    calls: list[tuple[str, Path]] | None = None,
) -> PreparedWorkspaceManager:
    _patch_quick_build(monkeypatch, calls=calls)
    return PreparedWorkspaceManager(
        startup_config=_startup_config(tmp_path),
        cache_root=tmp_path / "prepared-cache",
        now_fn=lambda: datetime(2026, 4, 2, tzinfo=timezone.utc),
    )


def test_startup_warmup_installs_shared_toolchain_and_runs_compile_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Path]] = []
    _patch_quick_build(monkeypatch, calls=calls)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    summary = manager.startup_warmup()

    assert summary.state == "ready"
    assert summary.cache_root.state == "ready"
    assert summary.frida_compile.state == "ready"
    assert summary.npm.state == "ready"
    assert summary.shared_toolchain.state == "installed"
    assert summary.compile_probe.state == "compiled"
    assert summary.compile_probe.bundle_path.is_file()
    assert calls == [
        ("npm", summary.shared_toolchain.root),
        ("frida-compile", summary.compile_probe.workspace_root),
    ]


def test_quick_subprocesses_do_not_inherit_server_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(prepared_service.subprocess, "run", fake_run)

    PreparedWorkspaceManager._run_subprocess(
        ["frida-compile", "index.ts", "-o", "_agent.js", "-c"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin"},
        error_prefix="boom",
    )

    assert captured["command"] == ["frida-compile", "index.ts", "-o", "_agent.js", "-c"]
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL


def test_startup_warmup_reuses_shared_toolchain_cache_without_reinstall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Path]] = []
    _patch_quick_build(monkeypatch, calls=calls)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    first = manager.startup_warmup()
    second = manager.startup_warmup()

    assert first.state == "ready"
    assert first.shared_toolchain.state == "installed"
    assert second.state == "ready"
    assert second.shared_toolchain.state == "cache_hit"
    assert second.compile_probe.state == "compiled"
    assert calls == [
        ("npm", first.shared_toolchain.root),
        ("frida-compile", first.compile_probe.workspace_root),
        ("frida-compile", second.compile_probe.workspace_root),
    ]


def test_startup_warmup_reports_unwritable_cache_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_root = tmp_path / "prepared-cache"
    blocked_root.write_text("occupied\n", encoding="utf-8")
    original_which = prepared_service.shutil.which

    def fake_which(command: str) -> str | None:
        if command in {"npm", "frida-compile"}:
            return f"/usr/bin/{command}"
        return original_which(command)

    monkeypatch.setattr(prepared_service.shutil, "which", fake_which)
    manager = PreparedWorkspaceManager(cache_root=blocked_root)

    summary = manager.startup_warmup()

    assert summary.state == "failed"
    assert summary.cache_root.state == "failed"
    assert "writable prepared cache root" in (summary.cache_root.detail or "")
    assert summary.shared_toolchain.state == "skipped"
    assert summary.compile_probe.state == "skipped"


def test_startup_warmup_reports_missing_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_which = prepared_service.shutil.which

    def fake_which(command: str) -> str | None:
        if command == "frida-compile":
            return "/usr/bin/frida-compile"
        if command == "npm":
            return None
        return original_which(command)

    monkeypatch.setattr(prepared_service.shutil, "which", fake_which)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    summary = manager.startup_warmup()

    assert summary.state == "failed"
    assert summary.npm.state == "failed"
    assert "requires `npm`" in (summary.npm.detail or "")
    assert summary.shared_toolchain.state == "skipped"
    assert summary.compile_probe.state == "skipped"


def test_startup_warmup_reuses_cached_toolchain_without_npm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Path]] = []
    _patch_quick_build(monkeypatch, calls=calls)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    first = manager.startup_warmup()
    original_which = prepared_service.shutil.which

    def fake_which(command: str) -> str | None:
        if command == "frida-compile":
            return "/usr/bin/frida-compile"
        if command == "npm":
            return None
        return original_which(command)

    monkeypatch.setattr(prepared_service.shutil, "which", fake_which)

    second = manager.startup_warmup()

    assert first.state == "ready"
    assert first.shared_toolchain.state == "installed"
    assert second.state == "ready"
    assert second.npm.state == "skipped"
    assert "did not require npm" in (second.npm.detail or "")
    assert second.shared_toolchain.state == "cache_hit"
    assert second.compile_probe.state == "compiled"
    assert calls == [
        ("npm", first.shared_toolchain.root),
        ("frida-compile", first.compile_probe.workspace_root),
        ("frida-compile", second.compile_probe.workspace_root),
    ]


def test_startup_warmup_reports_compile_probe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quick_build(monkeypatch, fail_compile="compile exploded")
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    summary = manager.startup_warmup()

    assert summary.state == "failed"
    assert summary.shared_toolchain.state == "installed"
    assert summary.compile_probe.state == "failed"
    assert summary.compile_probe.last_error == "compile exploded"


def test_startup_warmup_repairs_corrupted_probe_workspace_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quick_build(monkeypatch)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")
    probe_root = manager._startup_probe_root_for_spec(prepared_service.default_agent_package_spec())
    probe_root.parent.mkdir(parents=True, exist_ok=True)
    probe_root.write_text("occupied\n", encoding="utf-8")

    summary = manager.startup_warmup()

    assert summary.state == "ready"
    assert summary.compile_probe.state == "compiled"
    assert summary.compile_probe.workspace_root == probe_root
    assert probe_root.is_dir()
    assert summary.compile_probe.bundle_path.is_file()


def test_toolchain_root_digest_changes_when_quick_toolchain_versions_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")
    original_root = manager._toolchain_root_for_spec("@zsa233/frida-analykit-agent@1.0.0")

    monkeypatch.setattr(prepared_service, "_QUICK_TYPESCRIPT_VERSION", "^9.9.9")

    updated_root = manager._toolchain_root_for_spec("@zsa233/frida-analykit-agent@1.0.0")

    assert updated_root != original_root


def test_prepared_workspace_cache_hit_reuses_existing_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Path]] = []
    manager = _configured_manager(tmp_path, monkeypatch, calls=calls)
    request = PreparedSessionOpenRequest(
        app="com.example.demo",
        mode="attach",
        template="dex_probe",
        capabilities=["helper"],
        bootstrap_source='console.log("bootstrap-ready")',
    )

    first = manager.prepare(request)
    second = manager.prepare(request)

    assert first.cache_hit is False
    assert first.build_performed is True
    assert second.cache_hit is True
    assert second.build_performed is False
    assert first.manifest.signature == second.manifest.signature
    assert first.manifest.capabilities == ["rpc", "dex", "helper"]
    assert calls == [
        ("npm", manager._toolchain_root_for_spec(first.manifest.agent_package_spec)),
        ("frida-compile", first.manifest.workspace_root),
    ]


def test_prepared_workspace_uses_minimal_toolchain_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _configured_manager(tmp_path, monkeypatch)
    result = manager.prepare(PreparedSessionOpenRequest(app="com.example.demo", mode="attach"))

    package = json.loads((result.manifest.workspace_root / "package.json").read_text(encoding="utf-8"))
    tsconfig = json.loads((result.manifest.workspace_root / "tsconfig.json").read_text(encoding="utf-8"))
    toolchain_package = json.loads(
        (manager._toolchain_root_for_spec(result.manifest.agent_package_spec) / "package.json").read_text(
            encoding="utf-8"
        )
    )

    assert package["dependencies"] == {"@zsa233/frida-analykit-agent": result.manifest.agent_package_spec}
    assert "devDependencies" not in package
    assert "frida-compile" not in json.dumps(package)
    assert "@types/node" not in json.dumps(package)
    assert tsconfig["compilerOptions"]["types"] == ["frida-gum"]
    assert "node" not in tsconfig["compilerOptions"]["types"]
    assert "frida-compile" not in json.dumps(toolchain_package)
    assert "@types/node" not in json.dumps(toolchain_package)


def test_prepared_workspace_normalizes_npm_cache_path_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quick_build(monkeypatch)
    occupied_parent = tmp_path / "occupied-parent"
    occupied_parent.write_text("not-a-directory\n", encoding="utf-8")
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")
    manager._build_resources = workspace_build_resources(occupied_parent / "nested")

    with pytest.raises(PreparedWorkspaceError, match="writable npm cache"):
        manager.prepare(PreparedSessionOpenRequest(app="com.example.demo", mode="attach"))

    manifest_path = next((tmp_path / "prepared-cache").rglob("prepared.json"))
    manifest = manager.inspect(manifest_path.parent.name)
    assert manifest is not None
    assert manifest.last_prepare_outcome == "failed"
    assert "writable npm cache" in (manifest.last_build_error or "")


@pytest.mark.parametrize(
    ("capability", "module_path", "retain_export"),
    [(capability, *mapping) for capability, mapping in sorted(_EXPECTED_RETAIN_IMPORTS.items())],
)
def test_prepared_workspace_generates_explicit_retain_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
    module_path: str,
    retain_export: str,
) -> None:
    _patch_quick_build(monkeypatch)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    result = manager.prepare(
        PreparedSessionOpenRequest(
            app="com.example.demo",
            mode="attach",
            capabilities=[capability],
        )
    )
    index_source = (result.manifest.workspace_root / "index.ts").read_text(encoding="utf-8")

    assert 'import "@zsa233/frida-analykit-agent/rpc"' in index_source
    assert f'import {{ {retain_export} }} from "{module_path}"' in index_source
    assert f"void {retain_export}" in index_source
    assert f'import "{module_path}"' not in index_source


def test_prepared_workspace_retain_exports_are_unique() -> None:
    retain_exports = list(prepared_service._CAPABILITY_RETAIN_EXPORTS.values())

    assert len(retain_exports) == len(set(retain_exports))


def test_prepared_workspace_keeps_rpc_as_side_effect_import_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quick_build(monkeypatch)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    result = manager.prepare(PreparedSessionOpenRequest(app="com.example.demo", mode="attach"))
    index_source = (result.manifest.workspace_root / "index.ts").read_text(encoding="utf-8")

    assert 'import "@zsa233/frida-analykit-agent/rpc"' in index_source
    assert "void rpc" not in index_source
    assert 'from "@zsa233/frida-analykit-agent/rpc"' not in index_source


def test_prepared_workspace_treats_template_as_preset_and_capabilities_as_additive_preloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quick_build(monkeypatch)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    result = manager.prepare(
        PreparedSessionOpenRequest(
            app="com.example.demo",
            mode="attach",
            template="elf_probe",
            capabilities=["helper"],
        )
    )
    index_source = (result.manifest.workspace_root / "index.ts").read_text(encoding="utf-8")

    assert result.manifest.capabilities == ["rpc", "elf", "helper"]
    assert "@zsa233/frida-analykit-agent/elf/enhanced" not in index_source


def test_prepared_workspace_projects_startup_config_into_generated_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _configured_manager(tmp_path, monkeypatch)
    result = manager.prepare(PreparedSessionOpenRequest(app="com.example.demo", mode="attach"))

    config = AppConfig.from_file(result.manifest.config_path)
    config_text = result.manifest.config_path.read_text(encoding="utf-8")

    assert config.app == "com.example.demo"
    assert config.server.host == "usb"
    assert config.server.device == "SERIAL123"
    assert config.server.path == "/data/local/tmp/frida-server"
    assert 'datadir = "data"' in config_text
    assert 'stdout = "logs/outerr.log"' in config_text
    assert 'output_dir = "data/dextools"' in config_text
    assert 'output_dir = "data/nettools"' in config_text
    assert config.agent.datadir == (result.manifest.workspace_root / "data").resolve()
    assert config.agent.stdout == (result.manifest.workspace_root / "logs" / "outerr.log").resolve()
    assert config.agent.stderr == (result.manifest.workspace_root / "logs" / "outerr.log").resolve()
    assert config.script.dextools.output_dir == (result.manifest.workspace_root / "data" / "dextools").resolve()
    assert config.script.elftools.output_dir == (result.manifest.workspace_root / "data" / "elftools").resolve()
    assert config.script.nettools.output_dir == (
        result.manifest.workspace_root / "data" / "nettools"
    ).resolve()
    assert config.jsfile == result.manifest.bundle_path
    assert result.manifest.config_path.name == "config.toml"


def test_prepared_workspace_writes_inline_bootstrap_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quick_build(monkeypatch)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    result = manager.prepare(
        PreparedSessionOpenRequest(
            app="com.example.demo",
            mode="attach",
            bootstrap_source='console.log("bootstrap-ready")',
        )
    )
    index_source = (result.manifest.workspace_root / "index.ts").read_text(encoding="utf-8")

    assert result.manifest.bootstrap_kind == "source"
    assert result.manifest.bootstrap_source == 'console.log("bootstrap-ready")'
    assert 'import "./bootstrap.inline.ts"' not in index_source
    assert 'console.log("bootstrap-ready")' in index_source
    assert "Begin inlined bootstrap_source" in index_source
    assert not (result.manifest.workspace_root / "bootstrap.inline.ts").exists()


def test_prepared_workspace_accepts_bootstrap_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_quick_build(monkeypatch)

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


def test_prepared_workspace_rejects_bootstrap_path_with_relative_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quick_build(monkeypatch)

    bootstrap_path = tmp_path / "hooks.ts"
    bootstrap_path.write_text('import "./dep"\nconsole.log("from-file")\n', encoding="utf-8")
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    with pytest.raises(PreparedWorkspaceError, match="self-contained"):
        manager.prepare(
            PreparedSessionOpenRequest(
                app="com.example.demo",
                mode="spawn",
                bootstrap_path=str(bootstrap_path),
            )
        )


def test_prepared_workspace_prune_respects_protected_signatures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quick_build(monkeypatch)

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


def test_prepared_workspace_rejects_elf_enhanced_as_quick_capability() -> None:
    with pytest.raises(ValidationError, match="not supported as a quick-session preload capability"):
        PreparedSessionOpenRequest(
            app="com.example.demo",
            mode="attach",
            capabilities=["elf_enhanced"],
        )


def test_prepared_workspace_reuses_one_shared_toolchain_across_signatures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Path]] = []
    _patch_quick_build(monkeypatch, calls=calls)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")

    first = manager.prepare(PreparedSessionOpenRequest(app="com.example.one", mode="attach"))
    second = manager.prepare(PreparedSessionOpenRequest(app="com.example.two", mode="attach"))
    toolchain_root = manager._toolchain_root_for_spec(first.manifest.agent_package_spec)

    assert first.manifest.signature != second.manifest.signature
    assert calls == [
        ("npm", toolchain_root),
        ("frida-compile", first.manifest.workspace_root),
        ("frida-compile", second.manifest.workspace_root),
    ]


def test_prepared_workspace_reports_missing_frida_compile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_which = prepared_service.shutil.which

    def fake_which(command: str) -> str | None:
        if command == "frida-compile":
            return None
        if command == "npm":
            return "/usr/bin/npm"
        return original_which(command)

    monkeypatch.setattr(prepared_service.shutil, "which", fake_which)
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")
    request = PreparedSessionOpenRequest(app="com.example.demo", mode="attach")

    with pytest.raises(PreparedWorkspaceError, match="quick path requires `frida-compile` in the MCP environment PATH"):
        manager.prepare(request)

    manifest_path = next((tmp_path / "prepared-cache").rglob("prepared.json"))
    manifest = manager.inspect(manifest_path.parent.name)
    assert manifest is not None
    assert manifest.last_prepare_outcome == "failed"
    assert "frida-compile" in (manifest.last_build_error or "")


def test_prepared_workspace_persists_last_build_error_on_compile_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_quick_build(monkeypatch, fail_compile="compile exploded")
    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")
    request = PreparedSessionOpenRequest(app="com.example.demo", mode="attach")

    with pytest.raises(PreparedWorkspaceError, match="compile exploded"):
        manager.prepare(request)

    manifest_path = next((tmp_path / "prepared-cache").rglob("prepared.json"))
    manifest = manager.inspect(manifest_path.parent.name)
    assert manifest is not None
    assert manifest.last_prepare_outcome == "failed"
    assert manifest.last_build_error == "compile exploded"


@pytest.mark.scaffold
def test_prepared_workspace_real_quick_compile_uses_path_frida_compile_and_shared_runtime_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("FRIDA_ANALYKIT_ENABLE_NPM") != "1":
        pytest.skip("set FRIDA_ANALYKIT_ENABLE_NPM=1 to run npm quick-path smoke tests")
    if shutil.which("npm") is None:
        pytest.skip("npm is required for quick-path smoke tests")
    if shutil.which("frida-compile") is None:
        pytest.skip("frida-compile in PATH is required for quick-path smoke tests")

    local_types = REPO_ROOT / "node_modules" / "@types" / "frida-gum"
    local_typescript = REPO_ROOT / "node_modules" / "typescript"
    local_bridge = REPO_ROOT / "node_modules" / "frida-java-bridge"
    if not local_types.exists() or not local_typescript.exists() or not local_bridge.exists():
        pytest.skip("quick-path smoke test requires local repo node_modules for frida-gum, typescript, and frida-java-bridge")

    npm_env = _quick_npm_env(tmp_path)
    tarball = _pack_local_runtime(tmp_path, npm_env=npm_env)

    def ensure_shared_toolchain_with_local_runtime(
        self: PreparedWorkspaceManager,
        *,
        agent_package_spec: str,
        env,
    ) -> Path:
        del agent_package_spec
        toolchain_root = self._toolchain_root_for_spec(f"file:{tarball}")
        def local_toolchain_ready() -> bool:
            node_modules = toolchain_root / "node_modules"
            return (
                (toolchain_root / "package.json").is_file()
                and prepared_service._package_install_path(node_modules, prepared_service.AGENT_PACKAGE_NAME).is_dir()
                and prepared_service._package_install_path(node_modules, "@types/frida-gum").is_dir()
                and prepared_service._package_install_path(node_modules, "typescript").is_dir()
            )

        if local_toolchain_ready():
            return toolchain_root
        npm = prepared_service.shutil.which("npm")
        assert npm is not None
        toolchain_root.mkdir(parents=True, exist_ok=True)
        prepared_service._write_json(
            toolchain_root / "package.json",
            {
                "name": "frida-analykit-mcp-runtime-toolchain",
                "private": True,
                "type": "module",
                "dependencies": {
                    prepared_service.AGENT_PACKAGE_NAME: f"file:{tarball}",
                },
                "devDependencies": {
                    "@types/frida-gum": f"file:{local_types}",
                    "typescript": f"file:{local_typescript}",
                },
                "overrides": {
                    "frida-java-bridge": f"file:{local_bridge}",
                },
            },
        )
        prepared_service._remove_path(toolchain_root / "node_modules")
        prepared_service._remove_path(toolchain_root / "package-lock.json")
        self._run_subprocess(
            [npm, "install", "--ignore-scripts"],
            cwd=toolchain_root,
            env=env,
            error_prefix="failed to install quick-session runtime dependencies",
        )
        if not local_toolchain_ready():
            raise PreparedWorkspaceError(
                "quick-session runtime dependencies were installed, but the shared toolchain is still incomplete"
            )
        return toolchain_root

    monkeypatch.setattr(prepared_service, "default_agent_package_spec", lambda: f"file:{tarball}")
    monkeypatch.setattr(
        PreparedWorkspaceManager,
        "_ensure_shared_toolchain",
        ensure_shared_toolchain_with_local_runtime,
    )

    manager = PreparedWorkspaceManager(cache_root=tmp_path / "prepared-cache")
    result = manager.prepare(
        PreparedSessionOpenRequest(
            app="com.example.demo",
            mode="attach",
            template="dex_probe",
        )
    )
    toolchain_root = manager._toolchain_root_for_spec(f"file:{tarball}")
    bundle = result.manifest.bundle_path.read_text(encoding="utf-8")

    assert result.manifest.bundle_path.is_file()
    assert not (toolchain_root / "node_modules" / "frida").exists()
    assert "[DexTools]" in bundle
