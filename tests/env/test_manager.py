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


def test_repo_create_invokes_uv_commands_in_order_and_updates_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_file(
        tmp_path / "src/frida_analykit/resources/compat_profiles.json",
        """
        {
          "profiles": [
            {"name": "legacy-16", "series": "16.x", "tested_version": "16.5.9", "min_inclusive": "16.5.0", "max_exclusive": "17.0.0"}
          ]
        }
        """,
    )
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = EnvManager.for_repo(tmp_path, subprocess_run=_run)

    env = manager.create(name="legacy-16", profile="legacy-16")

    env_dir = tmp_path / ".frida-analykit" / "envs" / "legacy-16"
    python_path = _python_path(env_dir)
    assert env.env_dir == env_dir
    assert calls[0][0] == ["uv", "venv", str(env_dir), "--python", "3.11"]
    assert calls[1][0] == ["uv", "sync", "--active", "--extra", "repl", "--dev"]
    assert calls[1][1] == tmp_path
    assert calls[1][2] is not None
    assert calls[1][2]["VIRTUAL_ENV"] == str(env_dir)
    assert calls[1][2]["PATH"].split(os.pathsep)[0] == str(python_path.parent)
    assert calls[2][0] == [
        "uv",
        "pip",
        "install",
        "--python",
        str(python_path),
        "frida==16.5.9",
        "frida-tools",
    ]

    registry = json.loads((tmp_path / ".frida-analykit" / "envs.json").read_text(encoding="utf-8"))
    assert registry["current"] == "legacy-16"
    assert registry["envs"][0]["name"] == "legacy-16"
    assert registry["envs"][0]["frida_version"] == "16.5.9"
    assert registry["envs"][0]["frida_analykit_version"] == __version__
    assert registry["envs"][0]["source_kind"] == "profile"


