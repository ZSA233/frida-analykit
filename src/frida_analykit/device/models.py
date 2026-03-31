from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class DeviceSelectionError(RuntimeError):
    pass


class DeviceAppResolutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ConnectedAndroidDevice:
    serial: str
    state: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class DeviceWorkspace:
    root: Path
    config_path: Path
    agent_path: Path
    log_path: Path


@dataclass(frozen=True, slots=True)
class AppProbeResult:
    ok: bool
    package: str
    reason: str | None = None
