from __future__ import annotations

import re
from pathlib import Path

COMPAT_PROFILES_PATH = Path("src/frida_analykit/resources/compat_profiles.json")
_ENV_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LEGACY_ENV_GLOB = ".venv-*"
_DEFAULT_PYTHON_VERSION = "3.11"
_FRIDA_TOOLS_REQUIREMENT = "frida-tools"
_REPL_EXTRA = "repl"
_UV_REQUIRED_MESSAGE = (
    "Managed environment commands require `uv`, but it was not found on PATH. "
    "Install `uv`, ensure the `uv` command is available, then retry."
)
