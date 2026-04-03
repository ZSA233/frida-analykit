from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuickCapability = Literal[
    "rpc",
    "config",
    "bridges",
    "helper",
    "process",
    "jni",
    "ssl",
    "elf",
    "dex",
    "native_libssl",
    "native_libart",
    "native_libc",
]
QuickTemplate = Literal[
    "minimal",
    "process_probe",
    "java_bridge",
    "dex_probe",
    "ssl_probe",
    "elf_probe",
]
PreparedOutcome = Literal["cache_hit", "rebuilt", "failed"]
BootstrapKind = Literal["none", "source", "path"]
_UNSUPPORTED_QUICK_CAPABILITY = "elf_enhanced"
_UNSUPPORTED_QUICK_CAPABILITY_MESSAGE = (
    "`elf_enhanced` is not supported as a quick-session preload capability; "
    "import `@zsa233/frida-analykit-agent/elf/enhanced` from `bootstrap_path`, "
    "`bootstrap_source`, or a custom workspace instead"
)


class PreparedSessionOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: str
    mode: Literal["attach", "spawn"]
    capabilities: list[QuickCapability] = Field(default_factory=list)
    template: QuickTemplate = "minimal"
    pid: int | None = None
    bootstrap_path: str | None = None
    bootstrap_source: str | None = None
    force_replace: bool = False

    @model_validator(mode="before")
    @classmethod
    def _reject_unsupported_capabilities(cls, data: object) -> object:
        if isinstance(data, Mapping):
            raw_capabilities = data.get("capabilities")
            if isinstance(raw_capabilities, list) and _UNSUPPORTED_QUICK_CAPABILITY in raw_capabilities:
                raise ValueError(_UNSUPPORTED_QUICK_CAPABILITY_MESSAGE)
        return data

    @model_validator(mode="after")
    def _validate_bootstrap_inputs(self) -> "PreparedSessionOpenRequest":
        if self.bootstrap_path is not None and self.bootstrap_source is not None:
            raise ValueError("`bootstrap_path` and `bootstrap_source` are mutually exclusive")
        return self


class PreparedArtifactConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: str
    host: str
    device: str | None = None
    path: str
    jsfile: str
    datadir: Path | None = None
    stdout: Path | None = None
    stderr: Path | None = None
    dextools_output_dir: Path | None = None
    elftools_output_dir: Path | None = None
    ssl_log_secret: Path | None = None


class PreparedArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature: str
    template: QuickTemplate
    capabilities: list[QuickCapability] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    agent_package_spec: str
    bootstrap_kind: BootstrapKind = "none"
    bootstrap_path: Path | None = None
    bootstrap_source: str | None = None
    workspace_root: Path
    config_path: Path
    bundle_path: Path
    config: PreparedArtifactConfig
    build_ready: bool = False
    last_prepare_outcome: PreparedOutcome | None = None
    last_build_error: str | None = None
    last_prepared_at: datetime | None = None
    last_used_at: datetime | None = None


class PreparedWorkspaceBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: PreparedArtifactManifest
    cache_hit: bool
    build_performed: bool
