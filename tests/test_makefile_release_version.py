from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MAKE_BIN = shutil.which("make") or "/Applications/Xcode.app/Contents/Developer/usr/bin/make"


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_version_show_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "release-version-show"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "scripts/release_version.py show" in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_version_rc_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "release-version-rc", "BASE_VERSION=2.0.0", "RC=1"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert 'scripts/release_version.py set-rc --base "2.0.0" --rc "1"' in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_version_rc_check_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "release-version-rc", "BASE_VERSION=2.0.0", "RC=1", "CHECK=1"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert 'scripts/release_version.py set-rc --base "2.0.0" --rc "1" --check' in result.stdout
    assert "release-preflight" not in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_version_stable_dispatch_with_check_and_rc_tag() -> None:
    result = subprocess.run(
        [
            MAKE_BIN,
            "-n",
            "release-version-stable",
            "BASE_VERSION=2.0.0",
            "CHECK=1",
            "RC_TAG=v2.0.0-rc.1",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert 'scripts/release_version.py set-stable --base "2.0.0" --check --rc-tag "v2.0.0-rc.1"' in result.stdout
    assert "release-preflight" not in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_version_rc_requires_variables() -> None:
    result = subprocess.run(
        [MAKE_BIN, "release-version-rc"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Usage: make release-version-rc BASE_VERSION=<version> RC=<number> [CHECK=1]" in result.stderr


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_version_stable_requires_base_version() -> None:
    result = subprocess.run(
        [MAKE_BIN, "release-version-stable"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "Usage: make release-version-stable BASE_VERSION=<version> [CHECK=1] [RC_TAG=<tag>]"
        in result.stderr
    )