def test_repo_create_skips_repl_extra_when_requested(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = EnvManager.for_repo(tmp_path, subprocess_run=_run)

    manager.create(name="frida-16.5.9", frida_version="16.5.9", with_repl=False)

    assert calls[1][0] == ["uv", "sync", "--active", "--dev"]


def test_global_create_installs_repl_only_by_default(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = EnvManager(storage_root=tmp_path / "global-storage", repo_root=None, subprocess_run=_run)

    env = manager.create(name="frida-16.5.9", frida_version="16.5.9")

    env_dir = manager.env_root / "frida-16.5.9"
    python_path = _python_path(env_dir)
    install_source = REPO_ROOT
    assert env.env_dir == env_dir
    assert calls[1][0] == [
        "uv",
        "pip",
        "install",
        "--python",
        str(python_path),
        "--editable",
        f"{install_source}[repl]",
    ]
    assert calls[2][0] == [
        "uv",
        "pip",
        "install",
        "--python",
        str(python_path),
        "frida==16.5.9",
        "frida-tools",
    ]


def test_global_create_can_skip_repl_extra(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = EnvManager(storage_root=tmp_path / "global-storage", repo_root=None, subprocess_run=_run)

    manager.create(name="frida-16.5.9", frida_version="16.5.9", with_repl=False)

    assert calls[1][0][-1] == str(REPO_ROOT)


def test_create_streams_uv_progress_output(tmp_path: Path) -> None:
    calls: list[tuple[list[str], bool]] = []

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, capture_output))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = EnvManager.for_repo(tmp_path, subprocess_run=_run)

    manager.create(name="frida-16.5.9", frida_version="16.5.9")

    assert calls == [
        (["uv", "venv", str(tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"), "--python", "3.11"], False),
        (["uv", "sync", "--active", "--extra", "repl", "--dev"], False),
        (
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(_python_path(tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9")),
                "frida==16.5.9",
                "frida-tools",
            ],
            False,
        ),
    ]


def test_create_reports_missing_uv_with_install_guidance(tmp_path: Path) -> None:
    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        raise FileNotFoundError(command[0])

    manager = EnvManager.for_repo(tmp_path, subprocess_run=_run)

    with pytest.raises(EnvError, match="require `uv`"):
        manager.create(name="frida-16.5.9", frida_version="16.5.9")


def test_list_envs_discovers_legacy_virtualenvs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_file(
        tmp_path / "src/frida_analykit/resources/compat_profiles.json",
        """
        {
          "profiles": [
            {"name": "legacy-16", "series": "16.x", "tested_version": "16.5.9", "min_inclusive": "16.5.0", "max_exclusive": "17.0.0"}
          ]
        }
        """,
    )
    legacy_env = tmp_path / ".venv-frida-16.5.9"
    legacy_env.mkdir()
    (legacy_env / "pyvenv.cfg").write_text("home = /tmp\n", encoding="utf-8")

    manager = EnvManager.for_repo(tmp_path)
    monkeypatch.setattr(manager._registry_store, "detect_installed_frida_version", lambda _: "16.5.9")

    envs = manager.list_envs()

    assert len(envs) == 1
    assert envs[0].name == ".venv-frida-16.5.9"
    assert envs[0].legacy is True
    assert envs[0].frida_version == "16.5.9"

    registry = json.loads((tmp_path / ".frida-analykit" / "envs.json").read_text(encoding="utf-8"))
    assert registry["envs"][0]["legacy"] is True


def test_enter_uses_single_env_as_implicit_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = EnvManager.for_repo(tmp_path)
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    registry = {
        "current": None,
        "envs": [
            {
                "name": "frida-16.5.9",
                "path": str(env_dir),
                "frida_version": "16.5.9",
                "source_kind": "version",
                "source_value": "16.5.9",
                "last_updated": "2026-03-26T00:00:00Z",
                "legacy": False,
            }
        ],
    }
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(json.dumps(registry), encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr(manager._shell_launcher, "open_shell", lambda env: opened.append(env.name))

    manager.enter()

    assert opened == ["frida-16.5.9"]
    payload = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    assert payload["current"] == "frida-16.5.9"


def test_env_root_for_python_keeps_symlinked_virtualenv_python(tmp_path: Path) -> None:
    env_dir = tmp_path / "venv"
    env_dir.mkdir()
    (env_dir / "pyvenv.cfg").write_text("home = /tmp\n", encoding="utf-8")
    python_path = _python_path(env_dir)
    python_path.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "python-base" / "python"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")

    try:
        python_path.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable in this environment")

    assert _env_root_for_python(python_path) == env_dir


def test_create_refuses_to_recreate_symlinked_env_dir(tmp_path: Path) -> None:
    manager = EnvManager.for_repo(tmp_path)
    target_dir = tmp_path / "outside"
    target_dir.mkdir()
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        env_dir.symlink_to(target_dir, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable in this environment")

    with pytest.raises(EnvError, match="managed env path is a symlink"):
        manager.create(name="frida-16.5.9", frida_version="16.5.9")


def test_remove_deletes_current_managed_env_and_clears_current(tmp_path: Path) -> None:
    manager = EnvManager.for_repo(tmp_path)
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(
        json.dumps(
            {
                "current": "frida-16.5.9",
                "envs": [
                    {
                        "name": "frida-16.5.9",
                        "path": str(env_dir),
                        "frida_version": "16.5.9",
                        "source_kind": "version",
                        "source_value": "16.5.9",
                        "last_updated": "2026-03-26T00:00:00Z",
                        "legacy": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    removed = manager.remove("frida-16.5.9")

    assert removed.name == "frida-16.5.9"
    assert not env_dir.exists()
    payload = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    assert payload["current"] is None
    assert payload["envs"] == []


def test_remove_legacy_env_requires_repo_local_path(tmp_path: Path) -> None:
    manager = EnvManager.for_repo(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-env"
    outside.mkdir()
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(
        json.dumps(
            {
                "current": None,
                "envs": [
                    {
                        "name": ".venv-frida-16.5.9",
                        "path": str(outside),
                        "frida_version": "16.5.9",
                        "source_kind": "version",
                        "source_value": "16.5.9",
                        "last_updated": "2026-03-26T00:00:00Z",
                        "legacy": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EnvError, match="legacy path escapes repository root"):
        manager.remove(".venv-frida-16.5.9")
