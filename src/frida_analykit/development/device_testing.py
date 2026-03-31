from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from ..device import (
    DEFAULT_DEVICE_FRIDA_VERSION,
    DeviceHelpers,
    DeviceServerRuntime,
    DeviceTestLock,
    DeviceWorkspace,
    resolve_device_serial,
)
from ..device.models import DeviceSelectionError
from .managed_envs import resolve_managed_python


class DeviceTestContext:
    def __init__(
        self,
        *,
        repo_root: Path,
        env: dict[str, str],
        requested_version: str,
        device_helpers: DeviceHelpers,
    ) -> None:
        self.repo_root = repo_root
        self.env = env
        self.requested_version = requested_version
        self.device_helpers = device_helpers

    @classmethod
    def from_environment(
        cls,
        repo_root: Path,
        environ: Mapping[str, str] | None = None,
        *,
        requested_version: str | None = None,
    ) -> "DeviceTestContext":
        resolved_version = requested_version or os.environ.get(
            "FRIDA_ANALYKIT_DEVICE_FRIDA_VERSION",
            DEFAULT_DEVICE_FRIDA_VERSION,
        )
        env = dict(environ or os.environ)
        src_root = repo_root / "src"
        env["PYTHONPATH"] = f"{src_root}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(src_root)
        env["PYTHONUNBUFFERED"] = "1"
        env["FRIDA_ANALYKIT_DEVICE_FRIDA_VERSION"] = resolved_version

        resolved_serial = resolve_device_serial(
            env.get("ANDROID_SERIAL"),
            env=env,
            cwd=repo_root,
        )
        python_executable = resolve_managed_python(repo_root, env, resolved_version)
        device_helpers = DeviceHelpers(
            repo_root,
            env,
            resolved_serial,
            python_executable=python_executable,
            frida_version=resolved_version,
        )
        return cls(
            repo_root=repo_root,
            env=env,
            requested_version=resolved_version,
            device_helpers=device_helpers,
        )

    def ensure_requested_frida_version(self) -> None:
        actual_version = self.device_helpers.current_frida_version()
        if actual_version != self.requested_version:
            raise DeviceSelectionError(
                f"selected device test python `{self.device_helpers.python_executable}` reports frida=={actual_version}, "
                f"expected {self.requested_version}"
            )

    def create_session_lock(self) -> DeviceTestLock:
        return DeviceTestLock(self.device_helpers.lock_path)

    def create_server_runtime(self) -> DeviceServerRuntime:
        return DeviceServerRuntime(self.device_helpers)

    def create_admin_workspace(self, root: Path) -> DeviceWorkspace:
        return self.device_helpers.create_workspace(root, app=None)

    def create_workspace(self, root: Path, *, app: str | None) -> DeviceWorkspace:
        return self.device_helpers.create_workspace(root, app=app)

    def resolve_device_app(
        self,
        runtime: DeviceServerRuntime,
        admin_workspace: DeviceWorkspace,
        *,
        explicit_app: str | None,
        timeout: int = 60,
    ) -> tuple[str, str]:
        runtime.ensure_running(admin_workspace.config_path, timeout=timeout)
        return self.device_helpers.resolve_device_app(
            explicit_app=explicit_app,
            require_attach=True,
            timeout=timeout,
        )
