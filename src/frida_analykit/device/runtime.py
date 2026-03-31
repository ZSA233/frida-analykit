from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .defaults import DEVICE_RUNTIME_BOOT_MAX_ATTEMPTS, TRANSIENT_DEVICE_FAILURE_MARKERS

if TYPE_CHECKING:
    from .helpers import DeviceHelpers


def is_transient_device_failure(detail: str) -> bool:
    lowered = detail.strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in TRANSIENT_DEVICE_FAILURE_MARKERS)


def should_retry_device_operation(
    helper: "DeviceHelpers",
    *,
    stage: str,
    detail: str,
) -> bool:
    if stage == "boot":
        return True
    if is_transient_device_failure(detail):
        return True
    return helper._probe_remote_ready() is not None


class DeviceServerRuntime:
    def __init__(self, helper: "DeviceHelpers") -> None:
        self._helper = helper
        self._process: subprocess.Popen[str] | None = None
        self._config_path: Path | None = None

    def ensure_installed(self, config_path: Path) -> None:
        self._helper.ensure_matching_server(config_path)

    def _ensure_running_once(self, config_path: Path, *, timeout: int = 30) -> None:
        self.ensure_installed(config_path)
        self._config_path = config_path

        if self._process is not None and self._process.poll() is not None:
            self.invalidate()
            self._config_path = config_path

        if self._helper._probe_remote_ready() is None:
            return

        if self._process is not None:
            self.stop(config_path)

        self._process = self._helper.start_boot_process(
            config_path,
            force_restart=True,
            timeout=timeout,
        )

    def ensure_running(
        self,
        config_path: Path,
        *,
        timeout: int = 30,
        max_attempts: int = DEVICE_RUNTIME_BOOT_MAX_ATTEMPTS,
    ) -> None:
        last_error: RuntimeError | None = None
        attempts = max(1, max_attempts)
        for attempt in range(1, attempts + 1):
            try:
                # Older devices can transiently lose the forwarded endpoint or
                # crash the boot child during restart, so give the shared
                # runtime one recovery pass before surfacing a hard failure.
                self._ensure_running_once(config_path, timeout=timeout)
                return
            except RuntimeError as exc:
                last_error = exc

            if attempt >= attempts:
                break
            if last_error is None or not should_retry_device_operation(
                self._helper,
                stage="boot",
                detail=str(last_error),
            ):
                break
            self.invalidate()
            self._helper.wait_for_device_ready(timeout=max(timeout, 60))
            time.sleep(1)

        raise last_error or RuntimeError("failed to boot remote frida-server")

    def stop(self, config_path: Path | None = None) -> None:
        target_config = config_path or self._config_path
        if target_config is None:
            self.invalidate()
            return

        if self._process is not None:
            self._helper.stop_boot_process(self._process, target_config)
        else:
            self._helper.run_cli(["server", "stop", "--config", str(target_config)], timeout=60)
        self._helper.wait_for_device_ready()
        self.invalidate()

    def invalidate(self) -> None:
        self._process = None
        self._config_path = None
