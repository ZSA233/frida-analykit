from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sys
from typing import TextIO

import colorama

from .config import AgentConfig
from .utils import ensure_filepath


class LoggerName(str, Enum):
    OUTERR = "outerr"
    STDOUT = "stdout"
    STDERR = "stderr"
    SSL_SECRET = "ssl_secret_log"


class ColorizedStream:
    def __init__(self, stream: TextIO, color: str | None = None) -> None:
        self._stream = stream
        self._color = color

    @property
    def buffer(self):  # pragma: no cover - passthrough
        return getattr(self._stream, "buffer", None)

    def write(self, message: str) -> int:
        if self._color:
            return self._stream.write(f"{self._color}{message}{colorama.Fore.RESET}")
        return self._stream.write(message)

    def flush(self) -> None:
        self._stream.flush()


class FileLogger:
    def __init__(
        self,
        channel: LoggerName | str,
        filepath: str,
        *,
        stream: TextIO | None = None,
        color: str | None = None,
        auto_flush: bool = True,
    ) -> None:
        self.channel = channel.value if isinstance(channel, LoggerName) else str(channel)
        self.filepath = filepath
        self._color = color
        self._auto_flush = auto_flush
        if stream is None:
            ensure_filepath(filepath)
            self._stream = open(filepath, "w", buffering=1, encoding="utf-8")
            self._owns_stream = True
        else:
            self._stream = stream
            self._owns_stream = False

    def write(self, message: str) -> int:
        if self._color:
            written = self._stream.write(f"{self._color}{message}{colorama.Fore.RESET}")
        else:
            written = self._stream.write(message)
        if self._auto_flush:
            self.flush()
        return written

    def flush(self) -> None:
        self._stream.flush()

    def close(self) -> None:
        if self._owns_stream:
            self._stream.close()

    def clone(self, *, color: str | None = None) -> "FileLogger":
        return FileLogger(
            self.channel,
            self.filepath,
            stream=self._stream,
            color=color if color is not None else self._color,
            auto_flush=self._auto_flush,
        )


@dataclass(frozen=True)
class LoggerBundle:
    stdout: TextIO
    stderr: TextIO


def build_loggers(agent: AgentConfig) -> LoggerBundle:
    stdout: TextIO = ColorizedStream(sys.stdout)
    stderr: TextIO = ColorizedStream(sys.stderr, colorama.Fore.RED)

    if agent.stdout and agent.stderr and agent.stdout == agent.stderr:
        shared = FileLogger(LoggerName.OUTERR, str(agent.stdout))
        stdout = shared
        stderr = shared.clone()
    else:
        if agent.stdout:
            stdout = FileLogger(LoggerName.STDOUT, str(agent.stdout))
        if agent.stderr:
            stderr = FileLogger(LoggerName.STDERR, str(agent.stderr))

    return LoggerBundle(stdout=stdout, stderr=stderr)
