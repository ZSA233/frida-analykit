from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from ...config import AppConfig, DEFAULT_CONFIG_FILENAME
from ...scaffold import AGENT_PACKAGE_NAME, default_agent_package_spec
from ...workspace import (
    acquire_workspace_build_lock,
    prepare_workspace_npm_env,
    workspace_build_resources,
    write_workspace_config,
)
from ..models import (
    QuickPathCheckSummary,
    QuickPathCompileProbeSummary,
    QuickPathReadinessSummary,
    QuickPathToolchainSummary,
)
from .models import (
    PreparedArtifactConfig,
    PreparedArtifactManifest,
    PreparedSessionOpenRequest,
    PreparedWorkspaceBuildResult,
)
from ..config import MCPStartupConfig
from .constants import (
    BOOTSTRAP_FILE_STEM as _BOOTSTRAP_FILE_STEM,
    BOOTSTRAP_RELATIVE_IMPORT_PATTERNS as _BOOTSTRAP_RELATIVE_IMPORT_PATTERNS,
    CAPABILITY_IMPORTS as _CAPABILITY_IMPORTS,
    CAPABILITY_RETAIN_EXPORTS as _CAPABILITY_RETAIN_EXPORTS,
    ENV_TYPES_FILENAME as _ENV_TYPES_FILENAME,
    MANIFEST_FILENAME as _MANIFEST_FILENAME,
    MISSING_FRIDA_COMPILE_MESSAGE as _MISSING_FRIDA_COMPILE_MESSAGE,
    MISSING_NPM_MESSAGE as _MISSING_NPM_MESSAGE,
    QUICK_FRIDA_GUM_TYPES_VERSION as _QUICK_FRIDA_GUM_TYPES_VERSION,
    QUICK_TYPESCRIPT_VERSION as _QUICK_TYPESCRIPT_VERSION,
    SCHEMA_VERSION as _SCHEMA_VERSION,
    STARTUP_PROBE_DIRNAME as _STARTUP_PROBE_DIRNAME,
    TOOLCHAIN_DIRNAME as _TOOLCHAIN_DIRNAME,
)
from .paths import (
    default_prepared_cache_root as _default_prepared_cache_root,
    package_install_path as _package_install_path,
    remove_path as _remove_path,
    tail_text as _tail_text,
    write_json as _write_json,
)
from .rendering import (
    PreparedBootstrap as _PreparedBootstrap,
    render_index_source as _render_index_source,
    resolve_capabilities as _resolve_capabilities,
)
from .signature import hash_text as _hash_text
from .signature import signature_for_request as _signature_for_request


