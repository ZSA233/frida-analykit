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


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("[]", "top-level payload must be an object"),
        ('{"current": 1, "envs": []}', "`current` must be a string or null"),
        ('{"current": null, "envs": {}}', "`envs` must be an array"),
        ("{", "Failed to read registry"),
    ],
)
def test_list_envs_rejects_invalid_registry_shape(
    tmp_path: Path,
    payload: str,
    message: str,
) -> None:
    manager = EnvManager.for_repo(tmp_path)
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(payload, encoding="utf-8")

    with pytest.raises(EnvError, match=message):
        manager.list_envs()


def test_list_envs_repairs_partial_registry_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = EnvManager.for_repo(tmp_path)
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    (env_dir / "pyvenv.cfg").write_text("home = /tmp\n", encoding="utf-8")

    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(
        json.dumps(
            {
                "current": "broken",
                "envs": [
                    {
                        "name": "frida-16.5.9",
                        "path": str(env_dir),
                    },
                    {
                        "path": str(env_dir / "missing-name"),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(manager._registry_store, "detect_installed_frida_version", lambda _: "16.5.9")
    monkeypatch.setattr(
        manager._registry_store,
        "detect_installed_frida_analykit_version",
        lambda _: __version__,
    )

    envs = manager.list_envs()

    assert [env.name for env in envs] == ["frida-16.5.9"]
    assert envs[0].frida_version == "16.5.9"
    assert envs[0].frida_analykit_version == __version__
    assert envs[0].source_kind == "version"
    assert envs[0].source_value == "16.5.9"
    assert envs[0].legacy is False

    payload = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    assert payload["current"] is None
    assert len(payload["envs"]) == 1
    assert payload["envs"][0]["legacy"] is False
    assert payload["envs"][0]["last_updated"]
    assert payload["envs"][0]["frida_analykit_version"] == __version__


def test_render_list_does_not_rewrite_registry_when_payload_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = EnvManager.for_repo(tmp_path)
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    registry = {
        "current": "frida-16.5.9",
        "envs": [
            {
                "name": "frida-16.5.9",
                "path": str(env_dir),
                "frida_version": "16.5.9",
                "frida_analykit_version": __version__,
                "source_kind": "version",
                "source_value": "16.5.9",
                "last_updated": "2026-03-26T00:00:00Z",
                "legacy": False,
            }
        ],
    }
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        manager._registry_store,
        "save_registry",
        lambda payload: (_ for _ in ()).throw(AssertionError(f"unexpected write: {payload}")),
    )

    output = manager.render_list()

    assert "frida-16.5.9" in output
    assert __version__ in output


def test_render_list_refreshes_cached_frida_analykit_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = EnvManager.for_repo(tmp_path)
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    registry = {
        "current": "frida-16.5.9",
        "envs": [
            {
                "name": "frida-16.5.9",
                "path": str(env_dir),
                "frida_version": "16.5.9",
                "frida_analykit_version": "1.9.0",
                "source_kind": "version",
                "source_value": "16.5.9",
                "last_updated": "2026-03-26T00:00:00Z",
                "legacy": False,
            }
        ],
    }
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(manager._registry_store, "detect_installed_frida_analykit_version", lambda _: "2.0.1")

    output = manager.render_list()

    assert "2.0.1" in output
    payload = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    assert payload["envs"][0]["frida_analykit_version"] == "2.0.1"


def test_save_registry_keeps_previous_contents_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = EnvManager.for_repo(tmp_path)
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    old_text = json.dumps({"current": None, "envs": []}, indent=2, sort_keys=True) + "\n"
    manager.registry_path.write_text(old_text, encoding="utf-8")

    def _fail_replace(source: Path, destination: Path) -> None:
        raise OSError("boom")

    monkeypatch.setattr("frida_analykit.env.registry.os.replace", _fail_replace)

    with pytest.raises(EnvError, match="Failed to write registry"):
        manager._registry_store.save_registry({"current": "frida-16.5.9", "envs": []})

    assert manager.registry_path.read_text(encoding="utf-8") == old_text
    assert list(manager.registry_path.parent.glob(".envs.json.*.tmp")) == []
