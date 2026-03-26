from __future__ import annotations

import shlex
import sys
from typing import Iterable

_VERBOSE = False


def set_verbose(enabled: bool) -> None:
    global _VERBOSE
    _VERBOSE = enabled


def is_verbose() -> bool:
    return _VERBOSE


def format_command(command: Iterable[object]) -> str:
    return shlex.join(str(part) for part in command)


def verbose_echo(message: str) -> None:
    if not _VERBOSE:
        return
    print(f"[verbose] {message}", file=sys.stderr, flush=True)
