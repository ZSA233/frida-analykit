from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML

DEFAULT_SCRIPT_REPL_GLOBALS: tuple[str, ...] = (
    "Process",
    "Module",
    "Memory",
    "Java",
    "ObjC",
    "Swift",
)


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str | None = None
    servername: str = "frida-server"
    host: str = "127.0.0.1:27042"
    version: str | None = None

    @property
    def is_remote(self) -> bool:
        return self.host not in {"local", "local://", "usb", "usb://"}


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datadir: Path | None = None
    stdout: Path | None = None
    stderr: Path | None = None


class ScriptNetToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ssl_log_secret: Path | None = None


class ScriptDexToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dex_dir: Path | None = None


class ScriptRpcConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_max_bytes: int = 8 * 1024 * 1024


class ScriptReplConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    globals: list[str] = Field(default_factory=lambda: list(DEFAULT_SCRIPT_REPL_GLOBALS))


class ScriptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nettools: ScriptNetToolsConfig = Field(default_factory=ScriptNetToolsConfig)
    dextools: ScriptDexToolsConfig = Field(default_factory=ScriptDexToolsConfig)
    rpc: ScriptRpcConfig = Field(default_factory=ScriptRpcConfig)
    repl: ScriptReplConfig = Field(default_factory=ScriptReplConfig)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: str | None = None
    jsfile: Path
    server: ServerConfig
    agent: AgentConfig = Field(default_factory=AgentConfig)
    script: ScriptConfig = Field(default_factory=ScriptConfig)
    source_path: Path | None = Field(default=None, exclude=True, repr=False)

    @classmethod
    def from_yaml(cls, filepath: str | Path) -> "AppConfig":
        path = Path(filepath).expanduser().resolve()
        yaml = YAML(typ="safe")
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle) or {}
        config = cls.model_validate(data)
        return config.resolve_paths(path.parent, source_path=path)

    def resolve_paths(
        self,
        base_dir: Path,
        *,
        source_path: Path | None = None,
    ) -> "AppConfig":
        def resolve(value: Path | None) -> Path | None:
            if value is None:
                return None
            expanded = Path(value).expanduser()
            if expanded.is_absolute():
                return expanded
            return (base_dir / expanded).resolve()

        return self.model_copy(
            update={
                "jsfile": resolve(self.jsfile),
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
                            update={
                                "dex_dir": resolve(self.script.dextools.dex_dir),
                            }
                        ),
                        "nettools": self.script.nettools.model_copy(
                            update={
                                "ssl_log_secret": resolve(self.script.nettools.ssl_log_secret),
                            }
                        )
                    }
                ),
                "source_path": source_path,
            }
        )

    def to_yaml_data(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"source_path"})
        return data
