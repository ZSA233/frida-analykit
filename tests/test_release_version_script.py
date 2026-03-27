from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "release_version.py"
SPEC = importlib.util.spec_from_file_location("release_version_script", MODULE_PATH)
release_version_script = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = release_version_script
SPEC.loader.exec_module(release_version_script)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _managed_file_texts(repo_root: Path) -> dict[Path, str | None]:
    return {
        relative_path: (
            (repo_root / relative_path).read_text(encoding="utf-8")
            if (repo_root / relative_path).exists()
            else None
        )
        for relative_path in release_version_script.MANAGED_VERSION_PATHS
    }


def _write_lockfile(repo_root: Path, release) -> None:
    _write_json(
        repo_root / release_version_script.PACKAGE_LOCK_PATH,
        {
            "name": "frida-analykit-monorepo",
            "version": release.npm_version,
            "lockfileVersion": 3,
            "requires": True,
            "packages": {
                "": {
                    "name": "frida-analykit-monorepo",
                    "version": release.npm_version,
                    "dependencies": {
                        release_version_script.AGENT_PACKAGE_NAME: release.agent_package_spec,
                    },
                },
                "packages/frida-analykit-agent": {
                    "name": release_version_script.AGENT_PACKAGE_NAME,
                    "version": release.npm_version,
                },
            },
        },
    )


def _make_version_repo(
    tmp_path: Path,
    *,
    config: release_version_script.ReleaseVersionConfig,
    file_release: object | None = None,
) -> Path:
    repo_root = tmp_path / "repo"
    release = file_release or config.release

    _write_file(
        repo_root / release_version_script.RELEASE_VERSION_PATH,
        release_version_script.render_release_version_config(config),
    )
    _write_file(
        repo_root / release_version_script.VERSION_FILE_PATH,
        f'__version__ = "{release.python_version}"\n',
    )
    _write_json(
        repo_root / release_version_script.ROOT_PACKAGE_JSON_PATH,
        {
            "name": "frida-analykit-monorepo",
            "version": release.npm_version,
            "private": True,
            "workspaces": ["packages/*"],
            "dependencies": {
                release_version_script.AGENT_PACKAGE_NAME: release.agent_package_spec,
            },
        },
    )
    _write_json(
        repo_root / release_version_script.AGENT_PACKAGE_JSON_PATH,
        {
            "name": release_version_script.AGENT_PACKAGE_NAME,
            "version": release.npm_version,
        },
    )
    _write_json(
        repo_root / release_version_script.PACKAGE_LOCK_PATH,
        {
            "name": "frida-analykit-monorepo",
            "version": release.npm_version,
            "lockfileVersion": 3,
            "requires": True,
            "packages": {
                "": {
                    "name": "frida-analykit-monorepo",
                    "version": release.npm_version,
                    "dependencies": {
                        release_version_script.AGENT_PACKAGE_NAME: release.agent_package_spec,
                    },
                },
                "packages/frida-analykit-agent": {
                    "name": release_version_script.AGENT_PACKAGE_NAME,
                    "version": release.npm_version,
                },
            },
        },
    )
    return repo_root


def test_load_release_version_config_supports_stable_and_rc(tmp_path: Path) -> None:
    stable_repo = tmp_path / "stable"
    _write_file(
        stable_repo / release_version_script.RELEASE_VERSION_PATH,
        """
        base_version = "2.0.0"
        channel = "stable"
        """,
    )

    stable = release_version_script.load_release_version_config(stable_repo)
    assert stable.release.python_version == "2.0.0"
    assert stable.release.npm_version == "2.0.0"
    assert stable.release.tag == "v2.0.0"

    rc_repo = tmp_path / "rc"
    _write_file(
        rc_repo / release_version_script.RELEASE_VERSION_PATH,
        """
        base_version = "2.0.0"
        channel = "rc"
        rc_number = 2
        """,
    )

    rc = release_version_script.load_release_version_config(rc_repo)
    assert rc.release.python_version == "2.0.0rc2"
    assert rc.release.npm_version == "2.0.0-rc.2"
    assert rc.release.tag == "v2.0.0-rc.2"


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        (
            """
            base_version = "2.0.0rc1"
            channel = "stable"
            """,
            "base_version must not include an rc suffix",
        ),
        (
            """
            base_version = "2.0.0"
            channel = "beta"
            """,
            "channel must be 'stable' or 'rc'",
        ),
        (
            """
            base_version = "2.0.0"
            channel = "stable"
            rc_number = 1
            """,
            "rc_number is only allowed when channel = 'rc'",
        ),
        (
            """
            base_version = "2.0.0"
            channel = "rc"
            """,
            "rc_number is required when channel = 'rc'",
        ),
    ],
)
def test_load_release_version_config_validates_fields(
    tmp_path: Path,
    content: str,
    expected_message: str,
) -> None:
    repo_root = tmp_path / "repo"
    _write_file(repo_root / release_version_script.RELEASE_VERSION_PATH, content)

    with pytest.raises(release_version_script.ReleaseVersionToolError, match=expected_message):
        release_version_script.load_release_version_config(repo_root)


