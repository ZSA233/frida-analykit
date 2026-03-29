from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence
from urllib.request import Request

from ..compat import FridaCompat


class ServerSubprocessRun(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]: ...


class _TextStream(Protocol):
    def read(self, size: int = -1) -> str: ...


class PopenProcess(Protocol):
    stdout: _TextStream | None
    stderr: _TextStream | None

    def wait(self, timeout: float | None = None) -> int: ...

    def communicate(self, timeout: float | None = None) -> tuple[str | None, str | None]: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class ServerSubprocessPopen(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        stdout: int | None = None,
        stderr: int | None = None,
        text: bool = False,
    ) -> PopenProcess: ...


class ResponseHeaders(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None: ...


class UrlOpenResponse(Protocol):
    headers: ResponseHeaders | None

    def __enter__(self) -> "UrlOpenResponse": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def read(self, size: int = -1) -> bytes: ...


class UrlOpenFunc(Protocol):
    def __call__(self, request: Request) -> UrlOpenResponse: ...


@dataclass(slots=True)
class ServerRuntime:
    compat: FridaCompat
    urlopen_func: UrlOpenFunc
    subprocess_run: ServerSubprocessRun
    subprocess_popen: ServerSubprocessPopen
    cache_dir: Path
    adb_executable: str
