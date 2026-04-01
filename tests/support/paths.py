from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
DEVICE_TESTS_ROOT = REPO_ROOT / "tests" / "device"


def device_conftest_path() -> Path:
    return DEVICE_TESTS_ROOT / "conftest.py"
