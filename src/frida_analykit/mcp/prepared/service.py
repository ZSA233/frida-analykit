from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from ...config import AppConfig, DEFAULT_CONFIG_FILENAME
from ...frontend import build_agent_bundle, load_frontend_project
from ...scaffold import AGENT_PACKAGE_NAME, default_agent_package_spec, generate_dev_workspace
from ...workspace import (
    acquire_workspace_build_lock,
    prepare_workspace_npm_env,
    workspace_build_resources,
    write_workspace_config,
)
from .models import (
    BootstrapKind,
    PreparedArtifactConfig,
    PreparedArtifactManifest,
    PreparedSessionOpenRequest,
    PreparedWorkspaceBuildResult,
    QuickCapability,
    QuickTemplate,
)
from ..config import MCPStartupConfig

_MANIFEST_FILENAME = "prepared.json"
_SCHEMA_VERSION = 2
_BOOTSTRAP_INLINE_FILENAME = "bootstrap.inline.ts"
_BOOTSTRAP_FILE_STEM = "bootstrap.user"

_CAPABILITY_IMPORTS: dict[QuickCapability, str] = {
    "rpc": f"{AGENT_PACKAGE_NAME}/rpc",
    "config": f"{AGENT_PACKAGE_NAME}/config",
    "bridges": f"{AGENT_PACKAGE_NAME}/bridges",
    "helper": f"{AGENT_PACKAGE_NAME}/helper",
    "process": f"{AGENT_PACKAGE_NAME}/process",
    "jni": f"{AGENT_PACKAGE_NAME}/jni",
    "ssl": f"{AGENT_PACKAGE_NAME}/ssl",
    "elf": f"{AGENT_PACKAGE_NAME}/elf",
    "elf_enhanced": f"{AGENT_PACKAGE_NAME}/elf/enhanced",
    "dex": f"{AGENT_PACKAGE_NAME}/dex",
    "native_libssl": f"{AGENT_PACKAGE_NAME}/native/libssl",
    "native_libart": f"{AGENT_PACKAGE_NAME}/native/libart",
    "native_libc": f"{AGENT_PACKAGE_NAME}/native/libc",
}

_TEMPLATE_CAPABILITIES: dict[QuickTemplate, tuple[QuickCapability, ...]] = {
    "minimal": (),
    "process_probe": ("helper", "process"),
    "java_bridge": ("bridges", "jni"),
    "dex_probe": ("dex",),
    "ssl_probe": ("ssl",),
    "elf_probe": ("elf", "elf_enhanced"),
}

_TEMPLATE_HINTS: dict[QuickTemplate, str] = {
    "minimal": "Keep target-specific probes in MCP eval_js or install_snippet calls.",
    "process_probe": "Process helpers are preloaded for fast memory-map and process-state checks.",
    "java_bridge": "Java and JNI bridge helpers are preloaded for Android runtime inspection.",
    "dex_probe": "Dex helpers are preloaded for loader enumeration and dex validation flows.",
    "ssl_probe": "SSL helpers are preloaded for keylog or libssl-oriented validation.",
    "elf_probe": "ELF helpers are preloaded for module, symbol, and hook validation.",
}


class PreparedWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _PreparedBootstrap:
    kind: BootstrapKind
    source_text: str | None = None
    original_path: Path | None = None
    workspace_filename: str | None = None
    signature_path: str | None = None
    signature_hash: str | None = None

    @property
    def import_path(self) -> str | None:
        if self.workspace_filename is None:
            return None
        return f"./{self.workspace_filename}"


