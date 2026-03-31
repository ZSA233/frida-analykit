from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from frida_analykit.development import DeviceTestContext
from frida_analykit.device import DeviceAppResolutionError, DeviceHelpers, DeviceServerRuntime, DeviceWorkspace
from frida_analykit.device.models import DeviceSelectionError

DEVICE_APP_ENV = "FRIDA_ANALYKIT_DEVICE_APP"
DEVICE_SKIP_APP_TESTS_ENV = "FRIDA_ANALYKIT_DEVICE_SKIP_APP_TESTS"
DEVICE_APP_MARK = "device_app"


def _is_truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _device_app_tests_skipped() -> bool:
    return _is_truthy_env(os.environ.get(DEVICE_SKIP_APP_TESTS_ENV))


def _require_device_enabled() -> None:
    if os.environ.get("FRIDA_ANALYKIT_ENABLE_DEVICE") != "1":
        pytest.skip("set FRIDA_ANALYKIT_ENABLE_DEVICE=1 to run device tests")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "device_app: requires a launchable Android app package for device tests")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not _device_app_tests_skipped():
        return

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if item.get_closest_marker(DEVICE_APP_MARK) is not None:
            deselected.append(item)
            continue
        selected.append(item)

    if not deselected:
        return

    config.hook.pytest_deselected(items=deselected)
    items[:] = selected


@pytest.fixture(scope="session")
def device_context() -> DeviceTestContext:
    _require_device_enabled()
    repo_root = Path(__file__).resolve().parents[2]
    try:
        context = DeviceTestContext.from_environment(repo_root, os.environ)
    except DeviceSelectionError as exc:
        raise pytest.UsageError(str(exc)) from exc
    try:
        context.ensure_requested_frida_version()
    except DeviceSelectionError as exc:
        pytest.skip(str(exc))
    return context


@pytest.fixture(scope="session")
def device_helpers(device_context: DeviceTestContext) -> DeviceHelpers:
    return device_context.device_helpers


@pytest.fixture(scope="session")
def device_admin_workspace(device_context: DeviceTestContext, tmp_path_factory: pytest.TempPathFactory) -> DeviceWorkspace:
    return device_context.create_admin_workspace(tmp_path_factory.mktemp("device-admin"))


@pytest.fixture(scope="session", autouse=True)
def device_session_guard(
    device_context: DeviceTestContext,
) -> Iterator[None]:
    lock = device_context.create_session_lock()
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


@pytest.fixture(scope="session")
def device_server_runtime(
    device_context: DeviceTestContext,
    device_admin_workspace: DeviceWorkspace,
    device_session_guard,
) -> Iterator[DeviceServerRuntime]:
    runtime = device_context.create_server_runtime()
    try:
        yield runtime
    finally:
        runtime.stop(device_admin_workspace.config_path)


@pytest.fixture
def device_server_ready(
    device_server_runtime: DeviceServerRuntime,
    device_admin_workspace: DeviceWorkspace,
) -> DeviceServerRuntime:
    device_server_runtime.ensure_running(device_admin_workspace.config_path, timeout=60)
    return device_server_runtime


@pytest.fixture(scope="session")
def device_app(
    device_context: DeviceTestContext,
    device_admin_workspace: DeviceWorkspace,
    device_server_runtime: DeviceServerRuntime,
) -> str:
    _require_device_enabled()
    if _device_app_tests_skipped():
        pytest.skip(f"{DEVICE_SKIP_APP_TESTS_ENV}=1 disabled app-backed device tests")

    device_server_runtime.ensure_running(device_admin_workspace.config_path, timeout=60)
    try:
        app, source = device_context.resolve_device_app(
            device_server_runtime,
            device_admin_workspace,
            explicit_app=os.environ.get(DEVICE_APP_ENV),
            timeout=60,
        )
    except DeviceAppResolutionError as exc:
        raise pytest.UsageError(str(exc)) from exc

    print(
        f"[device] selected app `{app}` via {source} "
        f"for serial `{device_context.device_helpers.resolved_serial}` on {device_context.device_helpers.remote_host}"
    )
    return app


@pytest.fixture
def booted_device_workspace(
    device_context: DeviceTestContext,
    device_app: str,
    tmp_path: Path,
    device_server_ready: DeviceServerRuntime,
) -> DeviceWorkspace:
    workspace = device_context.create_workspace(tmp_path, app=device_app)
    return workspace
