from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MAKE_BIN = shutil.which("make") or "/Applications/Xcode.app/Contents/Developer/usr/bin/make"


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_defaults_to_help() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "dev-env"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "scripts/dev_env.py help" in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_list_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "dev-env-list"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "scripts/dev_env.py list" in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_gen_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "dev-env-gen", "FRIDA_VERSION=16.5.9", "ENV_NAME=frida-16.5.9"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "scripts/dev_env.py gen" in result.stdout
    assert "--frida-version \"16.5.9\"" in result.stdout
    assert "--name \"frida-16.5.9\"" in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_gen_dispatch_without_env_name() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "dev-env-gen", "FRIDA_VERSION=16.5.9"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "scripts/dev_env.py gen" in result.stdout
    assert "--frida-version \"16.5.9\"" in result.stdout
    assert "--name" not in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_gen_dispatch_with_no_repl() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "dev-env-gen", "FRIDA_VERSION=16.5.9", "NO_REPL=1"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "scripts/dev_env.py gen" in result.stdout
    assert "--no-repl" in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_enter_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "dev-env-enter", "ENV_NAME=frida-16.5.9"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "scripts/dev_env.py enter" in result.stdout
    assert "--name \"frida-16.5.9\"" in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_remove_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "dev-env-remove", "ENV_NAME=frida-16.5.9"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "scripts/dev_env.py remove" in result.stdout
    assert "--name \"frida-16.5.9\"" in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_gen_requires_explicit_variables() -> None:
    result = subprocess.run(
        [MAKE_BIN, "dev-env-gen"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Usage: make dev-env-gen FRIDA_VERSION=<version> [ENV_NAME=<name>] [NO_REPL=1]" in result.stderr


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_enter_requires_env_name() -> None:
    result = subprocess.run(
        [MAKE_BIN, "dev-env-enter"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Usage: make dev-env-enter ENV_NAME=<name>" in result.stderr


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_dev_env_remove_requires_env_name() -> None:
    result = subprocess.run(
        [MAKE_BIN, "dev-env-remove"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Usage: make dev-env-remove ENV_NAME=<name>" in result.stderr