class PreparedWorkspaceManager:
    def __init__(
        self,
        *,
        startup_config: MCPStartupConfig | None = None,
        cache_root: str | Path | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._startup_config = startup_config or MCPStartupConfig()
        self._cache_root = (
            Path(cache_root).expanduser().resolve()
            if cache_root is not None
            else (
                self._startup_config.mcp.prepared_cache_root
                if self._startup_config.mcp.prepared_cache_root is not None
                else _default_prepared_cache_root()
            )
        )
        self._build_resources = workspace_build_resources(self._cache_root)
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    @property
    def cache_root(self) -> Path:
        return self._cache_root

    def prepare(self, request: PreparedSessionOpenRequest) -> PreparedWorkspaceBuildResult:
        validated = PreparedSessionOpenRequest.model_validate(request)
        package_spec = default_agent_package_spec()
        capabilities = _resolve_capabilities(validated.template, validated.capabilities)
        bootstrap = _resolve_bootstrap(validated)
        workspace_defaults = self._startup_config.workspace_write_kwargs()
        signature = _signature_for_request(
            app=validated.app,
            capabilities=capabilities,
            template=validated.template,
            bootstrap_kind=bootstrap.kind,
            bootstrap_path=bootstrap.signature_path,
            bootstrap_hash=bootstrap.signature_hash,
            bootstrap_source=validated.bootstrap_source,
            host=str(workspace_defaults["host"]),
            device=_optional_string(workspace_defaults["device"]),
            path=str(workspace_defaults["path"]),
            datadir=str(workspace_defaults["datadir"]),
            stdout=str(workspace_defaults["stdout"]),
            stderr=str(workspace_defaults["stderr"]),
            dextools_output_dir=str(workspace_defaults["dextools_output_dir"]),
            elftools_output_dir=str(workspace_defaults["elftools_output_dir"]),
            ssl_log_secret=str(workspace_defaults["ssl_log_secret"]),
            agent_package_spec=package_spec,
        )
        workspace_root = self._cache_root / signature
        manifest_path = workspace_root / _MANIFEST_FILENAME
        imports = [_CAPABILITY_IMPORTS[capability] for capability in capabilities]
        now = self._now_fn()

        workspace_root.mkdir(parents=True, exist_ok=True)
        generate_dev_workspace(workspace_root, force=True, agent_package_spec=package_spec)
        if bootstrap.source_text is not None and bootstrap.workspace_filename is not None:
            (workspace_root / bootstrap.workspace_filename).write_text(bootstrap.source_text, encoding="utf-8")
        (workspace_root / "index.ts").write_text(
            _render_index_source(
                template=validated.template,
                capabilities=capabilities,
                bootstrap_import=bootstrap.import_path,
            ),
            encoding="utf-8",
        )
        config = write_workspace_config(
            workspace_root / DEFAULT_CONFIG_FILENAME,
            app=validated.app,
            jsfile="_agent.js",
            host=str(workspace_defaults["host"]),
            path=str(workspace_defaults["path"]),
            device=_optional_string(workspace_defaults["device"]),
            datadir=workspace_defaults["datadir"],
            stdout=workspace_defaults["stdout"],
            stderr=workspace_defaults["stderr"],
            dextools_output_dir=workspace_defaults["dextools_output_dir"],
            elftools_output_dir=workspace_defaults["elftools_output_dir"],
            ssl_log_secret=workspace_defaults["ssl_log_secret"],
        )
        prepared_config = _artifact_config_from_app_config(config)

        manifest = self._load_manifest(manifest_path) or PreparedArtifactManifest(
            signature=signature,
            template=validated.template,
            capabilities=list(capabilities),
            imports=imports,
            agent_package_spec=package_spec,
            bootstrap_kind=bootstrap.kind,
            bootstrap_path=bootstrap.original_path,
            bootstrap_source=validated.bootstrap_source,
            workspace_root=workspace_root,
            config_path=config.source_path or (workspace_root / DEFAULT_CONFIG_FILENAME),
            bundle_path=workspace_root / "_agent.js",
            config=prepared_config,
        )
        manifest = manifest.model_copy(
            update={
                "template": validated.template,
                "capabilities": list(capabilities),
                "imports": imports,
                "agent_package_spec": package_spec,
                "bootstrap_kind": bootstrap.kind,
                "bootstrap_path": bootstrap.original_path,
                "bootstrap_source": validated.bootstrap_source,
                "workspace_root": workspace_root,
                "config_path": config.source_path or (workspace_root / DEFAULT_CONFIG_FILENAME),
                "bundle_path": workspace_root / "_agent.js",
                "config": prepared_config,
                "last_used_at": now,
            }
        )

        cache_hit = self._artifact_is_ready(manifest)
        build_performed = False
        if cache_hit:
            manifest = manifest.model_copy(
                update={
                    "build_ready": True,
                    "last_prepare_outcome": "cache_hit",
                    "last_prepared_at": now,
                }
            )
            self._write_manifest(manifest_path, manifest)
            return PreparedWorkspaceBuildResult(manifest=manifest, cache_hit=True, build_performed=False)

        build_performed = True
        env = prepare_workspace_npm_env(os.environ, self._build_resources)
        lock = acquire_workspace_build_lock(self._build_resources)
        try:
            project = load_frontend_project(config, project_dir=workspace_root)
            build_agent_bundle(project, install=True, env=env)
        except Exception as exc:
            manifest = manifest.model_copy(
                update={
                    "build_ready": False,
                    "last_prepare_outcome": "failed",
                    "last_build_error": str(exc),
                    "last_prepared_at": now,
                }
            )
            self._write_manifest(manifest_path, manifest)
            raise PreparedWorkspaceError(str(exc)) from exc
        finally:
            lock.release()

        manifest = manifest.model_copy(
            update={
                "build_ready": True,
                "last_prepare_outcome": "rebuilt",
                "last_build_error": None,
                "last_prepared_at": now,
            }
        )
        self._write_manifest(manifest_path, manifest)
        return PreparedWorkspaceBuildResult(manifest=manifest, cache_hit=False, build_performed=build_performed)

    def inspect(self, signature: str) -> PreparedArtifactManifest | None:
        manifest_path = self._cache_root / signature / _MANIFEST_FILENAME
        manifest = self._load_manifest(manifest_path)
        if manifest is None:
            return None
        if self._artifact_is_ready(manifest):
            return manifest.model_copy(update={"build_ready": True})
        return manifest.model_copy(update={"build_ready": False})

    def prune(
        self,
        *,
        signature: str | None = None,
        all_unused: bool = False,
        older_than_seconds: int | None = None,
        protected_signatures: set[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        protected = protected_signatures or set()
        deleted: list[str] = []
        skipped: list[str] = []
        candidates = list(self._iter_manifests())
        if signature is not None:
            candidates = [manifest for manifest in candidates if manifest.signature == signature]
        elif not all_unused and older_than_seconds is None:
            raise PreparedWorkspaceError(
                "prepared cache prune requires `signature`, `all_unused=true`, or `older_than_seconds`"
            )

        cutoff: datetime | None = None
        if older_than_seconds is not None:
            cutoff = self._now_fn() - timedelta(seconds=max(older_than_seconds, 0))

        for manifest in candidates:
            if manifest.signature in protected:
                skipped.append(manifest.signature)
                continue
            last_seen = manifest.last_used_at or manifest.last_prepared_at
            if cutoff is not None and last_seen is not None and last_seen > cutoff:
                continue
            if cutoff is not None and last_seen is None:
                stat_time = datetime.fromtimestamp(manifest.workspace_root.stat().st_mtime, tz=timezone.utc)
                if stat_time > cutoff:
                    continue
            shutil.rmtree(manifest.workspace_root, ignore_errors=True)
            deleted.append(manifest.signature)
        return deleted, skipped

    def _iter_manifests(self) -> list[PreparedArtifactManifest]:
        if not self._cache_root.exists():
            return []
        manifests: list[PreparedArtifactManifest] = []
        for child in self._cache_root.iterdir():
            if not child.is_dir():
                continue
            manifest = self._load_manifest(child / _MANIFEST_FILENAME)
            if manifest is not None:
                manifests.append(manifest)
        return manifests

    @staticmethod
    def _artifact_is_ready(manifest: PreparedArtifactManifest) -> bool:
        return (
            manifest.build_ready
            and manifest.config_path.is_file()
            and manifest.bundle_path.is_file()
            and (manifest.workspace_root / "package.json").is_file()
            and (manifest.workspace_root / "index.ts").is_file()
        )

    @staticmethod
    def _load_manifest(path: Path) -> PreparedArtifactManifest | None:
        if not path.is_file():
            return None
        try:
            return PreparedArtifactManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _write_manifest(path: Path, manifest: PreparedArtifactManifest) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def _render_index_source(
    *,
    template: QuickTemplate,
    capabilities: tuple[QuickCapability, ...],
    bootstrap_import: str | None,
) -> str:
    lines = [f'import "{_CAPABILITY_IMPORTS["rpc"]}"']
    for capability in capabilities:
        if capability == "rpc":
            continue
        lines.append(f'import "{_CAPABILITY_IMPORTS[capability]}"')
    if bootstrap_import is not None:
        lines.append(f'import "{bootstrap_import}"')
    lines.extend(
        [
            "",
            "// Prepared by frida-analykit MCP quick session.",
            f"// Template: {template}",
            f"// Imported capabilities: {', '.join(capabilities)}",
            f"// {_TEMPLATE_HINTS[template]}",
            "// Keep target-specific hooks and probes in MCP eval_js/install_snippet calls.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _resolve_capabilities(
    template: QuickTemplate,
    requested: list[QuickCapability],
) -> tuple[QuickCapability, ...]:
    ordered: list[QuickCapability] = []
    for capability in ("rpc", *_TEMPLATE_CAPABILITIES[template], *requested):
        if capability not in ordered:
            ordered.append(capability)
    return tuple(ordered)

def _signature_for_request(
    *,
    app: str,
    capabilities: tuple[QuickCapability, ...],
    template: QuickTemplate,
    bootstrap_kind: BootstrapKind,
    bootstrap_path: str | None,
    bootstrap_hash: str | None,
    bootstrap_source: str | None,
    host: str,
    device: str | None,
    path: str,
    datadir: str,
    stdout: str,
    stderr: str,
    dextools_output_dir: str,
    elftools_output_dir: str,
    ssl_log_secret: str,
    agent_package_spec: str,
) -> str:
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "app": app,
        "capabilities": list(capabilities),
        "template": template,
        "bootstrap_kind": bootstrap_kind,
        "bootstrap_path": bootstrap_path,
        "bootstrap_hash": bootstrap_hash,
        "bootstrap_source": bootstrap_source,
        "host": host,
        "device": device,
        "path": path,
        "datadir": datadir,
        "stdout": stdout,
        "stderr": stderr,
        "dextools_output_dir": dextools_output_dir,
        "elftools_output_dir": elftools_output_dir,
        "ssl_log_secret": ssl_log_secret,
        "agent_package_spec": agent_package_spec,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_config_from_app_config(config: AppConfig) -> PreparedArtifactConfig:
    return PreparedArtifactConfig(
        app=config.app or "",
        host=config.server.host,
        device=config.server.device,
        path=config.server.path,
        jsfile=str(config.jsfile.name),
        datadir=config.agent.datadir,
        stdout=config.agent.stdout,
        stderr=config.agent.stderr,
        dextools_output_dir=config.script.dextools.output_dir,
        elftools_output_dir=config.script.elftools.output_dir,
        ssl_log_secret=config.script.nettools.ssl_log_secret,
    )


def _optional_string(value: str | Path | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _default_prepared_cache_root() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return (base / "frida-analykit" / "mcp-prepared").expanduser().resolve()


def _resolve_bootstrap(request: PreparedSessionOpenRequest) -> _PreparedBootstrap:
    if request.bootstrap_source is not None:
        source = request.bootstrap_source.rstrip() + "\n"
        return _PreparedBootstrap(
            kind="source",
            source_text=source,
            workspace_filename=_BOOTSTRAP_INLINE_FILENAME,
            signature_hash=_hash_text(source),
        )
    if request.bootstrap_path is None:
        return _PreparedBootstrap(kind="none")

    source_path = Path(request.bootstrap_path).expanduser().resolve()
    if not source_path.is_file():
        raise PreparedWorkspaceError(f"bootstrap file does not exist: `{source_path}`")
    if source_path.suffix.lower() not in {".ts", ".js"}:
        raise PreparedWorkspaceError("bootstrap_path must point to a .ts or .js file")
    source_text = source_path.read_text(encoding="utf-8")
    workspace_filename = f"{_BOOTSTRAP_FILE_STEM}{source_path.suffix.lower()}"
    return _PreparedBootstrap(
        kind="path",
        source_text=source_text,
        original_path=source_path,
        workspace_filename=workspace_filename,
        signature_path=str(source_path),
        signature_hash=_hash_text(source_text),
    )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
