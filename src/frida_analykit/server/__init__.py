from __future__ import annotations

from .manager import FridaServerManager
from .models import (
    DownloadProgressCallback,
    DownloadedServer,
    RemoteServerStatus,
    ServerInstallResult,
    ServerManagerError,
)


def boot_server(config, *, force_restart: bool = False) -> None:
    FridaServerManager().boot_remote_server(config, force_restart=force_restart)


def stop_server(config) -> set[int]:
    return FridaServerManager().stop_remote_server(config)


__all__ = [
    "DownloadProgressCallback",
    "DownloadedServer",
    "FridaServerManager",
    "RemoteServerStatus",
    "ServerInstallResult",
    "ServerManagerError",
    "boot_server",
    "stop_server",
]
