from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from tests.support.paths import REPO_ROOT

import pytest


MAKE_BIN = shutil.which("make") or "/Applications/Xcode.app/Contents/Developer/usr/bin/make"
_MAKE_ENV_KEYS_TO_CLEAR = (
    "MAKEFLAGS",
    "MAKELEVEL",
    "MFLAGS",
    "MAKEOVERRIDES",
    "GNUMAKEFLAGS",
    "CI_REF",
    "BASE_VERSION",
    "RC",
    "CHECK",
    "RC_TAG",
    "RELEASE_TAG",
)


def _make_test_env() -> dict[str, str]:
    env = os.environ.copy()
    # These tests invoke nested `make` commands. If we inherit MAKEFLAGS or
    # release variables from an outer `make release-version-* CHECK=1`, the
    # inner call can accidentally rerun the real release flow instead of
    # exercising the expected usage/error branch.
    for key in _MAKE_ENV_KEYS_TO_CLEAR:
        env.pop(key, None)
    return env


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_version_show_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "release-version-show"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_make_test_env(),
    )

    assert result.returncode == 0, result.stderr
    assert "scripts/release_version.py show" in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_preflight_uses_fail_fast_verbose_pytest() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "release-preflight", "RELEASE_TAG=v2.0.0-rc.1"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_make_test_env(),
    )

    assert result.returncode == 0, result.stderr
    assert 'pytest -x -vv -m "not smoke and not scaffold and not device"' in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_ci_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "release-ci", "CI_REF=release/v2.0.8"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_make_test_env(),
    )

    assert result.returncode == 0, result.stderr
    assert 'scripts/release_ci.py --ref "release/v2.0.8"' in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_preflight_skips_promotion_without_rc_tag_for_stable() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "release-preflight", "RELEASE_TAG=v2.0.0"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_make_test_env(),
    )

    assert result.returncode == 0, result.stderr
    assert "validate-release-version --tag \"v2.0.0\"" in result.stdout
    assert "validate-promotion" not in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_preflight_runs_promotion_when_rc_tag_is_supplied() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "release-preflight", "RELEASE_TAG=v2.0.0", "RC_TAG=v2.0.0-rc.1"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_make_test_env(),
    )

    assert result.returncode == 0, result.stderr
    assert 'validate-promotion --tag "v2.0.0" --rc-tag "v2.0.0-rc.1"' in result.stdout


@pytest.mark.skipif(not Path(MAKE_BIN).exists(), reason="make is not available")
def test_make_release_version_rc_dispatch() -> None:
    result = subprocess.run(
        [MAKE_BIN, "-n", "release-version-rc", "BASE_VERSION=2.0.0", "RC=1"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_make_test_env(),
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
        env=_make_test_env(),
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
        env=_make_test_env(),
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
        env=_make_test_env(),
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
        env=_make_test_env(),
    )

    assert result.returncode != 0
    assert (
        "Usage: make release-version-stable BASE_VERSION=<version> [CHECK=1] [RC_TAG=<tag>]"
        in result.stderr
    )
