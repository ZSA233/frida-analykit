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
    _activate_path,
    _env_root_for_python,
    _python_path,
)

from tests.support.paths import REPO_ROOT

from .support import _write_file


def test_install_frida_requires_virtualenv(tmp_path: Path) -> None:
    manager = EnvManager.for_global()

    with pytest.raises(EnvError, match="not inside a virtual environment"):
        manager.install_frida(tmp_path / "python", "16.5.9")
def test_install_frida_updates_managed_env_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-17.8.2"
    env_dir.mkdir(parents=True)
    (env_dir / "pyvenv.cfg").write_text("home = /tmp\n", encoding="utf-8")
    python_path = env_dir / "bin" / "python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("", encoding="utf-8")

    calls: list[list[str]] = []

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = EnvManager.for_repo(tmp_path, subprocess_run=_run)
    monkeypatch.setattr(manager._registry_store, "detect_installed_frida_analykit_version", lambda _: __version__)
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(
        json.dumps(
            {
                "current": "frida-17.8.2",
                "envs": [
                    {
                        "name": "frida-17.8.2",
                        "path": str(env_dir),
                        "frida_version": "17.8.2",
                        "frida_analykit_version": __version__,
                        "source_kind": "version",
                        "source_value": "17.8.2",
                        "last_updated": "2026-03-26T00:00:00Z",
                        "legacy": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manager.install_frida(python_path, "16.5.9")

    assert calls == [
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python_path),
            "frida==16.5.9",
            "frida-tools",
        ]
    ]
    registry = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    assert registry["envs"][0]["frida_version"] == "16.5.9"
    assert registry["envs"][0]["frida_analykit_version"] == __version__