class PreparedWorkspaceError(RuntimeError):
    pass


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

    def _toolchain_signature_payload(self, agent_package_spec: str) -> dict[str, str | int]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "agent_package_spec": agent_package_spec,
            "typescript": _QUICK_TYPESCRIPT_VERSION,
            "frida_gum_types": _QUICK_FRIDA_GUM_TYPES_VERSION,
        }

    def _toolchain_digest_for_spec(self, agent_package_spec: str) -> str:
        payload = json.dumps(self._toolchain_signature_payload(agent_package_spec), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _toolchain_root_for_spec(self, agent_package_spec: str) -> Path:
        digest = self._toolchain_digest_for_spec(agent_package_spec)
        return self._cache_root / _TOOLCHAIN_DIRNAME / digest

    def _startup_probe_root_for_spec(self, agent_package_spec: str) -> Path:
        digest = self._toolchain_digest_for_spec(agent_package_spec)
        return self._cache_root / _STARTUP_PROBE_DIRNAME / digest

    def _toolchain_package_manifest(self, agent_package_spec: str) -> dict[str, object]:
        return {
            "name": "frida-analykit-mcp-runtime-toolchain",
            "private": True,
            "type": "module",
            "dependencies": {
                AGENT_PACKAGE_NAME: agent_package_spec,
            },
            "devDependencies": {
                "@types/frida-gum": _QUICK_FRIDA_GUM_TYPES_VERSION,
                "typescript": _QUICK_TYPESCRIPT_VERSION,
            },
        }

    def _write_workspace_package_json(self, workspace_root: Path, *, agent_package_spec: str) -> None:
        _write_json(
            workspace_root / "package.json",
            {
                "name": "frida-analykit-mcp-prepared-session",
                "private": True,
                "type": "module",
                "dependencies": {
                    AGENT_PACKAGE_NAME: agent_package_spec,
                },
            },
        )

    def _write_workspace_tsconfig(self, workspace_root: Path) -> None:
        _write_json(
            workspace_root / "tsconfig.json",
            {
                "compilerOptions": {
                    "module": "es2022",
                    "moduleResolution": "bundler",
                    "target": "es2021",
                    "lib": ["es2021"],
                    "types": ["frida-gum"],
                    "allowJs": True,
                    "noEmit": True,
                    "strict": True,
                    "esModuleInterop": True,
                    "allowSyntheticDefaultImports": True,
                    "skipLibCheck": True,
                }
            },
        )

    def _write_workspace_env_types(self, workspace_root: Path) -> None:
        (workspace_root / _ENV_TYPES_FILENAME).write_text(
            "\n".join(
                [
                    "declare const console: {",
                    "  log(...args: unknown[]): void",
                    "  warn(...args: unknown[]): void",
                    "  error(...args: unknown[]): void",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def _resolve_frida_compile(self) -> str:
        executable = shutil.which("frida-compile")
        if executable is None:
            raise PreparedWorkspaceError(_MISSING_FRIDA_COMPILE_MESSAGE)
        return executable

    def _resolve_npm(self) -> str:
        executable = shutil.which("npm")
        if executable is None:
            raise PreparedWorkspaceError(_MISSING_NPM_MESSAGE)
        return executable

    def _ensure_cache_root_writable(self) -> None:
        probe_path = self._cache_root / ".warmup-write-probe"
        try:
            self._cache_root.mkdir(parents=True, exist_ok=True)
            probe_path.write_text("ok\n", encoding="utf-8")
        except OSError as exc:
            raise PreparedWorkspaceError(
                f"quick path requires a writable prepared cache root at `{self._cache_root}`: {exc}"
            ) from exc
        finally:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _prepare_npm_env(self, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
        try:
            return prepare_workspace_npm_env(base_env or os.environ, self._build_resources)
        except OSError as exc:
            raise PreparedWorkspaceError(
                f"quick path requires a writable npm cache under `{self._build_resources.npm_cache_dir}`: {exc}"
            ) from exc

    def _acquire_build_lock(self):
        try:
            return acquire_workspace_build_lock(self._build_resources)
        except OSError as exc:
            raise PreparedWorkspaceError(
                f"quick path requires a writable build lock at `{self._build_resources.lock_path}`: {exc}"
            ) from exc

    @staticmethod
    def _ensure_managed_directory(path: Path, *, label: str) -> None:
        try:
            if path.exists() and not path.is_dir():
                _remove_path(path)
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PreparedWorkspaceError(f"failed to prepare {label} at `{path}`: {exc}") from exc

    def _toolchain_ready(self, toolchain_root: Path, *, agent_package_spec: str) -> bool:
        package_json = toolchain_root / "package.json"
        if not package_json.is_file():
            return False
        try:
            package_payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if package_payload != self._toolchain_package_manifest(agent_package_spec):
            return False
        node_modules = toolchain_root / "node_modules"
        return (
            _package_install_path(node_modules, AGENT_PACKAGE_NAME).is_dir()
            and _package_install_path(node_modules, "@types/frida-gum").is_dir()
            and _package_install_path(node_modules, "typescript").is_dir()
        )

    def _ensure_shared_toolchain_with_state(
        self,
        *,
        agent_package_spec: str,
        env: Mapping[str, str],
    ) -> tuple[Path, Literal["cache_hit", "installed"]]:
        toolchain_root = self._toolchain_root_for_spec(agent_package_spec)
        if self._toolchain_ready(toolchain_root, agent_package_spec=agent_package_spec):
            return toolchain_root, "cache_hit"

        npm = self._resolve_npm()
        try:
            self._ensure_managed_directory(toolchain_root, label="shared quick runtime toolchain directory")
            _write_json(toolchain_root / "package.json", self._toolchain_package_manifest(agent_package_spec))
            _remove_path(toolchain_root / "node_modules")
            _remove_path(toolchain_root / "package-lock.json")
            self._run_subprocess(
                [npm, "install", "--ignore-scripts"],
                cwd=toolchain_root,
                env=env,
                error_prefix="failed to install quick-session runtime dependencies",
            )
        except PreparedWorkspaceError:
            raise
        except OSError as exc:
            raise PreparedWorkspaceError(
                f"failed to prepare shared quick runtime toolchain at `{toolchain_root}`: {exc}"
            ) from exc
        if not self._toolchain_ready(toolchain_root, agent_package_spec=agent_package_spec):
            raise PreparedWorkspaceError(
                "quick-session runtime dependencies were installed, but the shared toolchain is still incomplete"
            )
        return toolchain_root, "installed"

    def _ensure_shared_toolchain(
        self,
        *,
        agent_package_spec: str,
        env: Mapping[str, str],
    ) -> Path:
        toolchain_root, _ = self._ensure_shared_toolchain_with_state(
            agent_package_spec=agent_package_spec,
            env=env,
        )
        return toolchain_root

    def _sync_workspace_node_modules(self, *, workspace_root: Path, toolchain_root: Path) -> None:
        node_modules = workspace_root / "node_modules"
        shared_node_modules = toolchain_root / "node_modules"
        if node_modules.is_symlink():
            try:
                if node_modules.resolve() == shared_node_modules.resolve():
                    return
            except OSError:
                pass
        if node_modules.exists() or node_modules.is_symlink():
            _remove_path(node_modules)
        try:
            # Quick workspaces only need a view over the shared runtime toolchain;
            # a directory symlink avoids reinstalling the same dependencies per signature.
            node_modules.symlink_to(shared_node_modules, target_is_directory=True)
        except OSError:
            shutil.copytree(shared_node_modules, node_modules, dirs_exist_ok=True)

    def _build_quick_bundle(
        self,
        *,
        workspace_root: Path,
        bundle_path: Path,
        frida_compile: str,
        toolchain_root: Path,
        env: Mapping[str, str],
    ) -> None:
        build_env = dict(env)
        node_modules = str(toolchain_root / "node_modules")
        existing_node_path = build_env.get("NODE_PATH")
        build_env["NODE_PATH"] = (
            node_modules if not existing_node_path else os.pathsep.join([node_modules, existing_node_path])
        )
        _remove_path(bundle_path)
        self._run_subprocess(
            [frida_compile, "index.ts", "-o", bundle_path.name, "-c"],
            cwd=workspace_root,
            env=build_env,
            error_prefix="`frida-compile` failed for the prepared quick session",
        )
        if not bundle_path.is_file():
            raise PreparedWorkspaceError(
                f"`frida-compile` completed but `{bundle_path.name}` was not created in `{workspace_root}`"
            )

    def _run_compile_probe(
        self,
        *,
        agent_package_spec: str,
        frida_compile: str,
        toolchain_root: Path,
        env: Mapping[str, str],
    ) -> QuickPathCompileProbeSummary:
        probe_root = self._startup_probe_root_for_spec(agent_package_spec)
        bundle_path = probe_root / "_agent.js"
        try:
            self._ensure_managed_directory(probe_root, label="startup compile probe workspace")
            self._write_workspace_package_json(probe_root, agent_package_spec=agent_package_spec)
            self._write_workspace_tsconfig(probe_root)
            self._write_workspace_env_types(probe_root)
            (probe_root / "index.ts").write_text(
                _render_index_source(
                    template="minimal",
                    capabilities=("rpc",),
                    bootstrap=_PreparedBootstrap(kind="none"),
                ),
                encoding="utf-8",
            )
            self._sync_workspace_node_modules(workspace_root=probe_root, toolchain_root=toolchain_root)
            self._build_quick_bundle(
                workspace_root=probe_root,
                bundle_path=bundle_path,
                frida_compile=frida_compile,
                toolchain_root=toolchain_root,
                env=env,
            )
        except PreparedWorkspaceError:
            raise
        except OSError as exc:
            raise PreparedWorkspaceError(
                f"failed to prepare startup compile probe workspace at `{probe_root}`: {exc}"
            ) from exc
        return QuickPathCompileProbeSummary(
            state="compiled",
            workspace_root=probe_root,
            bundle_path=bundle_path,
            detail="compile sanity probe succeeded",
            last_error=None,
        )

    @staticmethod
    def _run_subprocess(
        command: list[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None,
        error_prefix: str,
    ) -> None:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=dict(env) if env is not None else None,
                # Quick warmup/build subprocesses run inside the MCP server process.
                # Keep them off fd 0 so `frida-compile`/`npm` cannot interfere with stdio MCP traffic.
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise PreparedWorkspaceError(f"{error_prefix}: {exc}") from exc
        if result.returncode == 0:
            return
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
        detail = f"\n\nLast output:\n{_tail_text(output)}" if output else ""
        raise PreparedWorkspaceError(
            f"{error_prefix} in `{cwd}` with exit code {result.returncode}.{detail}"
        )

    def startup_warmup(self) -> QuickPathReadinessSummary:
        checked_at = self._now_fn()
        agent_package_spec = default_agent_package_spec()
        toolchain_root = self._toolchain_root_for_spec(agent_package_spec)
        probe_root = self._startup_probe_root_for_spec(agent_package_spec)
        summary_message: str | None = None
        cache_root = QuickPathCheckSummary(state="skipped", path=self._cache_root, detail=None)
        npm = QuickPathCheckSummary(state="skipped", path=None, detail="startup preflight did not run")
        frida_compile = QuickPathCheckSummary(state="skipped", path=None, detail="startup preflight did not run")
        shared_toolchain = QuickPathToolchainSummary(
            state="skipped",
            root=toolchain_root,
            agent_package_spec=agent_package_spec,
            detail="startup warmup did not run",
        )
        compile_probe = QuickPathCompileProbeSummary(
            state="skipped",
            workspace_root=probe_root,
            bundle_path=probe_root / "_agent.js",
            detail="startup warmup did not run",
            last_error=None,
        )

        try:
            self._ensure_cache_root_writable()
            cache_root = QuickPathCheckSummary(
                state="ready",
                path=self._cache_root,
                detail="prepared cache root is writable",
            )
        except PreparedWorkspaceError as exc:
            summary_message = str(exc)
            cache_root = QuickPathCheckSummary(
                state="failed",
                path=self._cache_root,
                detail=str(exc),
            )

        frida_compile_path: str | None = None
        try:
            frida_compile_path = self._resolve_frida_compile()
            frida_compile = QuickPathCheckSummary(
                state="ready",
                path=Path(frida_compile_path),
                detail="found in MCP PATH",
            )
        except PreparedWorkspaceError as exc:
            summary_message = summary_message or str(exc)
            frida_compile = QuickPathCheckSummary(
                state="failed",
                path=None,
                detail=str(exc),
            )

        if summary_message is not None or frida_compile_path is None:
            return QuickPathReadinessSummary(
                state="failed",
                checked_at=checked_at,
                message=summary_message,
                cache_root=cache_root,
                npm=npm,
                frida_compile=frida_compile,
                shared_toolchain=shared_toolchain,
                compile_probe=compile_probe,
            )

        toolchain_cache_hit = self._toolchain_ready(toolchain_root, agent_package_spec=agent_package_spec)

        env = dict(os.environ)
        if toolchain_cache_hit:
            npm_path = shutil.which("npm")
            if npm_path is not None:
                npm = QuickPathCheckSummary(
                    state="ready",
                    path=Path(npm_path),
                    detail="found in MCP PATH",
                )
            else:
                npm = QuickPathCheckSummary(
                    state="skipped",
                    path=None,
                    detail="shared quick runtime toolchain cache hit did not require npm",
                )
        else:
            try:
                npm_path = self._resolve_npm()
                npm = QuickPathCheckSummary(
                    state="ready",
                    path=Path(npm_path),
                    detail="found in MCP PATH",
                )
                env = self._prepare_npm_env(os.environ)
            except PreparedWorkspaceError as exc:
                message = str(exc)
                return QuickPathReadinessSummary(
                    state="failed",
                    checked_at=checked_at,
                    message=message,
                    cache_root=cache_root,
                    npm=npm.model_copy(update={"state": "failed", "detail": message}),
                    frida_compile=frida_compile,
                    shared_toolchain=shared_toolchain.model_copy(update={"detail": "shared toolchain warmup was not attempted"}),
                    compile_probe=compile_probe.model_copy(update={"detail": "compile probe was not attempted"}),
                )

        try:
            lock = self._acquire_build_lock()
        except PreparedWorkspaceError as exc:
            message = str(exc)
            return QuickPathReadinessSummary(
                state="failed",
                checked_at=checked_at,
                message=message,
                cache_root=cache_root,
                npm=npm,
                frida_compile=frida_compile,
                shared_toolchain=shared_toolchain.model_copy(update={"detail": "shared toolchain warmup was not attempted"}),
                compile_probe=compile_probe.model_copy(update={"detail": "compile probe was not attempted"}),
            )
        try:
            try:
                toolchain_root, toolchain_state = self._ensure_shared_toolchain_with_state(
                    agent_package_spec=agent_package_spec,
                    env=env,
                )
                shared_toolchain = QuickPathToolchainSummary(
                    state=toolchain_state,
                    root=toolchain_root,
                    agent_package_spec=agent_package_spec,
                    detail=(
                        "reused shared quick runtime toolchain"
                        if toolchain_state == "cache_hit"
                        else "installed shared quick runtime toolchain"
                    ),
                )
            except PreparedWorkspaceError as exc:
                summary_message = str(exc)
                shared_toolchain = QuickPathToolchainSummary(
                    state="failed",
                    root=toolchain_root,
                    agent_package_spec=agent_package_spec,
                    detail=str(exc),
                )
                return QuickPathReadinessSummary(
                    state="failed",
                    checked_at=checked_at,
                    message=summary_message,
                    cache_root=cache_root,
                    npm=npm,
                    frida_compile=frida_compile,
                    shared_toolchain=shared_toolchain,
                    compile_probe=compile_probe.model_copy(update={"detail": "compile probe was not attempted"}),
                )

            try:
                compile_probe = self._run_compile_probe(
                    agent_package_spec=agent_package_spec,
                    frida_compile=frida_compile_path,
                    toolchain_root=toolchain_root,
                    env=env,
                )
            except PreparedWorkspaceError as exc:
                summary_message = str(exc)
                compile_probe = QuickPathCompileProbeSummary(
                    state="failed",
                    workspace_root=probe_root,
                    bundle_path=probe_root / "_agent.js",
                    detail="compile sanity probe failed",
                    last_error=str(exc),
                )
                return QuickPathReadinessSummary(
                    state="failed",
                    checked_at=checked_at,
                    message=summary_message,
                    cache_root=cache_root,
                    npm=npm,
                    frida_compile=frida_compile,
                    shared_toolchain=shared_toolchain,
                    compile_probe=compile_probe,
                )
        finally:
            lock.release()

        return QuickPathReadinessSummary(
            state="ready",
            checked_at=checked_at,
            message="quick path toolchain is ready",
            cache_root=cache_root,
            npm=npm,
            frida_compile=frida_compile,
            shared_toolchain=shared_toolchain,
            compile_probe=compile_probe,
        )

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
            nettools_output_dir=str(workspace_defaults["nettools_output_dir"]),
            agent_package_spec=package_spec,
        )
        workspace_root = self._cache_root / signature
        manifest_path = workspace_root / _MANIFEST_FILENAME
        imports = [_CAPABILITY_IMPORTS[capability] for capability in capabilities]
        now = self._now_fn()

        try:
            self._ensure_managed_directory(workspace_root, label="prepared quick-session workspace")
            self._write_workspace_package_json(workspace_root, agent_package_spec=package_spec)
            self._write_workspace_tsconfig(workspace_root)
            self._write_workspace_env_types(workspace_root)
            _remove_path(workspace_root / "bootstrap.inline.ts")
            _remove_path(workspace_root / f"{_BOOTSTRAP_FILE_STEM}.ts")
            _remove_path(workspace_root / f"{_BOOTSTRAP_FILE_STEM}.js")
            if bootstrap.source_text is not None and bootstrap.workspace_filename is not None:
                (workspace_root / bootstrap.workspace_filename).write_text(bootstrap.source_text, encoding="utf-8")
            (workspace_root / "index.ts").write_text(
                _render_index_source(
                    template=validated.template,
                    capabilities=capabilities,
                    bootstrap=bootstrap,
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
                nettools_output_dir=workspace_defaults["nettools_output_dir"],
            )
        except PreparedWorkspaceError:
            raise
        except OSError as exc:
            raise PreparedWorkspaceError(
                f"failed to prepare quick-session workspace at `{workspace_root}`: {exc}"
            ) from exc
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
            self._write_manifest_checked(manifest_path, manifest, context="record prepared quick-session cache hit")
            return PreparedWorkspaceBuildResult(manifest=manifest, cache_hit=True, build_performed=False)

        build_performed = True
        lock = None
        try:
            env = self._prepare_npm_env(os.environ)
            lock = self._acquire_build_lock()
            frida_compile = self._resolve_frida_compile()
            toolchain_root = self._ensure_shared_toolchain(agent_package_spec=package_spec, env=env)
            self._sync_workspace_node_modules(workspace_root=workspace_root, toolchain_root=toolchain_root)
            self._build_quick_bundle(
                workspace_root=workspace_root,
                bundle_path=manifest.bundle_path,
                frida_compile=frida_compile,
                toolchain_root=toolchain_root,
                env=env,
            )
        except PreparedWorkspaceError as exc:
            manifest = manifest.model_copy(
                update={
                    "build_ready": False,
                    "last_prepare_outcome": "failed",
                    "last_build_error": str(exc),
                    "last_prepared_at": now,
                }
            )
            self._write_manifest_best_effort(manifest_path, manifest)
            raise
        except OSError as exc:
            normalized = PreparedWorkspaceError(
                f"failed to build prepared quick-session workspace at `{workspace_root}`: {exc}"
            )
            manifest = manifest.model_copy(
                update={
                    "build_ready": False,
                    "last_prepare_outcome": "failed",
                    "last_build_error": str(normalized),
                    "last_prepared_at": now,
                }
            )
            self._write_manifest_best_effort(manifest_path, manifest)
            raise normalized from exc
        finally:
            if lock is not None:
                lock.release()

        manifest = manifest.model_copy(
            update={
                "build_ready": True,
                "last_prepare_outcome": "rebuilt",
                "last_build_error": None,
                "last_prepared_at": now,
            }
        )
        self._write_manifest_checked(manifest_path, manifest, context="record prepared quick-session build result")
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

    @classmethod
    def _write_manifest_checked(
        cls,
        path: Path,
        manifest: PreparedArtifactManifest,
        *,
        context: str,
    ) -> None:
        try:
            cls._write_manifest(path, manifest)
        except OSError as exc:
            raise PreparedWorkspaceError(f"failed to {context} at `{path}`: {exc}") from exc

    @classmethod
    def _write_manifest_best_effort(cls, path: Path, manifest: PreparedArtifactManifest) -> None:
        try:
            cls._write_manifest(path, manifest)
        except OSError:
            pass


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
        nettools_output_dir=config.script.nettools.output_dir,
    )


def _optional_string(value: str | Path | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _resolve_bootstrap(request: PreparedSessionOpenRequest) -> _PreparedBootstrap:
    if request.bootstrap_source is not None:
        source = request.bootstrap_source.rstrip() + "\n"
        return _PreparedBootstrap(
            kind="source",
            source_text=source,
            signature_hash=_hash_text(source),
        )
    if request.bootstrap_path is None:
        return _PreparedBootstrap(kind="none")

    source_path = Path(request.bootstrap_path).expanduser().resolve()
    if not source_path.is_file():
        raise PreparedWorkspaceError(f"bootstrap file does not exist: `{source_path}`")
    if source_path.suffix.lower() not in {".ts", ".js"}:
        raise PreparedWorkspaceError("bootstrap_path must point to a .ts or .js file")
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PreparedWorkspaceError(f"failed to read bootstrap file `{source_path}`: {exc}") from exc
    relative_import = _find_relative_bootstrap_import(source_text)
    if relative_import is not None:
        raise PreparedWorkspaceError(
            "quick bootstrap_path must be a self-contained .ts/.js file; "
            f"found relative import `{relative_import}` in `{source_path}`. "
            "Quick path only copies that single file into the prepared workspace. "
            "Use `session_open(config_path, ...)` if you need sibling local imports or a full workspace dependency graph."
        )
    workspace_filename = f"{_BOOTSTRAP_FILE_STEM}{source_path.suffix.lower()}"
    return _PreparedBootstrap(
        kind="path",
        source_text=source_text,
        original_path=source_path,
        workspace_filename=workspace_filename,
        signature_path=str(source_path),
        signature_hash=_hash_text(source_text),
    )


def _find_relative_bootstrap_import(source_text: str) -> str | None:
    # Quick bootstrap_path copies exactly one file into the prepared workspace.
    # Reject obvious relative imports up front so the failure is explicit instead
    # of surfacing later as a confusing bundler/module-resolution error.
    for pattern in _BOOTSTRAP_RELATIVE_IMPORT_PATTERNS:
        match = pattern.search(source_text)
        if match is not None:
            return match.group("path")
    return None
