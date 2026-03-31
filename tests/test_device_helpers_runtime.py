from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from frida_analykit.development import list_managed_frida_envs
from frida_analykit.device import (
    DeviceHelpers,
    derive_remote_host,
    is_transient_device_failure,
    resolve_device_serial,
    resolve_device_serials,
    should_retry_device_operation,
)


def test_resolve_device_serial_auto_selects_single_connected_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "frida_analykit.device.selection.list_connected_android_devices",
        lambda **kwargs: (SimpleNamespace(serial="SERIAL123", state="device"),),
    )

    assert resolve_device_serial(None) == "SERIAL123"


def test_resolve_device_serial_fails_for_multiple_connected_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "frida_analykit.device.selection.list_connected_android_devices",
        lambda **kwargs: (
            SimpleNamespace(serial="SERIAL123", state="device"),
            SimpleNamespace(serial="SERIAL456", state="device"),
        ),
    )

    with pytest.raises(RuntimeError, match="multiple Android devices are connected"):
        resolve_device_serial(None)


def test_resolve_device_serial_uses_custom_multiple_device_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "frida_analykit.device.selection.list_connected_android_devices",
        lambda **kwargs: (
            SimpleNamespace(serial="SERIAL123", state="device"),
            SimpleNamespace(serial="SERIAL456", state="device"),
        ),
    )

    with pytest.raises(RuntimeError, match="pass --serial <serial> or --all-devices"):
        resolve_device_serial(None, multiple_devices_hint="pass --serial <serial> or --all-devices")


def test_resolve_device_serials_prefers_requested_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "frida_analykit.device.selection.list_connected_android_devices",
        lambda **kwargs: (
            SimpleNamespace(serial="SERIAL123", state="device"),
            SimpleNamespace(serial="SERIAL456", state="device"),
        ),
    )

    assert resolve_device_serials(("SERIAL456", "SERIAL123")) == ("SERIAL456", "SERIAL123")


def test_derive_remote_host_uses_serial_specific_port_and_linear_probe_on_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_ports: list[int] = []

    def fake_port_is_available(host: str, port: int) -> bool:
        seen_ports.append(port)
        return len(seen_ports) > 1

    monkeypatch.setattr("frida_analykit.device.selection._port_is_available", fake_port_is_available)

    host = derive_remote_host("SERIAL123")

    assert host.startswith("127.0.0.1:")
    assert len(seen_ports) == 2
    assert seen_ports[1] == seen_ports[0] + 1


def test_list_managed_frida_envs_prefers_repo_local_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    class FakeEnv:
        def __init__(self, name: str, version: str, path: str) -> None:
            self.name = name
            self.frida_version = version
            self.python_path = Path(path)

    class FakeManager:
        def __init__(self, envs):
            self._envs = envs

        def list_envs(self):
            return self._envs

    monkeypatch.setattr(
        "frida_analykit.development.managed_envs.EnvManager.for_repo",
        lambda repo_root: FakeManager([FakeEnv("repo-17", "17.8.2", "/tmp/repo-17/python")]),
    )
    monkeypatch.setattr(
        "frida_analykit.development.managed_envs.EnvManager.for_global",
        lambda: FakeManager(
            [
                FakeEnv("global-16", "16.6.6", "/tmp/global-16/python"),
                FakeEnv("global-17", "17.8.2", "/tmp/global-17/python"),
            ]
        ),
    )

    envs = list_managed_frida_envs(repo_root)

    assert [env.frida_version for env in envs] == ["16.6.6", "17.8.2"]
    assert envs[1].source == "repo"
    assert envs[1].python_path == Path("/tmp/repo-17/python")


def test_is_transient_device_failure_matches_timeout_and_transport_errors() -> None:
    assert is_transient_device_failure("frida.TimedOutError: unexpectedly timed out while waiting for signal")
    assert is_transient_device_failure("frida.ServerNotRunningError: unable to connect to remote frida-server")
    assert not is_transient_device_failure("frida.NotSupportedError: unable to pick a payload base")


def test_should_retry_device_operation_retries_boot_failures_without_remote_probe() -> None:
    helper = SimpleNamespace(_probe_remote_ready=lambda: (_ for _ in ()).throw(AssertionError("should not probe")))

    assert should_retry_device_operation(helper, stage="boot", detail="server boot exited before ready")


