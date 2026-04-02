from __future__ import annotations

import tomllib
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
    source_path: Path | None = Field(default=None, exclude=True, repr=False)

    @classmethod
    def from_toml(cls, filepath: str | Path) -> "MCPStartupConfig":
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
        return config.resolve_paths(path.parent, source_path=path)

    def resolve_paths(
        self,
        base_dir: Path,
        *,
        source_path: Path | None = None,
    ) -> "MCPStartupConfig":
        def resolve(value: Path | None) -> Path | None:
            if value is None:
                return None
            expanded = Path(value).expanduser()
            if expanded.is_absolute():
                return expanded
            return (base_dir / expanded).resolve()

        return self.model_copy(
            update={
                "mcp": self.mcp.model_copy(
                    update={
                        "prepared_cache_root": resolve(self.mcp.prepared_cache_root),
                    }
                ),
                "agent": self.agent.model_copy(
                    update={
                        "datadir": resolve(self.agent.datadir),
                        "stdout": resolve(self.agent.stdout),
                        "stderr": resolve(self.agent.stderr),
                    }
                ),
                "script": self.script.model_copy(
                    update={
                        "dextools": self.script.dextools.model_copy(
                            update={"output_dir": resolve(self.script.dextools.output_dir)}
                        ),
                        "elftools": self.script.elftools.model_copy(
                            update={"output_dir": resolve(self.script.elftools.output_dir)}
                        ),
                        "nettools": self.script.nettools.model_copy(
                            update={"ssl_log_secret": resolve(self.script.nettools.ssl_log_secret)}
                        ),
                    }
                ),
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

    def to_summary(
        self,
        *,
        prepared_cache_root: Path,
        idle_timeout_seconds: int,
    ) -> ServiceConfigSummary:
        workspace = self.workspace_write_kwargs()
        return ServiceConfigSummary(
            config_path=self.source_path,
            idle_timeout_seconds=idle_timeout_seconds,
            prepared_cache_root=prepared_cache_root,
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
        )


def load_mcp_startup_config(filepath: str | Path | None) -> MCPStartupConfig:
    if filepath is None:
        return MCPStartupConfig()
    return MCPStartupConfig.from_toml(filepath)
