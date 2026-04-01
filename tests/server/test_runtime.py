from __future__ import annotations

import io
import json
import lzma
import shlex
import subprocess
from pathlib import Path

import frida
import pytest

from frida_analykit.compat import FridaCompat
from frida_analykit.config import AppConfig
from frida_analykit.diagnostics import set_verbose
from frida_analykit.server import FridaServerManager, ServerManagerError

from .support import (
    _FakeFrida,
    _FakeProcess,
    _Response,
    _completed,
    _connected_devices_output,
    _plain_shell,
    _remote_config,
    _remote_config_without_device,
    _su0_shell,
    _suc_shell,
    _suroot_shell,
)


def test_boot_remote_server_forwards_port_and_starts_foreground_process(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    adb_calls: list[list[str]] = []
    popen_calls: list[list[str]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-3:] == ["forward", "tcp:27042", "tcp:27042"]:
            return _completed(args)
        if _su0_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: unknown id 0\n")
        if _suroot_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: unknown id root\n")
        if _suc_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: invalid uid/gid '-c'\n")
        if _plain_shell(args, "pidof /data/local/tmp/frida-server"):
            return _completed(args, returncode=1)
        if _plain_shell(args, "pidof frida-server"):
            return _completed(args, returncode=1)
        if _plain_shell(args, "ps -A"):
            return _completed(args)
        if _plain_shell(args, "ps"):
            return _completed(args)
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.8.1\n")
        if args[-3:] == ["forward", "--remove", "tcp:27042"]:
            return _completed(args)
        raise AssertionError(f"unexpected adb run command: {args}")

    def fake_popen(args: list[str], **kwargs):
        popen_calls.append(args)
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.PIPE
        assert kwargs["text"] is True
        return _FakeProcess()

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        subprocess_popen=fake_popen,
        cache_dir=tmp_path / "cache",
    )

    manager.boot_remote_server(config)

    assert adb_calls[0] == ["adb", "devices", "-l"]
    assert any(_plain_shell(args, "pidof /data/local/tmp/frida-server") for args in adb_calls)
    assert ["adb", "-s", "emulator-5554", "forward", "tcp:27042", "tcp:27042"] in adb_calls
    assert any(_plain_shell(args, "/data/local/tmp/frida-server --version") for args in adb_calls)
    assert len(popen_calls) == 1
    assert popen_calls[0][:5] == ["adb", "-s", "emulator-5554", "shell", "-T"]
    assert popen_calls[0][-1] == "sh -c 'exec /data/local/tmp/frida-server -l 0.0.0.0:27042 1>/dev/null'"
    assert adb_calls[-1] == ["adb", "-s", "emulator-5554", "forward", "--remove", "tcp:27042"]


def test_boot_remote_server_interrupt_kills_new_remote_process_and_removes_forward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    adb_calls: list[list[str]] = []
    terminated = {"called": False}
    killed: list[set[int]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-3:] == ["forward", "tcp:27042", "tcp:27042"]:
            return _completed(args)
        if _su0_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: unknown id 0\n")
        if _suroot_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: unknown id root\n")
        if _suc_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: invalid uid/gid '-c'\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.8.1\n")
        if args[-3:] == ["forward", "--remove", "tcp:27042"]:
            return _completed(args)
        raise AssertionError(f"unexpected adb run command: {args}")

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        subprocess_popen=lambda args, **kwargs: _FakeProcess(interrupt=True),
        cache_dir=tmp_path / "cache",
    )

    pid_snapshots = [set(), set(), {4242}]

    def fake_list_remote_server_pids(_config: AppConfig) -> set[int]:
        if pid_snapshots:
            return pid_snapshots.pop(0)
        return set()

    monkeypatch.setattr(manager._boot, "list_remote_server_pids", fake_list_remote_server_pids)
    monkeypatch.setattr(manager._adb, "terminate_process", lambda process: terminated.update(called=True))
    monkeypatch.setattr(manager._boot, "_kill_remote_pids", lambda _config, pids: killed.append(set(pids)))

    manager.boot_remote_server(config)

    assert terminated["called"] is True
    assert killed == [{4242}]
    assert adb_calls[-1] == ["adb", "-s", "emulator-5554", "forward", "--remove", "tcp:27042"]