def test_should_retry_device_operation_retries_when_transient_marker_matches() -> None:
    helper = SimpleNamespace(_probe_remote_ready=lambda: (_ for _ in ()).throw(AssertionError("should not probe")))

    assert should_retry_device_operation(
        helper,
        stage="spawn",
        detail="frida.TimedOutError: unexpectedly timed out while waiting for signal",
    )


def test_should_retry_device_operation_checks_remote_probe_for_non_transient_failures() -> None:
    helper = SimpleNamespace(_probe_remote_ready=lambda: RuntimeError("remote endpoint vanished"))

    assert should_retry_device_operation(
        helper,
        stage="attach",
        detail="frida.ProcessNotFoundError: process not found",
    )


def test_device_helpers_pidof_remote_server_falls_back_to_server_basename() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    calls: list[list[str]] = []

    def fake_adb_run(args: list[str], *, timeout: int = 30):
        calls.append(args)
        if "pidof /data/local/tmp/frida-server" in args[-1]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "pidof frida-server" in args[-1]:
            return SimpleNamespace(returncode=0, stdout="18390\n", stderr="")
        raise AssertionError(f"unexpected adb args: {args}")

    helpers.adb_run = fake_adb_run  # type: ignore[method-assign]

    pid = helpers.pidof_remote_server()

    assert pid == 18390
    assert calls[:2] == [
        ["shell", "sh -c 'pidof /data/local/tmp/frida-server'"],
        ["shell", "su 0 sh -c 'pidof /data/local/tmp/frida-server'"],
    ]
    assert any("pidof frida-server" in command[-1] for command in calls)


def test_device_helpers_start_boot_process_retries_when_remote_pid_is_not_visible_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    config_path = repo_root / "tests" / "fixtures" / "dummy-config.yml"
    wait_calls: list[int] = []

    class FakeProcess:
        stdout = None
        stderr = None

        def poll(self):
            return None

    fake_process = FakeProcess()

    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["subprocess"], "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(helpers, "_probe_remote_ready", lambda host="127.0.0.1:27042": None)

    def fake_wait_for_remote_server_pid(*, timeout: int = 30):
        wait_calls.append(timeout)
        if len(wait_calls) == 1:
            raise TimeoutError("pid not visible yet")
        return 18390

    monkeypatch.setattr(helpers, "wait_for_remote_server_pid", fake_wait_for_remote_server_pid)
    monotonic_values = iter([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0, 2.0, 2.0])
    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["time"], "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["time"], "sleep", lambda _: None)

    process = helpers.start_boot_process(config_path, force_restart=True, timeout=10)

    assert process is fake_process
    assert wait_calls == [5, 5]


def test_device_helpers_start_boot_process_accepts_clean_boot_exit_once_remote_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    config_path = repo_root / "tests" / "fixtures" / "dummy-config.yml"

    class FakeProcess:
        stdout = None
        stderr = None

        def poll(self):
            return 0

        def communicate(self, timeout=None):
            return ("31341\n", "")

    fake_process = FakeProcess()
    probe_results = iter([RuntimeError("not ready yet"), None, None, None])

    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["subprocess"], "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(helpers, "_probe_remote_ready", lambda host="127.0.0.1:27042": next(probe_results))
    monkeypatch.setattr(helpers, "wait_for_remote_server_pid", lambda *, timeout=30: 18390)
    monotonic_values = iter([0.0, 0.0, 0.5, 1.0, 1.0])
    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["time"], "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["time"], "sleep", lambda _: None)

    process = helpers.start_boot_process(config_path, force_restart=True, timeout=10)

    assert process is fake_process


def test_device_helpers_start_boot_process_stops_before_collecting_timeout_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    config_path = repo_root / "tests" / "fixtures" / "dummy-config.yml"
    stop_calls: list[Path] = []

    class _UnreadablePipe:
        def read(self):
            raise AssertionError("stdout/stderr.read() should not be used on a live boot process")

    class FakeProcess:
        stdout = _UnreadablePipe()
        stderr = _UnreadablePipe()

        def poll(self):
            return None

        def communicate(self, timeout=None):
            return ("boot-stdout", "boot-stderr")

        def kill(self):
            return None

    fake_process = FakeProcess()

    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["subprocess"], "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(helpers, "_probe_remote_ready", lambda host="127.0.0.1:27042": RuntimeError("not ready"))
    monkeypatch.setattr(helpers, "stop_boot_process", lambda process, config_path: stop_calls.append(config_path))
    monotonic_values = iter([0.0, 0.0, 0.0, 11.0, 11.0])
    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["time"], "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["time"], "sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="timed out waiting for `frida-analykit server boot`"):
        helpers.start_boot_process(config_path, force_restart=True, timeout=10)

    assert stop_calls == [config_path]


