from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from .._version import __version__
from .paths import _activate_path, _binary_path, _python_path


class EnvError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManagedEnv:
    name: str
    path: str
    frida_version: str
    source_kind: str
    source_value: str
    last_updated: str
    frida_analykit_version: str = __version__
    legacy: bool = False

    @property
    def env_dir(self) -> Path:
        return Path(self.path)

    @property
    def python_path(self) -> Path:
        return _python_path(self.env_dir)

    @property
    def activate_path(self) -> Path:
        return _activate_path(self.env_dir)

    @property
    def frida_cli_path(self) -> Path:
        return _binary_path(self.env_dir, "frida")

    @property
    def frida_analykit_path(self) -> Path:
        return _binary_path(self.env_dir, "frida-analykit")

    @property
    def source_label(self) -> str:
        return f"{self.source_kind}:{self.source_value}"

    def to_record(self) -> "ManagedEnvRecord":
        return {
            "name": self.name,
            "path": self.path,
            "frida_version": self.frida_version,
            "frida_analykit_version": self.frida_analykit_version,
            "source_kind": self.source_kind,
            "source_value": self.source_value,
            "last_updated": self.last_updated,
            "legacy": self.legacy,
        }


class ManagedEnvRecord(TypedDict):
    name: str
    path: str
    frida_version: str
    frida_analykit_version: str
    source_kind: str
    source_value: str
    last_updated: str
    legacy: bool


class RegistryPayload(TypedDict):
    current: str | None
    envs: list[ManagedEnvRecord]
