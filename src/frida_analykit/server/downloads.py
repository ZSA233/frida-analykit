from __future__ import annotations

import json
import lzma
import shutil
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

from ..diagnostics import verbose_echo
from .helpers import _resolve_local_source
from .models import DownloadProgressCallback, DownloadedServer, ServerManagerError
from .runtime import ServerRuntime


class ServerDownloader:
    def __init__(self, runtime: ServerRuntime) -> None:
        self._runtime = runtime

    def prepare_local_server_binary(self, local_source: Path) -> Path:
        resolved = _resolve_local_source(local_source)
        destination_root = self._runtime.cache_dir / "local"
        if resolved.suffix == ".xz":
            target_name = resolved.name[: -len(".xz")]
            destination = destination_root / target_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            verbose_echo(f"extracting local frida-server archive `{resolved}` to `{destination}`")
            with lzma.open(resolved, "rb") as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
        else:
            destination = destination_root / resolved.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            verbose_echo(f"copying local frida-server binary `{resolved}` to `{destination}`")
            shutil.copyfile(resolved, destination)
        destination.chmod(0o755)
        return destination

    def download_server_binary(
        self,
        version: str,
        *,
        device_abi: str,
        asset_arch: str,
        force: bool = False,
        progress_callback: DownloadProgressCallback | None = None,
    ) -> DownloadedServer:
        release = self._load_release_metadata(version)
        expected_name = f"frida-server-{version}-{asset_arch}.xz"
        verbose_echo(f"looking for Frida server asset `{expected_name}` for device ABI `{device_abi}`")
        for asset in release.get("assets", []):
            if not isinstance(asset, dict) or asset.get("name") != expected_name:
                continue
            asset_name = str(asset["name"])
            archive_path = self._runtime.cache_dir / version / asset_name
            binary_path = archive_path.with_suffix("")
            if force or not archive_path.exists():
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                verbose_echo(f"downloading `{asset_name}` to `{archive_path}`")
                self._download_to_path(
                    str(asset["browser_download_url"]),
                    archive_path,
                    progress_callback=progress_callback,
                )
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
            if isinstance(asset, dict) and str(asset.get("name", "")).startswith("frida-server-")
        )
        raise ServerManagerError(
            f"release {version} does not provide `{expected_name}`. "
            f"Available server assets: {', '.join(available) if available else 'none'}"
        )

    def _load_release_metadata(self, version: str) -> dict[str, object]:
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
                with self._runtime.urlopen_func(request) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code == 404:
                    errors.append(f"{tag}: 404")
                    continue
                raise ServerManagerError(f"failed to load Frida release metadata for {version}: HTTP {exc.code}") from exc
            except URLError as exc:
                raise ServerManagerError(f"failed to load Frida release metadata for {version}: {exc.reason}") from exc
        raise ServerManagerError(f"unable to find a Frida release tagged {version}. Tried: {', '.join(errors)}")

    def _download_to_path(
        self,
        url: str,
        destination: Path,
        *,
        progress_callback: DownloadProgressCallback | None = None,
    ) -> None:
        verbose_echo(f"downloading release asset from `{url}`")
        request = Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "frida-analykit",
            },
        )
        try:
            with self._runtime.urlopen_func(request) as response, destination.open("wb") as handle:
                header_value = None
                headers = response.headers
                if headers is not None:
                    header_value = headers.get("Content-Length")
                total_bytes = int(header_value) if header_value and header_value.isdigit() else None
                downloaded = 0
                if progress_callback is not None:
                    progress_callback(0, total_bytes)
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, total_bytes)
        except HTTPError as exc:
            raise ServerManagerError(f"failed to download `{url}`: HTTP {exc.code}") from exc
        except URLError as exc:
            raise ServerManagerError(f"failed to download `{url}`: {exc.reason}") from exc
