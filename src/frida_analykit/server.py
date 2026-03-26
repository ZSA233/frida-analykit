from __future__ import annotations

import json
import lzma
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .compat import FridaCompat, Version
from .config import AppConfig
from .diagnostics import format_command, verbose_echo

_ANDROID_ABI_TO_ASSET = {
    "arm64-v8a": "android-arm64",
    "armeabi-v7a": "android-arm",
    "armeabi": "android-arm",
    "x86_64": "android-x86_64",
    "x86": "android-x86",
}

_UNAME_TO_ASSET = {
    "aarch64": ("arm64-v8a", "android-arm64"),
    "armv8l": ("arm64-v8a", "android-arm64"),
    "armv7l": ("armeabi-v7a", "android-arm"),
    "armv7": ("armeabi-v7a", "android-arm"),
    "arm": ("armeabi-v7a", "android-arm"),
    "i686": ("x86", "android-x86"),
    "i386": ("x86", "android-x86"),
    "x86_64": ("x86_64", "android-x86_64"),
}

_VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z._-]+)?")
_ABI_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(arm64-v8a|armeabi-v7a|armeabi|x86_64|x86|aarch64|armv8l|armv7l|armv7|i686|i386)(?![A-Za-z0-9_])"
)


class ServerManagerError(RuntimeError):
    pass


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
    device_abi: str
    asset_arch: str
    local_binary: Path
    remote_path: str
    installed_version: str | None


def _default_cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "frida-analykit" / "frida-server"


def _extract_version(text: str) -> str | None:
    match = _VERSION_PATTERN.search(text)
    return match.group(0) if match else None


def _iter_abi_candidates(raw: str) -> list[str]:
    return [match.group(1) for match in _ABI_TOKEN_PATTERN.finditer(raw)]


def _adb_prefix(config: AppConfig, adb_executable: str = "adb") -> list[str]:
    prefix = [adb_executable]
    if config.server.device:
        prefix.extend(["-s", config.server.device])
    return prefix


