from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from ..config import AppConfig
from .constants import _ABI_TOKEN_PATTERN, _ANDROID_ABI_TO_ASSET, _ASSET_TO_DISPLAY_ABI, _VERSION_PATTERN
from .models import ServerManagerError


def _default_cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "frida-analykit" / "frida-server"


def _extract_version(text: str) -> str | None:
    match = _VERSION_PATTERN.search(text)
    return match.group(0) if match else None


def _extract_version_from_local_source(path: Path) -> str | None:
    name = path.name
    if name.endswith(".xz"):
        name = name[: -len(".xz")]
    prefix = "frida-server-"
    if name.startswith(prefix):
        payload = name[len(prefix) :]
        asset_arches = sorted(set(_ANDROID_ABI_TO_ASSET.values()), key=len, reverse=True)
        for asset_arch in asset_arches:
            suffix = f"-{asset_arch}"
            if payload.endswith(suffix):
                return payload[: -len(suffix)]
    return _extract_version(name)


def _iter_abi_candidates(raw: str) -> list[str]:
    return [match.group(1).lower() for match in _ABI_TOKEN_PATTERN.finditer(raw)]


def _extract_local_asset_arch(path: Path) -> str | None:
    name = path.name
    if name.endswith(".xz"):
        name = name[: -len(".xz")]
    prefix = "frida-server-"
    if not name.startswith(prefix):
        return None
    payload = name[len(prefix) :]
    asset_arches = sorted(set(_ANDROID_ABI_TO_ASSET.values()), key=len, reverse=True)
    for asset_arch in asset_arches:
        suffix = f"-{asset_arch}"
        if payload.endswith(suffix):
            return asset_arch
    return None


def _describe_local_asset(path: Path) -> tuple[str | None, str | None]:
    asset_arch = _extract_local_asset_arch(path)
    if asset_arch is None:
        return None, None
    return _ASSET_TO_DISPLAY_ABI.get(asset_arch), asset_arch


def _summarize_probe_output(command: str, output: str, *, limit: int = 160) -> str:
    normalized = " ".join(output.split())
    if len(normalized) > limit:
        normalized = f"{normalized[: limit - 3]}..."
    return f"{command}: {normalized}"


def _adb_prefix(config: AppConfig, adb_executable: str = "adb") -> list[str]:
    prefix = [adb_executable]
    if config.server.device:
        prefix.extend(["-s", config.server.device])
    return prefix


def list_connected_adb_devices(
    *,
    adb_executable: str,
    subprocess_run: Callable[..., subprocess.CompletedProcess[str]],
    action: str,
) -> tuple[str, ...]:
    result = subprocess_run(
        [adb_executable, "devices", "-l"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = _combined_output(result).strip() or "adb devices -l failed"
        raise ServerManagerError(f"{action} failed to enumerate adb devices: {detail}")

    devices: list[str] = []
    for line in result.stdout.splitlines():
        value = line.strip()
        if not value or value.startswith("List of devices attached") or value.startswith("* "):
            continue
        parts = value.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return tuple(devices)


def resolve_remote_device_config(
    config: AppConfig,
    *,
    adb_executable: str,
    subprocess_run: Callable[..., subprocess.CompletedProcess[str]],
    action: str,
) -> AppConfig:
    resolved, _ = resolve_remote_device_target(
        config,
        adb_executable=adb_executable,
        subprocess_run=subprocess_run,
        action=action,
    )
    return resolved


def resolve_remote_device_target(
    config: AppConfig,
    *,
    adb_executable: str,
    subprocess_run: Callable[..., subprocess.CompletedProcess[str]],
    action: str,
) -> tuple[AppConfig, str]:
    ensure_remote_config(config, action=action)
    available = list_connected_adb_devices(
        adb_executable=adb_executable,
        subprocess_run=subprocess_run,
        action=action,
    )
    explicit_device = config.server.device
    env_device = os.environ.get("ANDROID_SERIAL")

    if explicit_device:
        if explicit_device not in available:
            raise ServerManagerError(
                f"{action} requested config.server.device `{explicit_device}`, "
                f"but connected devices are: {', '.join(available) or 'none'}"
            )
        return config, "config.server.device"

    if env_device:
        if env_device not in available:
            raise ServerManagerError(
                f"{action} requested ANDROID_SERIAL `{env_device}`, "
                f"but connected devices are: {', '.join(available) or 'none'}"
            )
        return (
            config.model_copy(
                update={
                    "server": config.server.model_copy(update={"device": env_device}),
                }
            ),
            "ANDROID_SERIAL",
        )

    if len(available) == 1:
        return (
            config.model_copy(
                update={
                    "server": config.server.model_copy(update={"device": available[0]}),
                }
            ),
            "single connected adb device",
        )

    if not available:
        raise ServerManagerError(f"{action} requires a connected Android device, but `adb devices -l` found none")

    raise ServerManagerError(
        f"{action} requires a unique Android device; set config.server.device or ANDROID_SERIAL=<serial>. "
        f"connected devices: {', '.join(available)}"
    )


def ensure_remote_config(config: AppConfig, *, action: str) -> None:
    if not config.server.is_remote:
        raise ServerManagerError(f"{action} only supports remote adb-backed targets")


def require_host_port(host: str, *, action: str) -> str:
    try:
        _, port = host.rsplit(":", 1)
    except ValueError as exc:
        raise ServerManagerError(f"{action} requires `server.host` in `host:port` format, got `{host}`") from exc
    return port


def optional_host_port(host: str) -> str | None:
    try:
        return require_host_port(host, action="server stop")
    except ServerManagerError:
        return None


def _resolve_local_source(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    if not candidate.is_file():
        raise ServerManagerError(f"local frida-server source `{path}` does not exist or is not a file")
    return candidate


def _tail_text(text: str | None, *, limit: int = 20) -> str | None:
    if text is None:
        return None
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return None
    return "\n".join(lines[-limit:])


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)
