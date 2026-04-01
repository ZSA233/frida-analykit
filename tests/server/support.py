import io
import json
import lzma
import shlex
import subprocess
from pathlib import Path

import frida
import pytest

from frida_analykit.compat import FridaCompat
from frida_analykit.config import AppConfig
from frida_analykit.diagnostics import set_verbose
from frida_analykit.server import FridaServerManager, ServerManagerError


class _FakeFrida:
    __version__ = "17.8.2"


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(payload)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _remote_config(tmp_path: Path, *, version: str | None = None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": "_agent.js",
            "server": {
                "host": "127.0.0.1:27042",
                "device": "emulator-5554",
                "servername": "/data/local/tmp/frida-server",
                "version": version,
            },
            "agent": {},
            "script": {"nettools": {}},
        }
    ).resolve_paths(tmp_path, source_path=tmp_path / "config.yml")


def _remote_config_without_device(tmp_path: Path, *, version: str | None = None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": "_agent.js",
            "server": {
                "host": "127.0.0.1:27042",
                "device": None,
                "servername": "/data/local/tmp/frida-server",
                "version": version,
            },
            "agent": {},
            "script": {"nettools": {}},
        }
    ).resolve_paths(tmp_path, source_path=tmp_path / "config.yml")


def _completed(args: list[str], *, stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


def _connected_devices_output(*serials: str) -> str:
    body = "".join(f"{serial} device product:demo model:demo device:demo\n" for serial in serials)
    return f"List of devices attached\n{body}"


def _plain_shell(args: list[str], command: str) -> bool:
    return args[-2:] == ["shell", shlex.join(("sh", "-c", command))]


def _su0_shell(args: list[str], command: str) -> bool:
    return args[-2:] == ["shell", shlex.join(("su", "0", "sh", "-c", command))]


def _suroot_shell(args: list[str], command: str) -> bool:
    return args[-2:] == ["shell", shlex.join(("su", "root", "sh", "-c", command))]


def _suc_shell(args: list[str], command: str) -> bool:
    return args[-2:] == ["shell", shlex.join(("su", "-c", command))]


def _auto_root_shell(args: list[str], command: str) -> bool:
    return any(
        matcher(args, command)
        for matcher in (_plain_shell, _su0_shell, _suroot_shell, _suc_shell)
    )


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        interrupt: bool = False,
        running: bool = True,
    ) -> None:
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._interrupt = interrupt
        self._running = running

    def wait(self, timeout=None):
        if timeout is not None and self._running:
            raise subprocess.TimeoutExpired(cmd="fake-adb-shell", timeout=timeout)
        if self._interrupt and timeout is None:
            raise KeyboardInterrupt
        return self._returncode

    def communicate(self, timeout=None):
        return self._stdout, self._stderr

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


