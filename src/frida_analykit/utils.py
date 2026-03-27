from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import shutil


def ensure_filepath(filepath: str | Path) -> Path:
    path = Path(filepath).expanduser().resolve()
    if path.exists() and path.is_file():
        timestamp = datetime.fromtimestamp(path.stat().st_mtime)
        archived = path.parent / f"{timestamp.strftime('%Y%m%d%H%M%S%f')}_{path.name}"
        shutil.copyfile(path, archived)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def ensure_filepath_open(
    file: str | Path,
    mode: str,
    buffering: int = -1,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
    closefd: bool = True,
    opener: Any | None = None,
) -> Iterator[Any]:
    path = ensure_filepath(file)
    with open(path, mode, buffering, encoding, errors, newline, closefd, opener) as handle:
        yield handle
