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


def test_detect_device_abi_maps_android_properties(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)
    adb_calls: list[list[str]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, stdout="arm64-v8a,armeabi-v7a\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    assert manager.detect_device_abi(config) == ("arm64-v8a", "android-arm64")
    assert adb_calls[0] == ["adb", "devices", "-l"]
    assert adb_calls[1][:3] == ["adb", "-s", "emulator-5554"]


def test_detect_device_abi_maps_system_product_properties(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if _plain_shell(args, "getprop ro.system.product.cpu.abilist64"):
            return _completed(args, stdout="x86_64,x86\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    assert manager.detect_device_abi(config) == ("x86_64", "android-x86_64")


def test_detect_device_abi_scans_full_getprop_output(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if _plain_shell(args, "getprop"):
            return _completed(args, stdout="[ro.system.product.cpu.abi]: [x86]\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    assert manager.detect_device_abi(config) == ("x86", "android-x86")


def test_detect_device_abi_falls_back_to_cpuinfo(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if _plain_shell(args, "cat /proc/cpuinfo"):
            return _completed(args, stdout="Processor\t: AArch64 Processor rev 13\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    assert manager.detect_device_abi(config) == ("arm64-v8a", "android-arm64")


def test_detect_device_abi_auto_selects_single_connected_device(tmp_path: Path) -> None:
    config = _remote_config_without_device(tmp_path)
    adb_calls: list[list[str]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("SERIAL123"))
        if args[:3] == ["adb", "-s", "SERIAL123"] and _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, stdout="arm64-v8a,armeabi-v7a\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    assert manager.detect_device_abi(config) == ("arm64-v8a", "android-arm64")
    assert adb_calls[0] == ["adb", "devices", "-l"]
    assert adb_calls[1][:3] == ["adb", "-s", "SERIAL123"]


def test_detect_device_abi_fails_when_multiple_devices_are_connected_without_target(tmp_path: Path) -> None:
    config = _remote_config_without_device(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("SERIAL123", "SERIAL456"))
        raise AssertionError(f"unexpected adb command: {args}")

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(RuntimeError, match="set config.server.device or ANDROID_SERIAL=<serial>"):
        manager.detect_device_abi(config)


def test_detect_device_abi_surfaces_adb_transport_errors(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, returncode=1, stderr="adb: error: device not found\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(RuntimeError, match="device ABI detection failed while running `getprop ro.product.cpu.abilist64`: adb: error: device not found"):
        manager.detect_device_abi(config)
