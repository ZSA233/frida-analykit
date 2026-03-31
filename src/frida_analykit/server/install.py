from __future__ import annotations

import shlex
from pathlib import Path, PurePosixPath

import frida

from ..compat import Version
from ..config import AppConfig
from ..diagnostics import verbose_echo
from .adb import ServerAdbClient
from .constants import (
    _ABI_PROPERTY_PREFIXES,
    _ABI_PROPERTY_SUFFIXES,
    _ANDROID_ABI_TO_ASSET,
    _ASSET_TO_DISPLAY_ABI,
    _UNAME_TO_ASSET,
)
from .downloads import ServerDownloader
from .helpers import (
    _combined_output,
    _describe_local_asset,
    _extract_version,
    _extract_version_from_local_source,
    _iter_abi_candidates,
    _resolve_local_source,
    _summarize_probe_output,
    require_host_port,
    resolve_remote_device_config,
    resolve_remote_device_target,
)
from .models import DownloadProgressCallback, RemoteServerStatus, ServerInstallResult, ServerManagerError
from .runtime import ServerRuntime


class ServerInstaller:
    def __init__(
        self,
        runtime: ServerRuntime,
        adb: ServerAdbClient,
        downloader: ServerDownloader,
    ) -> None:
        self._runtime = runtime
        self._adb = adb
        self._downloader = downloader

    def resolve_server_version(
        self,
        config: AppConfig,
        *,
        version_override: str | None = None,
    ) -> str:
        resolved, _ = self.resolve_server_version_with_source(
            config,
            version_override=version_override,
        )
        return resolved

    def resolve_server_version_with_source(
        self,
        config: AppConfig,
        *,
        version_override: str | None = None,
    ) -> tuple[str, str]:
        resolved = version_override or config.server.version or str(self._runtime.compat.installed_version)
        if version_override is not None:
            source = "--version"
        elif config.server.version:
            source = "config.server.version"
        else:
            source = "installed Frida"
        verbose_echo(
            "resolved frida-server version "
            f"`{resolved}` (override={version_override or 'none'}, "
            f"config={config.server.version or 'none'}, "
            f"installed-frida={self._runtime.compat.installed_version})"
        )
        return resolved, source

    def resolve_target_config(self, config: AppConfig, *, action: str) -> AppConfig:
        return resolve_remote_device_config(
            config,
            adb_executable=self._runtime.adb_executable,
            subprocess_run=self._runtime.subprocess_run,
            action=action,
        )

    def resolve_target_config_with_source(
        self,
        config: AppConfig,
        *,
        action: str,
    ) -> tuple[AppConfig, str]:
        return resolve_remote_device_target(
            config,
            adb_executable=self._runtime.adb_executable,
            subprocess_run=self._runtime.subprocess_run,
            action=action,
        )

    def inspect_remote_server(
        self,
        config: AppConfig,
        *,
        probe_abi: bool = True,
        probe_host: bool = False,
    ) -> RemoteServerStatus:
        config, resolved_device_source = self.resolve_target_config_with_source(
            config,
            action="remote server inspection",
        )
        selected_version, selected_version_source = self.resolve_server_version_with_source(config)
        adb_target = self.resolve_adb_target(config)
        resolved_device = config.server.device
        device_abi: str | None = None
        asset_arch: str | None = None
        abi_error: str | None = None
        host_reachable: bool | None = None
        host_error: str | None = None
        protocol_compatible: bool | None = None
        protocol_error: str | None = None

        if probe_abi:
            try:
                device_abi, asset_arch = self.detect_device_abi(config)
            except ServerManagerError as exc:
                abi_error = str(exc)

        remote_path = config.server.servername
        exists_probe = self._adb.shell_with_auto_root(
            config,
            f"ls {shlex.quote(remote_path)}",
            check=False,
        )
        exists = exists_probe.returncode == 0
        executable = False
        installed_version: str | None = None

        if exists:
            version_output = self._adb.probe_remote_binary_version(config, remote_path)
            installed_version = _extract_version(
                "\n".join(part for part in (version_output.stdout, version_output.stderr) if part)
            )
            executable = version_output.returncode == 0 and installed_version is not None

        matched_profile = None
        supported: bool | None = None
        version_matches_target: bool | None = None
        if installed_version is not None:
            profile = self._runtime.compat.matched_profile(Version.parse(installed_version))
            matched_profile = profile.name if profile else None
            supported = profile is not None
            version_matches_target = installed_version == selected_version

        if probe_host:
            host_reachable, host_error, protocol_compatible, protocol_error = self._probe_remote_host(config)

        return RemoteServerStatus(
            selected_version=selected_version,
            selected_version_source=selected_version_source,
            configured_version=config.server.version,
            server_path=remote_path,
            adb_target=adb_target,
            resolved_device=resolved_device,
            resolved_device_source=resolved_device_source,
            exists=exists,
            executable=executable,
            installed_version=installed_version,
            version_matches_target=version_matches_target,
            supported=supported,
            matched_profile=matched_profile,
            device_abi=device_abi,
            asset_arch=asset_arch,
            host_reachable=host_reachable,
            host_error=host_error,
            protocol_compatible=protocol_compatible,
            protocol_error=protocol_error,
            error=abi_error,
        )

    def _probe_remote_host(self, config: AppConfig) -> tuple[bool | None, str | None, bool | None, str | None]:
        try:
            self.ensure_remote_forward(config, action="remote host probe")
            device = self._runtime.compat.get_device(config.server.host, device_id=config.server.device)
            enumerate_processes = getattr(device, "enumerate_processes", None)
            if callable(enumerate_processes):
                enumerate_processes()
            return True, None, True, None
        except frida.ProtocolError as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            return True, None, False, detail
        except (frida.TransportError, frida.ServerNotRunningError) as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            return False, detail, None, None
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            lowered = detail.lower()
            if "connection closed" in lowered or "connection refused" in lowered or "timed out" in lowered:
                return False, detail, None, None
            return False, detail, None, None

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
        if local_server_path is not None and version_override is not None:
            raise ServerManagerError("`--local-server` cannot be combined with `--version`")
        if local_server_path is not None and force_download:
            raise ServerManagerError("`--force-download` can only be used together with `--version`")
        if local_server_path is None and version_override is None and force_download:
            raise ServerManagerError("`--force-download` requires an explicit `--version`")

        local_source = _resolve_local_source(local_server_path) if local_server_path is not None else None
        config = self.resolve_target_config(config, action="remote server installation")
        local_source_abi_hint: str | None = None
        local_source_asset_arch_hint: str | None = None
        if local_source is not None:
            selected_version = _extract_version_from_local_source(local_source) or "local"
            local_source_abi_hint, local_source_asset_arch_hint = _describe_local_asset(local_source)
            device_abi = None
            asset_arch = None
        else:
            selected_version = self.resolve_server_version(config, version_override=version_override)
            device_abi, asset_arch = self.detect_device_abi(config)
        if asset_arch_override is not None:
            asset_arch = asset_arch_override
            device_abi = _ASSET_TO_DISPLAY_ABI.get(asset_arch_override)
            verbose_echo(f"overriding detected asset arch with `{asset_arch_override}`")

        if local_source is not None:
            local_binary = self._downloader.prepare_local_server_binary(local_source)
        else:
            assert device_abi is not None
            assert asset_arch is not None
            downloaded = self._downloader.download_server_binary(
                selected_version,
                device_abi=device_abi,
                asset_arch=asset_arch,
                force=force_download,
                progress_callback=download_progress,
            )
            local_binary = downloaded.binary_path

        remote_path = config.server.servername
        temp_name = f".frida-analykit-{PurePosixPath(remote_path).name}-{selected_version}"
        temp_remote_path = f"/data/local/tmp/{temp_name}"
        remote_dir = str(PurePosixPath(remote_path).parent)

        try:
            self._adb.run_adb(
                config,
                ["push", str(local_binary), temp_remote_path],
                capture_output=True,
            )
            quoted_temp = shlex.quote(temp_remote_path)
            quoted_remote = shlex.quote(remote_path)
            quoted_remote_dir = shlex.quote(remote_dir)
            self._adb.shell_with_auto_root(config, f"mkdir -p {quoted_remote_dir}")
            self._adb.shell_with_auto_root(config, f"mv {quoted_temp} {quoted_remote}")
            self._adb.shell_with_auto_root(config, f"chmod 755 {quoted_remote}")
        finally:
            self._adb.shell_with_auto_root(
                config,
                f"rm -f {shlex.quote(temp_remote_path)}",
                check=False,
            )

        status = self.inspect_remote_server(config, probe_abi=local_source is None)
        self._validate_installed_server(
            status,
            selected_version=selected_version,
            local_source=local_source,
            local_source_abi_hint=local_source_abi_hint,
            local_source_asset_arch_hint=local_source_asset_arch_hint,
        )
        return ServerInstallResult(
            selected_version=selected_version,
            device_abi=device_abi,
            asset_arch=asset_arch,
            local_binary=local_binary,
            remote_path=remote_path,
            installed_version=status.installed_version,
            local_source=local_source,
            local_source_abi_hint=local_source_abi_hint,
            local_source_asset_arch_hint=local_source_asset_arch_hint,
        )

    def detect_device_abi(self, config: AppConfig) -> tuple[str, str]:
        config = self.resolve_target_config(config, action="device ABI detection")
        seen_outputs: list[str] = []
        property_commands = [
            f"getprop {prefix}.{suffix}"
            for prefix in _ABI_PROPERTY_PREFIXES
            for suffix in _ABI_PROPERTY_SUFFIXES
        ]
        commands = [
            *property_commands,
            "getprop",
            "uname -m",
            "cat /proc/cpuinfo",
        ]
        for command in commands:
            verbose_echo(f"probing device ABI with `{command}`")
            result = self._adb.shell(config, command, check=False)
            self._raise_transport_error_if_needed(result, command=command, action="device ABI detection")
            output = result.stdout.strip()
            if not output:
                continue
            seen_outputs.append(_summarize_probe_output(command, output))
            for candidate in _iter_abi_candidates(output):
                if candidate in _ANDROID_ABI_TO_ASSET:
                    return candidate, _ANDROID_ABI_TO_ASSET[candidate]
                if candidate in _UNAME_TO_ASSET:
                    return _UNAME_TO_ASSET[candidate]
        details = ", ".join(seen_outputs) if seen_outputs else "no ABI properties returned"
        raise ServerManagerError(f"unable to map device ABI to a Frida server asset ({details})")

    def resolve_adb_target(self, config: AppConfig) -> str | None:
        config = self.resolve_target_config(config, action="adb target resolution")
        result = self._adb.run_adb(
            config,
            ["get-serialno"],
            capture_output=True,
            check=False,
        )
        self._raise_transport_error_if_needed(result, command="get-serialno", action="adb target resolution")
        if result.returncode != 0:
            return None
        serial = result.stdout.strip()
        if not serial or serial == "unknown":
            return None
        return serial

    def ensure_remote_forward(self, config: AppConfig, *, action: str = "remote port forward") -> str:
        config = self.resolve_target_config(config, action=action)
        port = require_host_port(config.server.host, action=action)
        self._adb.run_adb(
            config,
            ["forward", f"tcp:{port}", f"tcp:{port}"],
            capture_output=True,
            check=True,
        )
        return port

    @staticmethod
    def _raise_transport_error_if_needed(
        result,
        *,
        command: str,
        action: str,
    ) -> None:
        if result.returncode == 0:
            return
        combined = _combined_output(result).strip()
        lowered = combined.lower()
        transport_markers = (
            "more than one device/emulator",
            "device not found",
            "no devices/emulators found",
        )
        if any(marker in lowered for marker in transport_markers):
            raise ServerManagerError(f"{action} failed while running `{command}`: {combined or 'adb transport error'}")

    def _validate_installed_server(
        self,
        status: RemoteServerStatus,
        *,
        selected_version: str,
        local_source: Path | None,
        local_source_abi_hint: str | None,
        local_source_asset_arch_hint: str | None,
    ) -> None:
        if not status.exists:
            raise ServerManagerError(
                f"installed server validation failed at `{status.server_path}`: "
                f"exists={status.exists}, executable={status.executable}"
            )
        if not status.executable or status.installed_version is None:
            details = (
                f"exists={status.exists}, executable={status.executable}, "
                f"installed_version={status.installed_version or 'unknown'}"
            )
            hint = ""
            if local_source is not None:
                if local_source_abi_hint and local_source_asset_arch_hint:
                    hint = (
                        f"; local source hint {local_source_abi_hint} "
                        f"({local_source_asset_arch_hint}) from `{local_source}`"
                    )
                else:
                    hint = f"; local source `{local_source}`"
            raise ServerManagerError(
                f"installed server validation failed at `{status.server_path}`: {details}{hint}"
            )
        if local_source is None and status.installed_version != selected_version:
            raise ServerManagerError(
                f"installed server version mismatch at `{status.server_path}`: expected {selected_version}, "
                f"found {status.installed_version}"
            )
