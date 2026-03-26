from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from frida_analykit.dev_env import (
    DevEnvError,
    DevEnvManager,
    ManagedEnv,
    _env_root_for_python,
    _python_path,
    load_profiles,
)


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

    profiles = load_profiles(tmp_path)

    assert profiles["legacy-16"].tested_version == "16.5.9"
    assert profiles["current-17"].tested_version == "17.8.2"


def test_repo_create_invokes_uv_commands_in_order_and_updates_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_file(
        tmp_path / "src/frida_analykit/resources/compat_profiles.json",
        """
        {
          "profiles": [
            {"name": "legacy-16", "tested_version": "16.5.9"}
          ]
        }
        """,
    )
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = DevEnvManager.for_repo(tmp_path, subprocess_run=_run)

    env = manager.create(name="legacy-16", profile="legacy-16")

    env_dir = tmp_path / ".frida-analykit" / "envs" / "legacy-16"
    python_path = env_dir / "bin" / "python"
    assert env.env_dir == env_dir
    assert calls[0][0] == ["uv", "venv", str(env_dir), "--python", "3.11"]
    assert calls[1][0] == ["uv", "sync", "--active", "--extra", "repl", "--dev"]
    assert calls[1][1] == tmp_path
    assert calls[1][2] is not None
    assert calls[1][2]["VIRTUAL_ENV"] == str(env_dir)
    assert calls[1][2]["PATH"].split(":")[0] == str(env_dir / "bin")
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
    assert registry["envs"][0]["source_kind"] == "profile"


