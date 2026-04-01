from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from tests.support.paths import device_conftest_path

import pytest


def _load_device_conftest_module():
    conftest_path = device_conftest_path()
    spec = importlib.util.spec_from_file_location("frida_analykit_device_conftest_collection", conftest_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DEVICE_CONFTEST = _load_device_conftest_module()


class _FakeItem:
    def __init__(self, nodeid: str, *, device_app: bool) -> None:
        self.nodeid = nodeid
        self._device_app = device_app

    def get_closest_marker(self, name: str):
        if name == DEVICE_CONFTEST.DEVICE_APP_MARK and self._device_app:
            return object()
        return None


def test_pytest_collection_deselects_device_app_items_when_skip_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DEVICE_CONFTEST.DEVICE_SKIP_APP_TESTS_ENV, "1")
    deselected: list[object] = []
    config = SimpleNamespace(
        hook=SimpleNamespace(pytest_deselected=lambda *, items: deselected.extend(items)),
    )
    items = [
        _FakeItem("tests/device/test_attach_marker.py::test_injection_writes_device_marker", device_app=True),
        _FakeItem("tests/device/test_server_lifecycle.py::test_server_stop_is_idempotent", device_app=False),
    ]

    DEVICE_CONFTEST.pytest_collection_modifyitems(config, items)

    assert [item.nodeid for item in items] == [
        "tests/device/test_server_lifecycle.py::test_server_stop_is_idempotent",
    ]
    assert [item.nodeid for item in deselected] == [
        "tests/device/test_attach_marker.py::test_injection_writes_device_marker",
    ]


def test_pytest_collection_keeps_items_when_skip_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DEVICE_CONFTEST.DEVICE_SKIP_APP_TESTS_ENV, raising=False)
    deselected: list[object] = []
    config = SimpleNamespace(
        hook=SimpleNamespace(pytest_deselected=lambda *, items: deselected.extend(items)),
    )
    items = [
        _FakeItem("tests/device/test_attach_marker.py::test_injection_writes_device_marker", device_app=True),
        _FakeItem("tests/device/test_server_lifecycle.py::test_server_stop_is_idempotent", device_app=False),
    ]

    DEVICE_CONFTEST.pytest_collection_modifyitems(config, items)

    assert [item.nodeid for item in items] == [
        "tests/device/test_attach_marker.py::test_injection_writes_device_marker",
        "tests/device/test_server_lifecycle.py::test_server_stop_is_idempotent",
    ]
    assert deselected == []
