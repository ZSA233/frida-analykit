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
    _auto_root_shell,
    _completed,
    _connected_devices_output,
    _plain_shell,
    _remote_config,
    _remote_config_without_device,
)


def test_inspect_remote_server_reports_existing_version(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-1] == "get-serialno":
            return _completed(args, stdout="emulator-5554\n")
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, stdout="arm64-v8a\n")
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.8.0\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    status = manager.inspect_remote_server(config)

    assert status.adb_target == "emulator-5554"
    assert status.resolved_device == "emulator-5554"
    assert status.resolved_device_source == "config.server.device"
    assert status.selected_version == "17.8.2"
    assert status.selected_version_source == "installed Frida"
    assert status.exists is True
    assert status.executable is True
    assert status.installed_version == "17.8.0"
    assert status.version_matches_target is False
    assert status.supported is True
    assert status.matched_profile == "current-17"
    assert status.device_abi == "arm64-v8a"
    assert status.asset_arch == "android-arm64"


def test_inspect_remote_server_emits_verbose_command_logs(
    tmp_path: Path,
    capsys,
) -> None:
    config = _remote_config(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-1] == "get-serialno":
            return _completed(args, stdout="emulator-5554\n")
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(
                args,
                stdout="[ro.product.cpu.abilist64]: [arm64-v8a]\n[ro.product.cpu.abi]: [armeabi-v7a]\n",
            )
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.8.0\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    set_verbose(True)
    try:
        manager.inspect_remote_server(config)
    finally:
        set_verbose(False)

    captured = capsys.readouterr()
    assert "running adb command: adb -s emulator-5554 get-serialno" in captured.err
    assert "running adb command: adb -s emulator-5554 shell " in captured.err
    assert "getprop ro.product.cpu.abilist64" in captured.err
    assert "ls /data/local/tmp/frida-server" in captured.err
    assert "stdout from adb -s emulator-5554 shell " in captured.err
    assert "/data/local/tmp/frida-server --version" in captured.err
    assert "resolved frida-server version `17.8.2`" in captured.err
    assert "Device ABI" not in captured.err


def test_inspect_remote_server_reports_reachable_remote_host(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    class _FakeRemoteDevice:
        def enumerate_processes(self) -> list[object]:
            return []

    class _FakeDeviceManager:
        def add_remote_device(self, host: str) -> _FakeRemoteDevice:
            assert host == "127.0.0.1:27042"
            return _FakeRemoteDevice()

    class _FakeFridaWithRemote(_FakeFrida):
        def get_device_manager(self) -> _FakeDeviceManager:
            return _FakeDeviceManager()

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-1] == "get-serialno":
            return _completed(args, stdout="emulator-5554\n")
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, stdout="arm64-v8a\n")
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.8.0\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFridaWithRemote()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    status = manager.inspect_remote_server(config, probe_host=True)

    assert status.host_reachable is True
    assert status.host_error is None
    assert status.protocol_compatible is True
    assert status.protocol_error is None


def test_inspect_remote_server_reports_unreachable_remote_host(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    class _FakeDeviceManager:
        def add_remote_device(self, host: str):
            assert host == "127.0.0.1:27042"
            raise RuntimeError("connection closed")

    class _FakeFridaWithBrokenRemote(_FakeFrida):
        def get_device_manager(self) -> _FakeDeviceManager:
            return _FakeDeviceManager()

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-1] == "get-serialno":
            return _completed(args, stdout="emulator-5554\n")
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, stdout="arm64-v8a\n")
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.8.0\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFridaWithBrokenRemote()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    status = manager.inspect_remote_server(config, probe_host=True)

    assert status.host_reachable is False
    assert status.host_error == "connection closed"
    assert status.protocol_compatible is None
    assert status.protocol_error is None


def test_inspect_remote_server_reports_protocol_incompatibility_separately(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="16.6.6")

    class _FakeRemoteDevice:
        def enumerate_processes(self) -> list[object]:
            raise frida.ProtocolError(
                "unable to communicate with remote frida-server; please ensure that major versions match"
            )

    class _FakeDeviceManager:
        def add_remote_device(self, host: str) -> _FakeRemoteDevice:
            assert host == "127.0.0.1:27042"
            return _FakeRemoteDevice()

    class _FakeFridaWithProtocolMismatch(_FakeFrida):
        def get_device_manager(self) -> _FakeDeviceManager:
            return _FakeDeviceManager()

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-1] == "get-serialno":
            return _completed(args, stdout="emulator-5554\n")
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, stdout="arm64-v8a\n")
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.7.0\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFridaWithProtocolMismatch()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    status = manager.inspect_remote_server(config, probe_host=True)

    assert status.host_reachable is True
    assert status.protocol_compatible is False
    assert "major versions match" in (status.protocol_error or "")
    assert status.selected_version == "16.6.6"
    assert status.selected_version_source == "config.server.version"
    assert status.installed_version == "17.7.0"
    assert status.version_matches_target is False