class FridaServerManager:
    def __init__(
        self,
        *,
        compat: FridaCompat | None = None,
        urlopen_func: Callable[..., Any] = urlopen,
        subprocess_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        subprocess_popen: Callable[..., Any] = subprocess.Popen,
        cache_dir: Path | None = None,
        adb_executable: str = "adb",
    ) -> None:
        self._compat = compat or FridaCompat()
        self._urlopen = urlopen_func
        self._subprocess_run = subprocess_run
        self._subprocess_popen = subprocess_popen
        self._cache_dir = cache_dir or _default_cache_dir()
        self._adb_executable = adb_executable

    def resolve_server_version(
        self,
        config: AppConfig,
        *,
        version_override: str | None = None,
    ) -> str:
        resolved = version_override or config.server.version or str(self._compat.installed_version)
        verbose_echo(
            "resolved frida-server version "
            f"`{resolved}` (override={version_override or 'none'}, "
            f"config={config.server.version or 'none'}, "
            f"installed-frida={self._compat.installed_version})"
        )
        return resolved

    def inspect_remote_server(self, config: AppConfig) -> RemoteServerStatus:
        self._ensure_remote_config(config, action="remote server inspection")
        selected_version = self.resolve_server_version(config)
        device_abi: str | None = None
        asset_arch: str | None = None
        abi_error: str | None = None

        try:
            device_abi, asset_arch = self.detect_device_abi(config)
        except ServerManagerError as exc:
            abi_error = str(exc)

        remote_path = config.server.servername
        quoted_path = shlex.quote(remote_path)
        exists_probe = self._shell(
            config,
            f"ls {quoted_path}",
            as_root=True,
            check=False,
        )
        exists = exists_probe.returncode == 0
        executable = False
        installed_version: str | None = None

        if exists:
            version_output = self._shell(
                config,
                f"{quoted_path} --version",
                as_root=True,
                check=False,
            )
            installed_version = _extract_version(
                "\n".join(part for part in (version_output.stdout, version_output.stderr) if part)
            )
            executable = version_output.returncode == 0 and installed_version is not None

        matched_profile = None
        supported: bool | None = None
        if installed_version is not None:
            profile = self._compat.matched_profile(Version.parse(installed_version))
            matched_profile = profile.name if profile else None
            supported = profile is not None

        return RemoteServerStatus(
            selected_version=selected_version,
            configured_version=config.server.version,
            server_path=remote_path,
            exists=exists,
            executable=executable,
            installed_version=installed_version,
            supported=supported,
            matched_profile=matched_profile,
            device_abi=device_abi,
            asset_arch=asset_arch,
            error=abi_error,
        )

    def install_remote_server(
        self,
        config: AppConfig,
        *,
        version_override: str | None = None,
        asset_arch_override: str | None = None,
        force_download: bool = False,
    ) -> ServerInstallResult:
        self._ensure_remote_config(config, action="remote server installation")
        selected_version = self.resolve_server_version(config, version_override=version_override)
        device_abi, asset_arch = self.detect_device_abi(config)
        if asset_arch_override is not None:
            asset_arch = asset_arch_override
            device_abi = asset_arch_override
            verbose_echo(f"overriding detected asset arch with `{asset_arch_override}`")

        downloaded = self.download_server_binary(
            selected_version,
            device_abi=device_abi,
            asset_arch=asset_arch,
            force=force_download,
        )

        remote_path = config.server.servername
        temp_name = f".frida-analykit-{PurePosixPath(remote_path).name}-{selected_version}"
        temp_remote_path = f"/data/local/tmp/{temp_name}"
        remote_dir = str(PurePosixPath(remote_path).parent)

        try:
            self._run_adb(
                config,
                ["push", str(downloaded.binary_path), temp_remote_path],
                capture_output=True,
            )
            quoted_temp = shlex.quote(temp_remote_path)
            quoted_remote = shlex.quote(remote_path)
            quoted_remote_dir = shlex.quote(remote_dir)
            self._shell(config, f"mkdir -p {quoted_remote_dir}", as_root=True)
            self._shell(config, f"mv {quoted_temp} {quoted_remote}", as_root=True)
            self._shell(config, f"chmod 755 {quoted_remote}", as_root=True)
        finally:
            self._shell(
                config,
                f"rm -f {shlex.quote(temp_remote_path)}",
                as_root=True,
                check=False,
            )

        status = self.inspect_remote_server(config)
        return ServerInstallResult(
            selected_version=selected_version,
            device_abi=device_abi,
            asset_arch=asset_arch,
            local_binary=downloaded.binary_path,
            remote_path=remote_path,
            installed_version=status.installed_version,
        )

    def boot_remote_server(self, config: AppConfig) -> None:
        self._ensure_remote_config(config, action="server boot")

        try:
            _, port = config.server.host.rsplit(":", 1)
        except ValueError as exc:
            raise ServerManagerError(
                f"server boot requires `server.host` in `host:port` format, got `{config.server.host}`"
            ) from exc

        try:
            self._run_adb(
                config,
                ["forward", f"tcp:{port}", f"tcp:{port}"],
                check=True,
            )
            before_pids = self.list_remote_server_pids(config)

            server_path = shlex.quote(config.server.servername)
            version_probe = self._shell(
                config,
                f"{server_path} --version",
                as_root=True,
                check=False,
            )
            installed_version = _extract_version(
                "\n".join(part for part in (version_probe.stdout, version_probe.stderr) if part)
            )
            if version_probe.returncode != 0:
                raise ServerManagerError(
                    f"failed to execute `{config.server.servername} --version` on the target device"
                )
            if installed_version is None:
                verbose_echo(
                    f"unable to parse a frida-server version from `{config.server.servername} --version`; continuing with boot"
                )

            launch_command = f"{server_path} -l 0.0.0.0:{port}"
            process = self._popen_adb(
                config,
                ["shell", self._remote_shell_command(launch_command, as_root=True)],
            )
            try:
                returncode = process.wait()
            except KeyboardInterrupt:
                verbose_echo("keyboard interrupt received while waiting for remote frida-server")
                self._terminate_process(process)
                self.cleanup_booted_remote_server(config, before_pids=before_pids)
                return

            if returncode != 0:
                raise ServerManagerError(
                    f"`{config.server.servername} -l 0.0.0.0:{port}` exited with code {returncode}"
                )
        finally:
            self._remove_forward(config, port)

    def detect_device_abi(self, config: AppConfig) -> tuple[str, str]:
        self._ensure_remote_config(config, action="device ABI detection")
        commands = (
            "getprop ro.product.cpu.abilist64",
            "getprop ro.product.cpu.abilist",
            "getprop ro.product.cpu.abi",
            "uname -m",
        )
        seen_outputs: list[str] = []
        for command in commands:
            verbose_echo(f"probing device ABI with `{command}`")
            result = self._shell(config, command, check=False)
            output = result.stdout.strip()
            if not output:
                continue
            seen_outputs.append(output)
            for candidate in _iter_abi_candidates(output):
                if candidate in _ANDROID_ABI_TO_ASSET:
                    return candidate, _ANDROID_ABI_TO_ASSET[candidate]
                if candidate in _UNAME_TO_ASSET:
                    return _UNAME_TO_ASSET[candidate]
        details = ", ".join(seen_outputs) if seen_outputs else "no ABI properties returned"
        raise ServerManagerError(f"unable to map device ABI to a Frida server asset ({details})")

    def list_remote_server_pids(self, config: AppConfig) -> set[int]:
        self._ensure_remote_config(config, action="remote server pid lookup")
        basename = PurePosixPath(config.server.servername).name
        identifiers = (config.server.servername, basename)

        pidof_candidates = [config.server.servername]
        if basename != config.server.servername:
            pidof_candidates.append(basename)

        for candidate in pidof_candidates:
            result = self._shell(
                config,
                f"pidof {shlex.quote(candidate)}",
                as_root=True,
                check=False,
            )
            pids = self._parse_pid_list(result.stdout)
            if pids:
                verbose_echo(f"resolved remote server pids via pidof `{candidate}`: {sorted(pids)}")
                return pids

        for command in ("ps -A", "ps"):
            result = self._shell(config, command, as_root=True, check=False)
            pids = self._parse_ps_pid_list(result.stdout, identifiers=identifiers)
            if pids:
                verbose_echo(f"resolved remote server pids via `{command}`: {sorted(pids)}")
                return pids
        return set()

    def cleanup_booted_remote_server(self, config: AppConfig, *, before_pids: set[int]) -> None:
        launched_pids = self._find_new_remote_server_pids(config, before_pids=before_pids)
        if not launched_pids:
            verbose_echo("no newly launched remote frida-server process detected during cleanup")
            return
        verbose_echo(f"cleaning up remote frida-server pids: {sorted(launched_pids)}")
        self._kill_remote_pids(config, launched_pids)

    def download_server_binary(
        self,
        version: str,
        *,
        device_abi: str,
        asset_arch: str,
        force: bool = False,
    ) -> DownloadedServer:
        release = self._load_release_metadata(version)
        expected_name = f"frida-server-{version}-{asset_arch}.xz"
        verbose_echo(
            f"looking for Frida server asset `{expected_name}` for device ABI `{device_abi}`"
        )
        for asset in release.get("assets", []):
            if asset.get("name") != expected_name:
                continue
            asset_name = str(asset["name"])
            archive_path = self._cache_dir / version / asset_name
            binary_path = archive_path.with_suffix("")
            if force or not archive_path.exists():
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                verbose_echo(f"downloading `{asset_name}` to `{archive_path}`")
                self._download_to_path(str(asset["browser_download_url"]), archive_path)
            if force or not binary_path.exists():
                binary_path.parent.mkdir(parents=True, exist_ok=True)
                verbose_echo(f"extracting `{archive_path}` to `{binary_path}`")
                with lzma.open(archive_path, "rb") as source, binary_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
            binary_path.chmod(0o755)
            return DownloadedServer(
                version=version,
                device_abi=device_abi,
                asset_arch=asset_arch,
                asset_name=asset_name,
                download_url=str(asset["browser_download_url"]),
                archive_path=archive_path,
                binary_path=binary_path,
            )
        available = sorted(
            str(asset["name"])
            for asset in release.get("assets", [])
            if str(asset.get("name", "")).startswith("frida-server-")
        )
        raise ServerManagerError(
            f"release {version} does not provide `{expected_name}`. "
            f"Available server assets: {', '.join(available) if available else 'none'}"
        )

    def _load_release_metadata(self, version: str) -> dict[str, Any]:
        errors: list[str] = []
        for tag in (version, f"v{version}"):
            url = f"https://api.github.com/repos/frida/frida/releases/tags/{tag}"
            verbose_echo(f"loading Frida release metadata from `{url}`")
            request = Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "frida-analykit",
                },
            )
            try:
                with self._urlopen(request) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code == 404:
                    errors.append(f"{tag}: 404")
                    continue
                raise ServerManagerError(f"failed to load Frida release metadata for {version}: HTTP {exc.code}") from exc
            except URLError as exc:
                raise ServerManagerError(f"failed to load Frida release metadata for {version}: {exc.reason}") from exc
        raise ServerManagerError(
            f"unable to find a Frida release tagged {version}. Tried: {', '.join(errors)}"
        )

    def _download_to_path(self, url: str, destination: Path) -> None:
        verbose_echo(f"downloading release asset from `{url}`")
        request = Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "frida-analykit",
            },
        )
        try:
            with self._urlopen(request) as response, destination.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        except HTTPError as exc:
            raise ServerManagerError(f"failed to download `{url}`: HTTP {exc.code}") from exc
        except URLError as exc:
            raise ServerManagerError(f"failed to download `{url}`: {exc.reason}") from exc

    def _remove_forward(self, config: AppConfig, port: str) -> None:
        self._run_adb(
            config,
            ["forward", "--remove", f"tcp:{port}"],
            capture_output=True,
            check=False,
        )

    def _run_adb(
        self,
        config: AppConfig,
        args: list[str],
        *,
        capture_output: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [*_adb_prefix(config, adb_executable=self._adb_executable), *args]
        verbose_echo(f"running adb command: {format_command(command)}")
        try:
            result = self._subprocess_run(
                command,
                check=check,
                capture_output=capture_output,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            self._log_process_result(
                command=command,
                returncode=exc.returncode,
                stdout=getattr(exc, "stdout", None),
                stderr=getattr(exc, "stderr", None),
            )
            raise
        self._log_process_result(
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        return result

    def _shell(
        self,
        config: AppConfig,
        command: str,
        *,
        as_root: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        shell_args = ["shell", self._remote_shell_command(command, as_root=as_root)]
        verbose_echo(f"remote shell command: {command}")
        return self._run_adb(config, shell_args, capture_output=True, check=check)

    def _popen_adb(self, config: AppConfig, args: list[str]):
        command = [*_adb_prefix(config, adb_executable=self._adb_executable), *args]
        verbose_echo(f"starting adb process: {format_command(command)}")
        try:
            return self._subprocess_popen(command)
        except OSError as exc:
            raise ServerManagerError(
                f"failed to start `{format_command(command)}`: {exc}"
            ) from exc

    @staticmethod
    def _remote_shell_command(command: str, *, as_root: bool) -> str:
        if not as_root:
            return command
        return f"su -c {shlex.quote(command)}"

    @staticmethod
    def _parse_pid_list(raw: str) -> set[int]:
        pids: set[int] = set()
        for token in raw.split():
            if token.isdigit():
                pids.add(int(token))
        return pids

    @classmethod
    def _parse_ps_pid_list(cls, raw: str, *, identifiers: tuple[str, ...]) -> set[int]:
        pids: set[int] = set()
        for line in raw.splitlines():
            if not any(identifier in line for identifier in identifiers):
                continue
            parts = line.split()
            for token in parts[1:]:
                if token.isdigit():
                    pids.add(int(token))
                    break
        return pids

    def _find_new_remote_server_pids(self, config: AppConfig, *, before_pids: set[int]) -> set[int]:
        deadline = time.monotonic() + 2.0
        latest: set[int] = set()
        while time.monotonic() < deadline:
            latest = self.list_remote_server_pids(config)
            new_pids = latest - before_pids
            if new_pids:
                return new_pids
            time.sleep(0.2)
        return latest - before_pids

    def _kill_remote_pids(self, config: AppConfig, pids: set[int]) -> None:
        remaining = set(pids)
        for pid in sorted(remaining):
            self._shell(config, f"kill {pid}", as_root=True, check=False)
        after_term = self.list_remote_server_pids(config)
        remaining &= after_term
        if not remaining:
            return
        verbose_echo(f"force killing remote frida-server pids: {sorted(remaining)}")
        for pid in sorted(remaining):
            self._shell(config, f"kill -9 {pid}", as_root=True, check=False)

    @staticmethod
    def _ensure_remote_config(config: AppConfig, *, action: str) -> None:
        if not config.server.is_remote:
            raise ServerManagerError(f"{action} only supports remote adb-backed targets")

    @staticmethod
    def _log_process_result(
        *,
        command: list[str],
        returncode: int,
        stdout: str | None,
        stderr: str | None,
    ) -> None:
        verbose_echo(f"{format_command(command)} exited with code {returncode}")
        if stdout and stdout.strip():
            verbose_echo(f"stdout from {format_command(command)}:\n{stdout.rstrip()}")
        if stderr and stderr.strip():
            verbose_echo(f"stderr from {format_command(command)}:\n{stderr.rstrip()}")

    @staticmethod
    def _terminate_process(process: Any) -> None:
        try:
            process.terminate()
        except BaseException:
            return
        try:
            process.wait(timeout=5)
        except BaseException:
            try:
                process.kill()
            except BaseException:
                return
            try:
                process.wait(timeout=5)
            except BaseException:
                return


def boot_server(config: AppConfig) -> None:
    FridaServerManager().boot_remote_server(config)
