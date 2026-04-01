from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from frida_analykit._version import __version__
from frida_analykit.development import load_profiles
from frida_analykit.env import (
    EnvError,
    EnvManager,
    ManagedEnv,
    _env_root_for_python,
    _activate_path,
    _python_path,
)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