def test_sync_release_version_updates_files_and_runs_lockfile_regeneration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = release_version_script.ReleaseVersionConfig(
        base_version="2.0.0",
        channel="rc",
        rc_number=1,
    )
    old_release = release_version_script.ReleaseVersion(base_version="1.9.0")
    repo_root = _make_version_repo(tmp_path, config=config, file_release=old_release)
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command, cwd=None, check=False, capture_output=False, text=False):
        calls.append((list(command), cwd))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(release_version_script.subprocess, "run", fake_run)

    payload = release_version_script.sync_release_version(repo_root, config)

    assert payload["tag"] == "v2.0.0-rc.1"
    assert (
        (repo_root / release_version_script.VERSION_FILE_PATH).read_text(encoding="utf-8").strip()
        == '__version__ = "2.0.0rc1"'
    )
    root_package = json.loads(
        (repo_root / release_version_script.ROOT_PACKAGE_JSON_PATH).read_text(encoding="utf-8")
    )
    assert root_package["version"] == "2.0.0-rc.1"
    assert root_package["dependencies"][release_version_script.AGENT_PACKAGE_NAME] == "^2.0.0-rc.1"
    agent_package = json.loads(
        (repo_root / release_version_script.AGENT_PACKAGE_JSON_PATH).read_text(encoding="utf-8")
    )
    assert agent_package["version"] == "2.0.0-rc.1"
    assert calls == [
        (["npm", "install", "--package-lock-only", "--ignore-scripts"], repo_root),
    ]


def test_sync_release_version_rolls_back_when_lockfile_regeneration_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = release_version_script.ReleaseVersionConfig(base_version="2.0.0", channel="stable")
    target_config = release_version_script.ReleaseVersionConfig(
        base_version="2.0.0",
        channel="rc",
        rc_number=1,
    )
    repo_root = _make_version_repo(tmp_path, config=original_config)
    before = _managed_file_texts(repo_root)

    def fake_run_lockfile_sync(current_repo_root: Path) -> None:
        _write_lockfile(current_repo_root, target_config.release)
        raise release_version_script.ReleaseVersionToolError(
            "Failed to regenerate package-lock.json: npm failed"
        )

    monkeypatch.setattr(release_version_script, "run_lockfile_sync", fake_run_lockfile_sync)

    with pytest.raises(
        release_version_script.ReleaseVersionToolError,
        match=re.escape("Failed to regenerate package-lock.json: npm failed"),
    ):
        release_version_script.sync_release_version(repo_root, target_config)

    assert _managed_file_texts(repo_root) == before


def test_set_rc_release_with_check_runs_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = release_version_script.ReleaseVersionConfig(base_version="2.0.0", channel="stable")
    repo_root = _make_version_repo(tmp_path, config=original_config)
    calls: list[tuple[str, str | None]] = []

    def fake_run_lockfile_sync(current_repo_root: Path) -> None:
        _write_lockfile(
            current_repo_root,
            release_version_script.ReleaseVersion(base_version="2.0.0", rc_number=1),
        )

    def fake_run_release_preflight(current_repo_root: Path, *, tag: str, rc_tag: str | None = None) -> None:
        calls.append((tag, rc_tag))

    monkeypatch.setattr(release_version_script, "run_lockfile_sync", fake_run_lockfile_sync)
    monkeypatch.setattr(release_version_script, "run_release_preflight", fake_run_release_preflight)

    payload = release_version_script.set_rc_release(
        repo_root,
        base_version="2.0.0",
        rc_number=1,
        check=True,
    )

    assert payload["tag"] == "v2.0.0-rc.1"
    assert calls == [("v2.0.0-rc.1", None)]


def test_set_stable_release_with_check_runs_preflight_and_rc_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = release_version_script.ReleaseVersionConfig(
        base_version="2.0.0",
        channel="rc",
        rc_number=1,
    )
    repo_root = _make_version_repo(tmp_path, config=original_config)
    calls: list[tuple[str, str | None]] = []

    def fake_run_lockfile_sync(current_repo_root: Path) -> None:
        _write_lockfile(
            current_repo_root,
            release_version_script.ReleaseVersion(base_version="2.0.0"),
        )

    def fake_run_release_preflight(current_repo_root: Path, *, tag: str, rc_tag: str | None = None) -> None:
        calls.append((tag, rc_tag))

    monkeypatch.setattr(release_version_script, "run_lockfile_sync", fake_run_lockfile_sync)
    monkeypatch.setattr(release_version_script, "run_release_preflight", fake_run_release_preflight)

    payload = release_version_script.set_stable_release(
        repo_root,
        base_version="2.0.0",
        check=True,
        rc_tag="v2.0.0-rc.1",
    )

    assert payload["tag"] == "v2.0.0"
    assert calls == [("v2.0.0", "v2.0.0-rc.1")]


