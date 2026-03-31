from __future__ import annotations

import socket
import subprocess
import zlib
from collections.abc import Sequence
from pathlib import Path

from .defaults import REMOTE_HOST_ADDRESS, REMOTE_PORT_BASE, REMOTE_PORT_COUNT
from .models import ConnectedAndroidDevice, DeviceSelectionError


def safe_device_serial_token(serial: str) -> str:
    token = "".join(char if char.isalnum() else "-" for char in serial)
    token = token.strip("-").lower()
    return token or "unknown-device"


def list_connected_android_devices(
    *,
    adb_executable: str = "adb",
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: int = 30,
) -> tuple[ConnectedAndroidDevice, ...]:
    result = subprocess.run(
        [adb_executable, "devices", "-l"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "adb devices failed"
        raise DeviceSelectionError(f"failed to enumerate adb devices: {detail}")

    devices: list[ConnectedAndroidDevice] = []
    for line in result.stdout.splitlines():
        value = line.strip()
        if not value or value.startswith("List of devices attached"):
            continue
        if value.startswith("* "):
            continue
        parts = value.split()
        if len(parts) < 2:
            continue
        devices.append(
            ConnectedAndroidDevice(
                serial=parts[0],
                state=parts[1],
                description=" ".join(parts[2:]),
            )
        )
    return tuple(devices)


def resolve_device_serial(
    explicit_serial: str | None,
    *,
    multiple_devices_hint: str | None = None,
    adb_executable: str = "adb",
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> str:
    devices = [
        device
        for device in list_connected_android_devices(adb_executable=adb_executable, env=env, cwd=cwd)
        if device.state == "device"
    ]
    if explicit_serial:
        for device in devices:
            if device.serial == explicit_serial:
                return explicit_serial
        raise DeviceSelectionError(
            f"requested ANDROID_SERIAL `{explicit_serial}` is not connected; "
            f"available devices: {', '.join(device.serial for device in devices) or 'none'}"
        )
    if len(devices) == 1:
        return devices[0].serial
    if not devices:
        raise DeviceSelectionError("no connected Android devices were detected by `adb devices -l`")
    hint = multiple_devices_hint or "set ANDROID_SERIAL=<serial> or use `make device-test-all`"
    raise DeviceSelectionError(f"multiple Android devices are connected; {hint}")


def resolve_device_serials(
    requested_serials: Sequence[str] = (),
    *,
    all_devices: bool = False,
    fallback_serial: str | None = None,
    multiple_devices_hint: str | None = None,
    adb_executable: str = "adb",
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[str, ...]:
    devices = [
        device
        for device in list_connected_android_devices(adb_executable=adb_executable, env=env, cwd=cwd)
        if device.state == "device"
    ]
    available = {device.serial for device in devices}
    if requested_serials:
        ordered: list[str] = []
        seen: set[str] = set()
        for serial in requested_serials:
            if serial in seen:
                continue
            seen.add(serial)
            if serial not in available:
                raise DeviceSelectionError(
                    f"requested device `{serial}` is not connected; "
                    f"available devices: {', '.join(sorted(available)) or 'none'}"
                )
            ordered.append(serial)
        return tuple(ordered)
    if fallback_serial:
        return (
            resolve_device_serial(
                fallback_serial,
                multiple_devices_hint=multiple_devices_hint,
                adb_executable=adb_executable,
                env=env,
                cwd=cwd,
            ),
        )
    if all_devices:
        if not devices:
            raise DeviceSelectionError("no connected Android devices were detected by `adb devices -l`")
        return tuple(device.serial for device in devices)
    return (
        resolve_device_serial(
            None,
            multiple_devices_hint=multiple_devices_hint,
            adb_executable=adb_executable,
            env=env,
            cwd=cwd,
        ),
    )


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def derive_remote_host(serial: str) -> str:
    start = REMOTE_PORT_BASE + (zlib.crc32(serial.encode("utf-8")) % REMOTE_PORT_COUNT)
    for offset in range(REMOTE_PORT_COUNT):
        candidate = REMOTE_PORT_BASE + ((start - REMOTE_PORT_BASE + offset) % REMOTE_PORT_COUNT)
        if _port_is_available(REMOTE_HOST_ADDRESS, candidate):
            return f"{REMOTE_HOST_ADDRESS}:{candidate}"
    raise DeviceSelectionError(
        f"failed to reserve a local remote host port for `{serial}` in "
        f"{REMOTE_HOST_ADDRESS}:{REMOTE_PORT_BASE}-{REMOTE_HOST_ADDRESS}:{REMOTE_PORT_BASE + REMOTE_PORT_COUNT - 1}"
    )


class DeviceTestLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: object | None = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a+", encoding="utf-8")
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX only
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX only
            pass
        else:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None
