from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence


class DevEnvSubprocessRun(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(slots=True)
class DevEnvRuntime:
    storage_root: Path
    env_root: Path
    registry_path: Path
    repo_root: Path | None
    subprocess_run: DevEnvSubprocessRun
