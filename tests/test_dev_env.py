from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "dev_env.py"
SPEC = importlib.util.spec_from_file_location("dev_env", MODULE_PATH)
dev_env = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = dev_env
SPEC.loader.exec_module(dev_env)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_load_profiles_reads_compat_data(tmp_path: Path) -> None:
    _write_file(
        tmp_path / "src/frida_analykit/resources/compat_profiles.json",
        """
        {
          "profiles": [
            {"name": "legacy-16", "tested_version": "16.5.9"},
            {"name": "current-17", "tested_version": "17.8.2"}
          ]
        }
        """,
    )

    profiles = dev_env.load_profiles(tmp_path)

    assert profiles["legacy-16"].tested_version == "16.5.9"
    assert profiles["current-17"].tested_version == "17.8.2"


def test_prepare_environment_invokes_uv_commands_in_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def _run(command, cwd, check, capture_output, text):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dev_env.subprocess, "run", _run)

    payload = dev_env.prepare_environment(
        tmp_path,
        env_name=".venv-legacy16",
        frida_version="16.5.9",
    )

    python_path = str(tmp_path / ".venv-legacy16" / "bin" / "python")
    assert payload["python"] == python_path
    assert calls == [
        ["uv", "venv", str(tmp_path / ".venv-legacy16"), "--python", "3.11"],
        ["uv", "sync", "--extra", "repl", "--dev", "--python", python_path],
        ["uv", "pip", "install", "--python", python_path, "frida==16.5.9"],
    ]
