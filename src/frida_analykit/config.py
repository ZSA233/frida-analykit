from __future__ import annotations

import tomllib
from pathlib import Path, PurePath
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from ruamel.yaml import YAML

DEFAULT_CONFIG_FILENAME = "config.toml"
LEGACY_CONFIG_FILENAMES: tuple[str, ...] = ("config.yml", "config.yaml")
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
    path: str = Field(default="frida-server", validation_alias=AliasChoices("path", "servername"))
    host: str = "127.0.0.1:27042"
    version: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_duplicate_path_keys(cls, data: object) -> object:
        if isinstance(data, dict) and "path" in data and "servername" in data:
            raise ValueError("server config cannot specify both `path` and legacy `servername`; use `path`")
        return data

    @property
    def is_remote(self) -> bool:
        return self.host not in {"local", "local://", "usb", "usb://"}

    @property
    def servername(self) -> str:
        return self.path


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

    output_dir: Path | None = None


class ScriptElfToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: Path | None = None


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
    elftools: ScriptElfToolsConfig = Field(default_factory=ScriptElfToolsConfig)
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
    def from_file(cls, filepath: str | Path) -> "AppConfig":
        path = Path(filepath).expanduser().resolve()
        suffix = path.suffix.lower()
        if suffix == ".toml":
            return cls.from_toml(path)
        if suffix in {".yml", ".yaml"}:
            return cls.from_yaml(path)
        raise ValueError(f"unsupported config format for `{path}`; expected .toml, .yml, or .yaml")

    @classmethod
    def from_toml(cls, filepath: str | Path) -> "AppConfig":
        path = Path(filepath).expanduser().resolve()
        with path.open("rb") as handle:
            data = tomllib.load(handle) or {}
        config = cls.model_validate(data)
        return config.resolve_paths(path.parent, source_path=path)

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
                                "output_dir": resolve(self.script.dextools.output_dir),
                            }
                        ),
                        "elftools": self.script.elftools.model_copy(
                            update={
                                "output_dir": resolve(self.script.elftools.output_dir),
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

    def to_data(self, *, exclude_none: bool = True) -> dict[str, Any]:
        raw = self.model_dump(mode="python", exclude={"source_path"}, exclude_none=exclude_none)
        return _serialize_config_value(raw)

    def to_toml_text(self) -> str:
        return _render_toml_document(self.to_data())

    def to_yaml_data(self) -> dict[str, Any]:
        return self.to_data()


def resolve_default_config_path(filepath: str | Path) -> Path:
    candidate = Path(filepath).expanduser()
    if candidate.exists():
        return candidate.resolve()
    if candidate.name == DEFAULT_CONFIG_FILENAME:
        for legacy_name in LEGACY_CONFIG_FILENAMES:
            legacy_candidate = candidate.with_name(legacy_name)
            if legacy_candidate.exists():
                return legacy_candidate.resolve()
    return candidate.resolve()


def _render_toml_document(data: dict[str, Any]) -> str:
    blocks = _render_toml_blocks(data)
    return "\n\n".join(block for block in blocks if block) + "\n"


def _render_toml_blocks(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> list[str]:
    scalars: list[str] = []
    blocks: list[str] = []
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            blocks.extend(_render_toml_blocks(value, (*prefix, key)))
            continue
        scalars.append(f"{key} = {_render_toml_value(value)}")

    header = f"[{'.'.join(prefix)}]" if prefix else ""
    current_block = "\n".join([*( [header] if header and scalars else [] ), *scalars])
    return ([current_block] if current_block else []) + blocks


def _render_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _quote_toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_render_toml_value(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value: {value!r}")


def _serialize_config_value(value: Any) -> Any:
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, dict):
        return {key: _serialize_config_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_config_value(item) for item in value]
    return value


def _quote_toml_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\f", "\\f")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'
