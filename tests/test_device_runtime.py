from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from frida_analykit.device import DEFAULT_DEVICE_TEST_APP_ID, DeviceServerRuntime


def _load_device_conftest_module():
    conftest_path = Path(__file__).resolve().parent / "device" / "conftest.py"
    spec = importlib.util.spec_from_file_location("frida_analykit_device_conftest", conftest_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DEVICE_CONFTEST = _load_device_conftest_module()


def test_device_server_runtime_ensure_running_reuses_existing_server() -> None:
    calls: list[tuple[str, object]] = []

    class FakeProcess:
        def poll(self):
            return None

    process = FakeProcess()
    probe_results = iter([RuntimeError("down"), None])

    helper = SimpleNamespace(
        ensure_matching_server=lambda config_path: calls.append(("install", config_path)),
        _probe_remote_ready=lambda: next(probe_results),
        start_boot_process=lambda config_path, force_restart=True, timeout=30: calls.append(("boot", config_path)) or process,
        stop_boot_process=lambda proc, config_path: calls.append(("stop", config_path)),
        run_cli=lambda args, timeout=60: calls.append(("cli-stop", tuple(args))),
    )
    runtime = DeviceServerRuntime(helper)
    config_path = Path("/tmp/device-runtime.yml")

    runtime.ensure_running(config_path)
    runtime.ensure_running(config_path)

    assert calls == [
        ("install", config_path),
        ("boot", config_path),
        ("install", config_path),
    ]


def test_device_server_runtime_recovers_after_stop() -> None:
    calls: list[tuple[str, object]] = []

    class FakeProcess:
        def poll(self):
            return None

    first_process = FakeProcess()
    second_process = FakeProcess()
    probe_results = iter([RuntimeError("down"), RuntimeError("down")])
    boot_results = iter([first_process, second_process])

    helper = SimpleNamespace(
        ensure_matching_server=lambda config_path: calls.append(("install", config_path)),
        _probe_remote_ready=lambda: next(probe_results),
        start_boot_process=lambda config_path, force_restart=True, timeout=30: calls.append(("boot", config_path)) or next(boot_results),
        stop_boot_process=lambda proc, config_path: calls.append(("stop", config_path)),
        run_cli=lambda args, timeout=60: calls.append(("cli-stop", tuple(args))),
        wait_for_device_ready=lambda timeout=120, package=None: calls.append(("ready", (timeout, package))),
    )
    runtime = DeviceServerRuntime(helper)
    config_path = Path("/tmp/device-runtime.yml")

    runtime.ensure_running(config_path)
    runtime.stop(config_path)
    runtime.ensure_running(config_path)

    assert calls == [
        ("install", config_path),
        ("boot", config_path),
        ("stop", config_path),
        ("ready", (120, None)),
        ("install", config_path),
        ("boot", config_path),
    ]


def test_device_server_runtime_retries_transient_boot_failure_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeProcess:
        def poll(self):
            return None

    process = FakeProcess()
    boot_results = iter([RuntimeError("server boot exited before the remote endpoint became ready"), process])

    def fake_start_boot_process(config_path: Path, force_restart: bool = True, timeout: int = 30):
        calls.append(("boot", config_path))
        result = next(boot_results)
        if isinstance(result, RuntimeError):
            raise result
        return result

    helper = SimpleNamespace(
        ensure_matching_server=lambda config_path: calls.append(("install", config_path)),
        _probe_remote_ready=lambda: RuntimeError("remote frida-server did not become ready"),
        start_boot_process=fake_start_boot_process,
        stop_boot_process=lambda proc, config_path: calls.append(("stop", config_path)),
        run_cli=lambda args, timeout=60: calls.append(("cli-stop", tuple(args))),
        wait_for_device_ready=lambda timeout=120, package=None: calls.append(("ready", (timeout, package))),
    )
    monkeypatch.setattr("frida_analykit.device.runtime.time.sleep", lambda _: None)
    runtime = DeviceServerRuntime(helper)
    config_path = Path("/tmp/device-runtime.yml")

    runtime.ensure_running(config_path)

    assert calls == [
        ("install", config_path),
        ("boot", config_path),
        ("ready", (60, None)),
        ("install", config_path),
        ("boot", config_path),
    ]


def test_device_server_runtime_stop_waits_for_device_readiness() -> None:
    calls: list[tuple[str, object]] = []

    class FakeProcess:
        def poll(self):
            return None

    helper = SimpleNamespace(
        stop_boot_process=lambda proc, config_path: calls.append(("stop", config_path)),
        run_cli=lambda args, timeout=60: calls.append(("cli-stop", tuple(args))),
        wait_for_device_ready=lambda timeout=120, package=None: calls.append(("ready", (timeout, package))),
    )
    runtime = DeviceServerRuntime(helper)
    runtime._process = FakeProcess()
    config_path = Path("/tmp/device-runtime.yml")
    runtime._config_path = config_path

    runtime.stop(config_path)

    assert calls == [
        ("stop", config_path),
        ("ready", (120, None)),
    ]


def test_device_app_fixture_uses_shared_server_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_calls: list[tuple[Path, int]] = []
    resolve_calls: list[dict[str, object]] = []
    config_path = Path("/tmp/device-admin.yml")

    runtime = SimpleNamespace(
        ensure_running=lambda path, timeout=60: ensure_calls.append((path, timeout)),
    )
    context = SimpleNamespace(
        device_helpers=SimpleNamespace(
            resolved_serial="SERIAL123",
            remote_host="127.0.0.1:31123",
        ),
        resolve_device_app=lambda runtime, admin_workspace, **kwargs: resolve_calls.append(kwargs) or (DEFAULT_DEVICE_TEST_APP_ID, "default-test-app"),
    )

    monkeypatch.delenv(DEVICE_CONFTEST.DEVICE_SKIP_APP_TESTS_ENV, raising=False)
    monkeypatch.delenv(DEVICE_CONFTEST.DEVICE_APP_ENV, raising=False)

    result = DEVICE_CONFTEST.device_app.__wrapped__(  # type: ignore[attr-defined]
        context,
        SimpleNamespace(config_path=config_path),
        runtime,
    )

    assert result == DEFAULT_DEVICE_TEST_APP_ID
    assert ensure_calls == [(config_path, 60)]
    assert resolve_calls == [
        {
            "explicit_app": None,
            "require_attach": True,
            "timeout": 60,
        }
    ]