def test_set_stable_release_with_check_rolls_back_when_preflight_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = release_version_script.ReleaseVersionConfig(
        base_version="2.0.0",
        channel="rc",
        rc_number=1,
    )
    repo_root = _make_version_repo(tmp_path, config=original_config)
    before = _managed_file_texts(repo_root)

    def fake_run_lockfile_sync(current_repo_root: Path) -> None:
        _write_lockfile(
            current_repo_root,
            release_version_script.ReleaseVersion(base_version="2.0.0"),
        )

    def fake_run_release_preflight(current_repo_root: Path, *, tag: str, rc_tag: str | None = None) -> None:
        raise release_version_script.ReleaseVersionToolError(
            f"Release preflight failed for {tag}: tests failed"
        )

    monkeypatch.setattr(release_version_script, "run_lockfile_sync", fake_run_lockfile_sync)
    monkeypatch.setattr(release_version_script, "run_release_preflight", fake_run_release_preflight)

    with pytest.raises(
        release_version_script.ReleaseVersionToolError,
        match=re.escape("Release preflight failed for v2.0.0: tests failed"),
    ):
        release_version_script.set_stable_release(
            repo_root,
            base_version="2.0.0",
            check=True,
            rc_tag="v2.0.0-rc.1",
        )

    assert _managed_file_texts(repo_root) == before


@pytest.mark.parametrize(
    ("tag", "mutator", "expected_message"),
    [
        (
            "v2.0.0",
            lambda repo_root: None,
            "release-version.toml expects tag v2.0.0-rc.1, found v2.0.0",
        ),
        (
            "v2.0.0-rc.1",
            lambda repo_root: (
                repo_root / release_version_script.VERSION_FILE_PATH
            ).write_text('__version__ = "2.0.0"\n', encoding="utf-8"),
            "src/frida_analykit/_version.py must be 2.0.0rc1, found 2.0.0",
        ),
        (
            "v2.0.0-rc.1",
            lambda repo_root: _write_json(
                repo_root / release_version_script.ROOT_PACKAGE_JSON_PATH,
                {
                    **json.loads(
                        (repo_root / release_version_script.ROOT_PACKAGE_JSON_PATH).read_text(
                            encoding="utf-8"
                        )
                    ),
                    "version": "2.0.0",
                },
            ),
            "package.json version must be 2.0.0-rc.1, found 2.0.0",
        ),
        (
            "v2.0.0-rc.1",
            lambda repo_root: _write_json(
                repo_root / release_version_script.AGENT_PACKAGE_JSON_PATH,
                {
                    **json.loads(
                        (repo_root / release_version_script.AGENT_PACKAGE_JSON_PATH).read_text(
                            encoding="utf-8"
                        )
                    ),
                    "version": "2.0.0",
                },
            ),
            "packages/frida-analykit-agent/package.json version must be 2.0.0-rc.1, found 2.0.0",
        ),
        (
            "v2.0.0-rc.1",
            lambda repo_root: _write_json(
                repo_root / release_version_script.ROOT_PACKAGE_JSON_PATH,
                {
                    **json.loads(
                        (repo_root / release_version_script.ROOT_PACKAGE_JSON_PATH).read_text(
                            encoding="utf-8"
                        )
                    ),
                    "dependencies": {
                        release_version_script.AGENT_PACKAGE_NAME: "^2.0.0",
                    },
                },
            ),
            "package.json dependency @zsa233/frida-analykit-agent must be ^2.0.0-rc.1, found ^2.0.0",
        ),
        (
            "v2.0.0-rc.1",
            lambda repo_root: _write_json(
                repo_root / release_version_script.PACKAGE_LOCK_PATH,
                {
                    **json.loads(
                        (repo_root / release_version_script.PACKAGE_LOCK_PATH).read_text(
                            encoding="utf-8"
                        )
                    ),
                    "packages": {
                        **json.loads(
                            (repo_root / release_version_script.PACKAGE_LOCK_PATH).read_text(
                                encoding="utf-8"
                            )
                        )["packages"],
                        "": {
                            **json.loads(
                                (repo_root / release_version_script.PACKAGE_LOCK_PATH).read_text(
                                    encoding="utf-8"
                                )
                            )["packages"][""],
                            "version": "2.0.0",
                        },
                    },
                },
            ),
            "package-lock.json root version must be 2.0.0-rc.1, found 2.0.0",
        ),
    ],
)
def test_check_release_sync_reports_drift(
    tmp_path: Path,
    tag: str,
    mutator,
    expected_message: str,
) -> None:
    config = release_version_script.ReleaseVersionConfig(
        base_version="2.0.0",
        channel="rc",
        rc_number=1,
    )
    repo_root = _make_version_repo(tmp_path, config=config)
    mutator(repo_root)

    with pytest.raises(
        release_version_script.ReleaseVersionToolError,
        match=re.escape(expected_message),
    ):
        release_version_script.check_release_sync(repo_root, tag=tag)


def test_check_release_sync_passes_for_consistent_stable_repo(tmp_path: Path) -> None:
    config = release_version_script.ReleaseVersionConfig(base_version="2.1.0", channel="stable")
    repo_root = _make_version_repo(tmp_path, config=config)

    payload = release_version_script.check_release_sync(repo_root, tag="v2.1.0")

    assert payload["python_version"] == "2.1.0"
    assert payload["npm_version"] == "2.1.0"
    assert payload["tag"] == "v2.1.0"
