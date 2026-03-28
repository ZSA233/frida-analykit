from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .runtime import PopenProcess

class ServerManagerError(RuntimeError):
    pass


DownloadProgressCallback = Callable[[int, int | None], None]


@dataclass(frozen=True)
class DownloadedServer:
    version: str
    device_abi: str
    asset_arch: str
    asset_name: str
    download_url: str
    archive_path: Path
    binary_path: Path


@dataclass(frozen=True)
class RemoteServerStatus:
    selected_version: str
    configured_version: str | None
    server_path: str
    adb_target: str | None
    exists: bool
    executable: bool
    installed_version: str | None
    supported: bool | None
    matched_profile: str | None
    device_abi: str | None
    asset_arch: str | None
    error: str | None = None


@dataclass(frozen=True)
class ServerInstallResult:
    selected_version: str
    device_abi: str | None
    asset_arch: str | None
    local_binary: Path
    remote_path: str
    installed_version: str | None
    local_source: Path | None = None
    local_source_abi_hint: str | None = None
    local_source_asset_arch_hint: str | None = None


@dataclass(frozen=True)
class _ShellCommand:
    args: tuple[str, ...]
    label: str


@dataclass(frozen=True)
class _BootExecutionResult:
    command: list[str]
    process: PopenProcess
    root_label: str
    returncode: int | None = None
    stdout: str | None = None
    stderr: str | None = None
