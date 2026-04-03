from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from ..workspace import (
    DEFAULT_WORKSPACE_DATADIR,
    DEFAULT_WORKSPACE_DEXTOOLS_OUTPUT_DIR,
    DEFAULT_WORKSPACE_ELFTOOLS_OUTPUT_DIR,
    DEFAULT_WORKSPACE_SSL_LOG_SECRET,
    DEFAULT_WORKSPACE_STDOUT,
)
from .models import (
    QuickPathReadinessSummary,
    ServiceAgentConfigSummary,
    ServiceConfigSummary,
    ServiceScriptConfigSummary,
    ServiceServerConfigSummary,
)


class MCPStartupConfigError(RuntimeError):
    pass


class MCPConfigSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idle_timeout_seconds: int = 1200
    prepared_cache_root: Path | None = None
    session_root: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("session_root", "session_history_root"),
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_duplicate_session_root_keys(cls, data: object) -> object:
        if isinstance(data, dict) and "session_root" in data and "session_history_root" in data:
            raise ValueError("mcp config cannot specify both `session_root` and legacy `session_history_root`; use `session_root`")
        return data


class MCPServerSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1:27042"
    device: str | None = None
    path: str = Field(default="frida-server", validation_alias=AliasChoices("path", "servername"))

    @model_validator(mode="before")
    @classmethod
    def _reject_duplicate_path_keys(cls, data: object) -> object:
        if isinstance(data, dict) and "path" in data and "servername" in data:
            raise ValueError("server config cannot specify both `path` and legacy `servername`; use `path`")
        return data

    @property
    def servername(self) -> str:
        return self.path


class MCPAgentSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datadir: Path | None = None
    stdout: Path | None = None
    stderr: Path | None = None


class MCPScriptDexToolsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: Path | None = None


class MCPScriptElfToolsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: Path | None = None


class MCPScriptNetToolsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ssl_log_secret: Path | None = None


class MCPScriptSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dextools: MCPScriptDexToolsSection = Field(default_factory=MCPScriptDexToolsSection)
    elftools: MCPScriptElfToolsSection = Field(default_factory=MCPScriptElfToolsSection)
    nettools: MCPScriptNetToolsSection = Field(default_factory=MCPScriptNetToolsSection)


class MCPStartupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mcp: MCPConfigSection = Field(default_factory=MCPConfigSection)
    server: MCPServerSection = Field(default_factory=MCPServerSection)
    agent: MCPAgentSection = Field(default_factory=MCPAgentSection)
    script: MCPScriptSection = Field(default_factory=MCPScriptSection)
    source_path_raw: str | None = Field(default=None, exclude=True, repr=False)
    source_path: Path | None = Field(default=None, exclude=True, repr=False)

    @classmethod
    def from_toml(cls, filepath: str | Path) -> "MCPStartupConfig":
        raw_path = str(filepath)
        path = Path(filepath).expanduser().resolve()
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise MCPStartupConfigError(f"MCP startup config does not exist: `{path}`") from exc
        except tomllib.TOMLDecodeError as exc:
            raise MCPStartupConfigError(f"MCP startup config is not valid TOML: {exc}") from exc
        except OSError as exc:
            raise MCPStartupConfigError(f"failed to read MCP startup config `{path}`: {exc}") from exc

        try:
            config = cls.model_validate(payload)
        except Exception as exc:
            raise MCPStartupConfigError(f"invalid MCP startup config `{path}`: {exc}") from exc
        return config.resolve_paths(path.parent, source_path=path, source_path_raw=raw_path)

    def resolve_paths(
        self,
        base_dir: Path,
        *,
        source_path: Path | None = None,
        source_path_raw: str | None = None,
    ) -> "MCPStartupConfig":
        def resolve_service_path(value: Path | None) -> Path | None:
            if value is None:
                return None
            expanded = Path(value).expanduser()
            if expanded.is_absolute():
                return expanded
            return (base_dir / expanded).resolve()

        def preserve_workspace_relative_path(value: Path | None) -> Path | None:
            if value is None:
                return None
            expanded = Path(value).expanduser()
            if expanded.is_absolute():
                return expanded
            return expanded

        return self.model_copy(
            update={
                "mcp": self.mcp.model_copy(
                    update={
                        "prepared_cache_root": resolve_service_path(self.mcp.prepared_cache_root),
                        "session_root": resolve_service_path(self.mcp.session_root),
                    }
                ),
                "agent": self.agent.model_copy(
                    update={
                        "datadir": preserve_workspace_relative_path(self.agent.datadir),
                        "stdout": preserve_workspace_relative_path(self.agent.stdout),
                        "stderr": preserve_workspace_relative_path(self.agent.stderr),
                    }
                ),
                "script": self.script.model_copy(
                    update={
                        "dextools": self.script.dextools.model_copy(
                            update={"output_dir": preserve_workspace_relative_path(self.script.dextools.output_dir)}
                        ),
                        "elftools": self.script.elftools.model_copy(
                            update={"output_dir": preserve_workspace_relative_path(self.script.elftools.output_dir)}
                        ),
                        "nettools": self.script.nettools.model_copy(
                            update={"ssl_log_secret": preserve_workspace_relative_path(self.script.nettools.ssl_log_secret)}
                        ),
                    }
                ),
                "source_path_raw": source_path_raw,
                "source_path": source_path,
            }
        )

    def workspace_write_kwargs(self) -> dict[str, str | Path | None]:
        stdout = self.agent.stdout or DEFAULT_WORKSPACE_STDOUT
        return {
            "host": self.server.host,
            "device": self.server.device,
            "path": self.server.path,
            "datadir": self.agent.datadir or DEFAULT_WORKSPACE_DATADIR,
            "stdout": stdout,
            "stderr": self.agent.stderr or stdout,
            "dextools_output_dir": self.script.dextools.output_dir or DEFAULT_WORKSPACE_DEXTOOLS_OUTPUT_DIR,
            "elftools_output_dir": self.script.elftools.output_dir or DEFAULT_WORKSPACE_ELFTOOLS_OUTPUT_DIR,
            "ssl_log_secret": self.script.nettools.ssl_log_secret or DEFAULT_WORKSPACE_SSL_LOG_SECRET,
        }

    def session_root(self, *, prepared_cache_root: Path) -> Path:
        configured = self.mcp.session_root
        if configured is not None:
            return configured
        return (prepared_cache_root / "sessions").resolve()

    def session_history_root(self, *, prepared_cache_root: Path) -> Path:
        return self.session_root(prepared_cache_root=prepared_cache_root)

    def to_summary(
        self,
        *,
        service_instance_id: str,
        service_started_at: datetime,
        prepared_cache_root: Path,
        session_root: Path,
        idle_timeout_seconds: int,
        quick_path: QuickPathReadinessSummary,
    ) -> ServiceConfigSummary:
        workspace = self.workspace_write_kwargs()
        return ServiceConfigSummary(
            service_instance_id=service_instance_id,
            service_started_at=service_started_at,
            config_path_raw=self.source_path_raw,
            config_path=self.source_path,
            idle_timeout_seconds=idle_timeout_seconds,
            prepared_cache_root=prepared_cache_root,
            session_root=session_root,
            server=ServiceServerConfigSummary(
                host=self.server.host,
                device=self.server.device,
                path=self.server.path,
            ),
            agent=ServiceAgentConfigSummary(
                datadir=workspace["datadir"],
                stdout=workspace["stdout"],
                stderr=workspace["stderr"],
            ),
            script=ServiceScriptConfigSummary(
                dextools_output_dir=workspace["dextools_output_dir"],
                elftools_output_dir=workspace["elftools_output_dir"],
                ssl_log_secret=workspace["ssl_log_secret"],
            ),
            quick_path=quick_path,
        )


def load_mcp_startup_config(filepath: str | Path | None) -> MCPStartupConfig:
    if filepath is None:
        return MCPStartupConfig()
    return MCPStartupConfig.from_toml(filepath)