def test_boot_remote_server_prefers_root_when_available(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    adb_calls: list[list[str]] = []
    popen_calls: list[list[str]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-3:] == ["forward", "tcp:27042", "tcp:27042"]:
            return _completed(args)
        if _su0_shell(args, "id -u"):
            return _completed(args, stdout="0\n")
        if _suroot_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: unknown id root\n")
        if _suc_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: invalid uid/gid '-c'\n")
        if _plain_shell(args, "pidof /data/local/tmp/frida-server"):
            return _completed(args, returncode=1)
        if _plain_shell(args, "pidof frida-server"):
            return _completed(args, returncode=1)
        if _plain_shell(args, "ps -A"):
            return _completed(args)
        if _plain_shell(args, "ps"):
            return _completed(args)
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.8.1\n")
        if args[-3:] == ["forward", "--remove", "tcp:27042"]:
            return _completed(args)
        raise AssertionError(f"unexpected adb run command: {args}")

    def fake_popen(args: list[str], **kwargs):
        popen_calls.append(args)
        if args[:5] == ["adb", "-s", "emulator-5554", "shell", "-T"] and args[-1].startswith("su 0 sh -c "):
            return _FakeProcess()
        raise AssertionError(f"unexpected adb popen command: {args}")

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        subprocess_popen=fake_popen,
        cache_dir=tmp_path / "cache",
    )

    manager.boot_remote_server(config)

    assert any(_su0_shell(args, "id -u") for args in adb_calls)
    assert len(popen_calls) == 1
    assert popen_calls[0][:5] == ["adb", "-s", "emulator-5554", "shell", "-T"]
    assert popen_calls[0][-1].startswith("su 0 sh -c ")


def test_boot_remote_server_rejects_existing_process_without_force_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        raise AssertionError(f"unexpected adb run command: {args}")

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    monkeypatch.setattr(manager._boot, "list_remote_server_pids", lambda _config: {31337})

    with pytest.raises(ServerManagerError, match="already running"):
        manager.boot_remote_server(config)


def test_boot_remote_server_force_restart_kills_existing_process_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    killed: list[set[int]] = []
    pid_snapshots = [{31337}, set()]

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-3:] == ["forward", "tcp:27042", "tcp:27042"]:
            return _completed(args)
        if _su0_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: unknown id 0\n")
        if _suroot_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: unknown id root\n")
        if _suc_shell(args, "id -u"):
            return _completed(args, returncode=1, stderr="su: invalid uid/gid '-c'\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.8.1\n")
        if args[-3:] == ["forward", "--remove", "tcp:27042"]:
            return _completed(args)
        raise AssertionError(f"unexpected adb run command: {args}")

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        subprocess_popen=lambda args, **kwargs: _FakeProcess(),
        cache_dir=tmp_path / "cache",
    )

    monkeypatch.setattr(
        manager._boot,
        "list_remote_server_pids",
        lambda _config: pid_snapshots.pop(0) if pid_snapshots else set(),
    )
    monkeypatch.setattr(manager._boot, "_kill_remote_pids", lambda _config, pids: killed.append(set(pids)))

    manager.boot_remote_server(config, force_restart=True)

    assert killed == [{31337}]


def test_stop_remote_server_kills_matching_processes_and_removes_forward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    adb_calls: list[list[str]] = []
    killed: list[set[int]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-3:] == ["forward", "--remove", "tcp:27042"]:
            return _completed(args)
        raise AssertionError(f"unexpected adb run command: {args}")

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    monkeypatch.setattr(manager._boot, "list_remote_server_pids", lambda _config: {111, 222})
    monkeypatch.setattr(manager._boot, "_kill_remote_pids", lambda _config, pids: killed.append(set(pids)))

    stopped = manager.stop_remote_server(config)

    assert stopped == {111, 222}
    assert killed == [{111, 222}]
    assert adb_calls[-1] == ["adb", "-s", "emulator-5554", "forward", "--remove", "tcp:27042"]


def test_stop_remote_server_returns_success_when_nothing_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    adb_calls: list[list[str]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-3:] == ["forward", "--remove", "tcp:27042"]:
            return _completed(args)
        raise AssertionError(f"unexpected adb run command: {args}")

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    monkeypatch.setattr(manager._boot, "list_remote_server_pids", lambda _config: set())

    assert manager.stop_remote_server(config) == set()
    assert adb_calls[-1] == ["adb", "-s", "emulator-5554", "forward", "--remove", "tcp:27042"]


def test_shell_with_auto_root_falls_back_when_plain_and_su_c_fail(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        calls.append(args)
        if _plain_shell(args, "ls /vendor/bin/frida-server"):
            return _completed(args, returncode=1, stderr="Permission denied\n")
        if _su0_shell(args, "ls /vendor/bin/frida-server"):
            return _completed(args, returncode=1, stderr="su: unknown id 0\n")
        if _suroot_shell(args, "ls /vendor/bin/frida-server"):
            return _completed(args, stdout="/vendor/bin/frida-server\n")
        if _suc_shell(args, "ls /vendor/bin/frida-server"):
            return _completed(args, returncode=1, stderr="su: invalid uid/gid '-c'\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    result = manager._adb.shell_with_auto_root(config, "ls /vendor/bin/frida-server", check=False)

    assert result.stdout.strip() == "/vendor/bin/frida-server"
    assert any(_plain_shell(args, "ls /vendor/bin/frida-server") for args in calls)
    assert any(_su0_shell(args, "ls /vendor/bin/frida-server") for args in calls)
    assert any(_suroot_shell(args, "ls /vendor/bin/frida-server") for args in calls)