def test_device_helpers_find_attachable_app_pid_keeps_polling_after_nonzero_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    launch_result = SimpleNamespace(returncode=1, stdout="", stderr="transient launch failure")
    pid_sequence = iter([None, 4321])
    probe_calls: list[int] = []

    monkeypatch.setattr(helpers, "launch_app", lambda package, timeout=30: launch_result)
    monkeypatch.setattr(helpers, "pidof_app", lambda package, timeout=30: next(pid_sequence))
    monkeypatch.setattr(
        helpers,
        "_probe_attachable_pid",
        lambda pid, host="127.0.0.1:27042", timeout=10: (probe_calls.append(pid), None)[1],
    )
    monkeypatch.setattr(DeviceHelpers.find_attachable_app_pid.__globals__["time"], "sleep", lambda _: None)

    pid, error = helpers.find_attachable_app_pid("com.demo", timeout=10)

    assert pid == 4321
    assert error is None
    assert probe_calls == [4321]


def test_device_helpers_find_attachable_app_pid_retries_launch_until_pid_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    launch_results = iter([
        SimpleNamespace(returncode=1, stdout="", stderr="activity manager unavailable"),
        SimpleNamespace(returncode=0, stdout="started", stderr=""),
    ])
    pid_sequence = iter([None, None, None, 5678])
    probe_calls: list[int] = []
    launch_calls: list[str] = []

    monkeypatch.setattr(
        helpers,
        "launch_app",
        lambda package, timeout=30: (launch_calls.append(package), next(launch_results))[1],
    )
    monkeypatch.setattr(helpers, "pidof_app", lambda package, timeout=30: next(pid_sequence))
    monkeypatch.setattr(
        helpers,
        "_probe_attachable_pid",
        lambda pid, host="127.0.0.1:27042", timeout=10: (probe_calls.append(pid), None)[1],
    )
    monotonic_values = iter([0.0, 0.0, 0.5, 2.5, 2.5, 5.0, 5.0, 5.5, 5.5])
    monkeypatch.setattr(DeviceHelpers.find_attachable_app_pid.__globals__["time"], "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(DeviceHelpers.find_attachable_app_pid.__globals__["time"], "sleep", lambda _: None)

    pid, error = helpers.find_attachable_app_pid("com.demo", timeout=10)

    assert pid == 5678
    assert error is None
    assert launch_calls == ["com.demo", "com.demo"]
    assert probe_calls == [5678]


def test_device_helpers_probe_remote_ready_uses_real_remote_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        helpers,
        "run_python_probe",
        lambda code, timeout=30, extra_env=None: captured.update(code=code, timeout=timeout)
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = helpers._probe_remote_ready()

    assert result is None
    assert captured["timeout"] == 30
    assert "query_system_parameters()" in captured["code"]


def test_device_helpers_wait_for_device_ready_retries_until_boot_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial="SERIAL123",
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    calls: list[list[str]] = []
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="0\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="0\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="1\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="package:/system/framework/framework-res.apk\n", stderr=""),
        ]
    )

    def fake_adb_run(args: list[str], *, timeout: int = 30):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(helpers, "adb_run", fake_adb_run)
    monkeypatch.setattr("frida_analykit.device.helpers.time.sleep", lambda _: None)
    monotonic_values = iter([0.0, 0.0, 1.0, 1.0, 2.0, 2.0])
    monkeypatch.setattr("frida_analykit.device.helpers.time.monotonic", lambda: next(monotonic_values))

    helpers.wait_for_device_ready(timeout=10)

    assert calls == [
        ["wait-for-device"],
        ["shell", "getprop", "sys.boot_completed"],
        ["shell", "getprop", "dev.bootcomplete"],
        ["wait-for-device"],
        ["shell", "getprop", "sys.boot_completed"],
        ["shell", "pm", "path", "android"],
    ]
