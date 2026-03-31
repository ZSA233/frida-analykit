from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.request import urlopen

from ..compat import FridaCompat
from ..config import AppConfig
from .adb import ServerAdbClient
from .boot import ServerBootController
from .downloads import ServerDownloader
from .helpers import _default_cache_dir
from .install import ServerInstaller
from .models import DownloadProgressCallback, DownloadedServer, RemoteServerStatus, ServerInstallResult
from .runtime import ServerRuntime, ServerSubprocessPopen, ServerSubprocessRun, UrlOpenFunc


class FridaServerManager:
    def __init__(
        self,
        *,
        compat: FridaCompat | None = None,
        urlopen_func: UrlOpenFunc = urlopen,
        subprocess_run: ServerSubprocessRun = subprocess.run,
        subprocess_popen: ServerSubprocessPopen = subprocess.Popen,
        cache_dir: Path | None = None,
        adb_executable: str = "adb",
    ) -> None:
        runtime = ServerRuntime(
            compat=compat or FridaCompat(),
            urlopen_func=urlopen_func,
            subprocess_run=subprocess_run,
            subprocess_popen=subprocess_popen,
            cache_dir=cache_dir or _default_cache_dir(),
            adb_executable=adb_executable,
        )
        self._runtime = runtime
        self._adb = ServerAdbClient(runtime)
        self._downloader = ServerDownloader(runtime)
        self._installer = ServerInstaller(runtime, self._adb, self._downloader)
        self._boot = ServerBootController(runtime, self._adb, self._installer)

    def resolve_server_version(
        self,
        config: AppConfig,
        *,
        version_override: str | None = None,
    ) -> str:
        return self._installer.resolve_server_version(config, version_override=version_override)

    def resolve_server_version_with_source(
        self,
        config: AppConfig,
        *,
        version_override: str | None = None,
    ) -> tuple[str, str]:
        return self._installer.resolve_server_version_with_source(
            config,
            version_override=version_override,
        )

    def resolve_target_config(self, config: AppConfig, *, action: str) -> AppConfig:
        return self._installer.resolve_target_config(config, action=action)

    def resolve_target_config_with_source(
        self,
        config: AppConfig,
        *,
        action: str,
    ) -> tuple[AppConfig, str]:
        return self._installer.resolve_target_config_with_source(config, action=action)

    def inspect_remote_server(
        self,
        config: AppConfig,
        *,
        probe_abi: bool = True,
        probe_host: bool = False,
    ) -> RemoteServerStatus:
        return self._installer.inspect_remote_server(config, probe_abi=probe_abi, probe_host=probe_host)

    def install_remote_server(
        self,
        config: AppConfig,
        *,
        version_override: str | None = None,
        local_server_path: Path | None = None,
        asset_arch_override: str | None = None,
        force_download: bool = False,
        download_progress: DownloadProgressCallback | None = None,
    ) -> ServerInstallResult:
        return self._installer.install_remote_server(
            config,
            version_override=version_override,
            local_server_path=local_server_path,
            asset_arch_override=asset_arch_override,
            force_download=force_download,
            download_progress=download_progress,
        )

    def detect_device_abi(self, config: AppConfig) -> tuple[str, str]:
        return self._installer.detect_device_abi(config)

    def resolve_adb_target(self, config: AppConfig) -> str | None:
        return self._installer.resolve_adb_target(config)

    def ensure_remote_forward(self, config: AppConfig, *, action: str = "remote port forward") -> str:
        return self._installer.ensure_remote_forward(config, action=action)

    def download_server_binary(
        self,
        version: str,
        *,
        device_abi: str,
        asset_arch: str,
        force: bool = False,
        progress_callback: DownloadProgressCallback | None = None,
    ) -> DownloadedServer:
        return self._downloader.download_server_binary(
            version,
            device_abi=device_abi,
            asset_arch=asset_arch,
            force=force,
            progress_callback=progress_callback,
        )

    def prepare_local_server_binary(self, local_source: Path) -> Path:
        return self._downloader.prepare_local_server_binary(local_source)

    def boot_remote_server(self, config: AppConfig, *, force_restart: bool = False) -> None:
        self._boot.boot_remote_server(config, force_restart=force_restart)

    def stop_remote_server(self, config: AppConfig) -> set[int]:
        return self._boot.stop_remote_server(config)

    def list_remote_server_pids(self, config: AppConfig) -> set[int]:
        return self._boot.list_remote_server_pids(config)