def test_repo_create_skips_repl_extra_when_requested(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = DevEnvManager.for_repo(tmp_path, subprocess_run=_run)

    manager.create(name="frida-16.5.9", frida_version="16.5.9", with_repl=False)

    assert calls[1][0] == ["uv", "sync", "--active", "--dev"]


def test_global_create_installs_repl_only_by_default(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = DevEnvManager(storage_root=tmp_path / "global-storage", repo_root=None, subprocess_run=_run)

    env = manager.create(name="frida-16.5.9", frida_version="16.5.9")

    env_dir = manager.env_root / "frida-16.5.9"
    python_path = env_dir / "bin" / "python"
    install_source = Path(__file__).resolve().parents[1]
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

    manager = DevEnvManager(storage_root=tmp_path / "global-storage", repo_root=None, subprocess_run=_run)

    manager.create(name="frida-16.5.9", frida_version="16.5.9", with_repl=False)

    assert calls[1][0][-1] == str(Path(__file__).resolve().parents[1])


def test_list_envs_discovers_legacy_virtualenvs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_file(
        tmp_path / "src/frida_analykit/resources/compat_profiles.json",
        """
        {
          "profiles": [
            {"name": "legacy-16", "tested_version": "16.5.9"}
          ]
        }
        """,
    )
    legacy_env = tmp_path / ".venv-frida-16.5.9"
    legacy_env.mkdir()
    (legacy_env / "pyvenv.cfg").write_text("home = /tmp\n", encoding="utf-8")

    manager = DevEnvManager.for_repo(tmp_path)
    monkeypatch.setattr(manager, "_detect_installed_frida_version", lambda _: "16.5.9")

    envs = manager.list_envs()

    assert len(envs) == 1
    assert envs[0].name == ".venv-frida-16.5.9"
    assert envs[0].legacy is True
    assert envs[0].frida_version == "16.5.9"

    registry = json.loads((tmp_path / ".frida-analykit" / "envs.json").read_text(encoding="utf-8"))
    assert registry["envs"][0]["legacy"] is True


def test_enter_uses_single_env_as_implicit_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = DevEnvManager.for_repo(tmp_path)
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
    monkeypatch.setattr(manager, "_open_shell", lambda env: opened.append(env.name))

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


def test_install_frida_requires_virtualenv(tmp_path: Path) -> None:
    manager = DevEnvManager.for_global()

    with pytest.raises(DevEnvError, match="not inside a virtual environment"):
        manager.install_frida(tmp_path / "python", "16.5.9")


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
    manager = DevEnvManager.for_repo(tmp_path)
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(payload, encoding="utf-8")

    with pytest.raises(DevEnvError, match=message):
        manager.list_envs()


def test_list_envs_repairs_partial_registry_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = DevEnvManager.for_repo(tmp_path)
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
    monkeypatch.setattr(manager, "_detect_installed_frida_version", lambda _: "16.5.9")

    envs = manager.list_envs()

    assert [env.name for env in envs] == ["frida-16.5.9"]
    assert envs[0].frida_version == "16.5.9"
    assert envs[0].source_kind == "version"
    assert envs[0].source_value == "16.5.9"
    assert envs[0].legacy is False

    payload = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    assert payload["current"] is None
    assert len(payload["envs"]) == 1
    assert payload["envs"][0]["legacy"] is False
    assert payload["envs"][0]["last_updated"]


def test_render_list_does_not_rewrite_registry_when_payload_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = DevEnvManager.for_repo(tmp_path)
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    registry = {
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
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    manager.registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        manager,
        "_save_registry",
        lambda payload: (_ for _ in ()).throw(AssertionError(f"unexpected write: {payload}")),
    )

    output = manager.render_list()

    assert "frida-16.5.9" in output


def test_save_registry_keeps_previous_contents_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = DevEnvManager.for_repo(tmp_path)
    manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
    old_text = json.dumps({"current": None, "envs": []}, indent=2, sort_keys=True) + "\n"
    manager.registry_path.write_text(old_text, encoding="utf-8")

    def _fail_replace(source: Path, destination: Path) -> None:
        raise OSError("boom")

    monkeypatch.setattr("frida_analykit.dev_env.os.replace", _fail_replace)

    with pytest.raises(DevEnvError, match="Failed to write registry"):
        manager._save_registry({"current": "frida-16.5.9", "envs": []})

    assert manager.registry_path.read_text(encoding="utf-8") == old_text
    assert list(manager.registry_path.parent.glob(".envs.json.*.tmp")) == []


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

    manager = DevEnvManager.for_repo(tmp_path, subprocess_run=_run)
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


def test_create_refuses_to_recreate_symlinked_env_dir(tmp_path: Path) -> None:
    manager = DevEnvManager.for_repo(tmp_path)
    target_dir = tmp_path / "outside"
    target_dir.mkdir()
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        env_dir.symlink_to(target_dir, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable in this environment")

    with pytest.raises(DevEnvError, match="managed env path is a symlink"):
        manager.create(name="frida-16.5.9", frida_version="16.5.9")


def test_remove_deletes_current_managed_env_and_clears_current(tmp_path: Path) -> None:
    manager = DevEnvManager.for_repo(tmp_path)
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
    manager = DevEnvManager.for_repo(tmp_path)
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

    with pytest.raises(DevEnvError, match="legacy path escapes repository root"):
        manager.remove(".venv-frida-16.5.9")


def test_open_shell_uses_zsh_wrapper_that_reactivates_after_user_rc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    activate_path = env_dir / "bin" / "activate"
    activate_path.parent.mkdir(parents=True, exist_ok=True)
    activate_path.write_text("", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    original_zshrc = home / ".zshrc"
    original_zshrc.write_text("export PATH=/shim:$PATH\n", encoding="utf-8")
    manager = DevEnvManager.for_repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str] | None, str, str]] = []

    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("HOME", str(home))

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        assert env is not None
        zdotdir = Path(env["ZDOTDIR"])
        calls.append(
            (
                command,
                env,
                (zdotdir / ".zshenv").read_text(encoding="utf-8"),
                (zdotdir / ".zshrc").read_text(encoding="utf-8"),
            )
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    manager._subprocess_run = _run
    managed_env = ManagedEnv(
        name="frida-16.5.9",
        path=str(env_dir),
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    manager._open_shell(managed_env)

    assert calls[0][0] == ["/bin/zsh", "-i"]
    assert ". " + str(original_zshrc) in calls[0][3]
    assert ". " + str(activate_path) in calls[0][3]
    assert calls[0][1]["VIRTUAL_ENV"] == str(env_dir)
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_NAME"] == "frida-16.5.9"
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_DIR"] == str(env_dir)
    assert calls[0][1]["UV_PROJECT"] == str(tmp_path)


def test_open_shell_fallback_exports_virtualenv_for_generic_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_dir = tmp_path / ".frida-analykit" / "envs" / "frida-16.5.9"
    env_dir.mkdir(parents=True)
    (env_dir / "bin").mkdir(parents=True, exist_ok=True)
    manager = DevEnvManager.for_repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    monkeypatch.setenv("SHELL", "/bin/sh")

    def _run(command, cwd=None, env=None, check=False, capture_output=False, text=False):
        calls.append((command, env))
        return subprocess.CompletedProcess(command, 0, "", "")

    manager._subprocess_run = _run
    managed_env = ManagedEnv(
        name="frida-16.5.9",
        path=str(env_dir),
        frida_version="16.5.9",
        source_kind="version",
        source_value="16.5.9",
        last_updated="2026-03-26T00:00:00Z",
    )

    manager._open_shell(managed_env)

    assert calls[0][0] == ["/bin/sh", "-i"]
    assert calls[0][1] is not None
    assert calls[0][1]["VIRTUAL_ENV"] == str(env_dir)
    assert calls[0][1]["PATH"].split(":")[0] == str(env_dir / "bin")
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_NAME"] == "frida-16.5.9"
    assert calls[0][1]["FRIDA_ANALYKIT_ENV_DIR"] == str(env_dir)
    assert calls[0][1]["UV_PROJECT"] == str(tmp_path)
