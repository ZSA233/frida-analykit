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


def test_install_remote_server_downloads_extracts_and_pushes(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    pushed: list[list[str]] = []
    payload = b"fake frida-server binary"
    compressed = lzma.compress(payload)

    def fake_urlopen(request):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/releases/tags/17.8.1"):
            body = json.dumps(
                {
                    "assets": [
                        {
                            "name": "frida-server-17.8.1-android-arm64.xz",
                            "browser_download_url": "https://downloads.example.test/frida-server.xz",
                        }
                    ]
                }
            ).encode("utf-8")
            return _Response(body)
        if url == "https://downloads.example.test/frida-server.xz":
            return _Response(compressed, headers={"Content-Length": str(len(compressed))})
        raise AssertionError(f"unexpected download url: {url}")

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        pushed.append(args)
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, stdout="arm64-v8a,armeabi-v7a\n")
        if len(args) >= 3 and args[-3] == "push":
            assert Path(args[-2]).exists()
            return _completed(args, stdout="1 file pushed\n")
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="17.8.1\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        urlopen_func=fake_urlopen,
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    result = manager.install_remote_server(config)

    assert result.selected_version == "17.8.1"
    assert result.installed_version == "17.8.1"
    assert result.device_abi == "arm64-v8a"
    assert result.asset_arch == "android-arm64"
    assert result.local_source is None
    assert result.local_binary.read_bytes() == payload
    assert any(len(args) >= 3 and args[-3] == "push" for args in pushed)
    assert any(_plain_shell(args, "mkdir -p /data/local/tmp") for args in pushed)
    assert any(
        _plain_shell(args, "mv /data/local/tmp/.frida-analykit-frida-server-17.8.1 /data/local/tmp/frida-server")
        for args in pushed
    )
    assert any(
        _plain_shell(args, "chmod 755 /data/local/tmp/frida-server")
        for args in pushed
    )


def test_install_remote_server_rejects_force_download_without_explicit_version(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(ServerManagerError, match="requires an explicit `--version`"):
        manager.install_remote_server(config, force_download=True)


def test_install_remote_server_pushes_local_binary(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    local_source = tmp_path / "frida-server"
    local_source.write_bytes(b"local frida-server")
    pushed: list[list[str]] = []
    unexpected_abi_probe_commands = {
        "getprop ro.product.cpu.abilist64",
        "getprop ro.product.cpu.abilist",
        "getprop ro.product.cpu.abilist32",
        "getprop ro.product.cpu.abi",
        "getprop ro.product.cpu.abi2",
        "getprop ro.odm.product.cpu.abilist64",
        "getprop ro.odm.product.cpu.abilist",
        "getprop ro.odm.product.cpu.abilist32",
        "getprop ro.odm.product.cpu.abi",
        "getprop ro.odm.product.cpu.abi2",
        "getprop ro.vendor.product.cpu.abilist64",
        "getprop ro.vendor.product.cpu.abilist",
        "getprop ro.vendor.product.cpu.abilist32",
        "getprop ro.vendor.product.cpu.abi",
        "getprop ro.vendor.product.cpu.abi2",
        "getprop ro.system.product.cpu.abilist64",
        "getprop ro.system.product.cpu.abilist",
        "getprop ro.system.product.cpu.abilist32",
        "getprop ro.system.product.cpu.abi",
        "getprop ro.system.product.cpu.abi2",
        "getprop",
        "uname -m",
        "cat /proc/cpuinfo",
    }

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        pushed.append(args)
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-1] == "get-serialno":
            return _completed(args, stdout="emulator-5554\n")
        if any(_plain_shell(args, command) for command in unexpected_abi_probe_commands):
            raise AssertionError(f"unexpected ABI probe command: {args}")
        if len(args) >= 3 and args[-3] == "push":
            assert Path(args[-2]).read_bytes() == b"local frida-server"
            return _completed(args)
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="16.5.9\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        urlopen_func=lambda request: (_ for _ in ()).throw(AssertionError("download should not be used")),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    result = manager.install_remote_server(config, local_server_path=local_source)

    assert result.local_source == local_source.resolve()
    assert result.local_binary.read_bytes() == b"local frida-server"
    assert result.device_abi is None
    assert result.asset_arch is None
    assert result.installed_version == "16.5.9"
    assert result.local_source_abi_hint is None
    assert result.local_source_asset_arch_hint is None


def test_install_remote_server_extracts_local_xz_archive(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    local_source = tmp_path / "frida-server-16.5.9-android-arm64.xz"
    local_source.write_bytes(lzma.compress(b"local archive frida-server"))

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if args[-1] == "get-serialno":
            return _completed(args, stdout="emulator-5554\n")
        if len(args) >= 3 and args[-3] == "push":
            assert Path(args[-2]).read_bytes() == b"local archive frida-server"
            return _completed(args)
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="16.5.9\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    result = manager.install_remote_server(config, local_server_path=local_source)

    assert result.local_source == local_source.resolve()
    assert result.local_binary.read_bytes() == b"local archive frida-server"
    assert result.selected_version == "16.5.9"
    assert result.device_abi is None
    assert result.asset_arch is None
    assert result.local_source_abi_hint == "arm64-v8a"
    assert result.local_source_asset_arch_hint == "android-arm64"


def test_install_remote_server_rejects_unexecutable_local_binary(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    local_source = tmp_path / "frida-server-16.5.9-android-arm64.xz"
    local_source.write_bytes(lzma.compress(b"bad binary"))

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if len(args) >= 3 and args[-3] == "push":
            return _completed(args)
        if _plain_shell(args, "mkdir -p /data/local/tmp"):
            return _completed(args)
        if _plain_shell(args, "mv /data/local/tmp/.frida-analykit-frida-server-16.5.9 /data/local/tmp/frida-server"):
            return _completed(args)
        if _plain_shell(args, "chmod 755 /data/local/tmp/frida-server"):
            return _completed(args)
        if _plain_shell(args, "rm -f /data/local/tmp/.frida-analykit-frida-server-16.5.9"):
            return _completed(args)
        if args[-1] == "get-serialno":
            return _completed(args, stdout="emulator-5554\n")
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, returncode=126, stderr="Permission denied\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(ServerManagerError, match="installed server validation failed"):
        manager.install_remote_server(config, local_server_path=local_source)


def test_install_remote_server_rejects_downloaded_version_mismatch(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    payload = b"fake frida-server binary"
    compressed = lzma.compress(payload)

    def fake_urlopen(request):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/releases/tags/17.8.1"):
            return _Response(
                json.dumps(
                    {
                        "assets": [
                            {
                                "name": "frida-server-17.8.1-android-arm64.xz",
                                "browser_download_url": "https://downloads.example.test/frida-server.xz",
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        if url == "https://downloads.example.test/frida-server.xz":
            return _Response(compressed, headers={"Content-Length": str(len(compressed))})
        raise AssertionError(f"unexpected download url: {url}")

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args == ["adb", "devices", "-l"]:
            return _completed(args, stdout=_connected_devices_output("emulator-5554"))
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, stdout="arm64-v8a\n")
        if len(args) >= 3 and args[-3] == "push":
            return _completed(args)
        if _plain_shell(args, "mkdir -p /data/local/tmp"):
            return _completed(args)
        if _plain_shell(args, "mv /data/local/tmp/.frida-analykit-frida-server-17.8.1 /data/local/tmp/frida-server"):
            return _completed(args)
        if _plain_shell(args, "chmod 755 /data/local/tmp/frida-server"):
            return _completed(args)
        if _plain_shell(args, "rm -f /data/local/tmp/.frida-analykit-frida-server-17.8.1"):
            return _completed(args)
        if args[-1] == "get-serialno":
            return _completed(args, stdout="emulator-5554\n")
        if _plain_shell(args, "ls /data/local/tmp/frida-server"):
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if _plain_shell(args, "/data/local/tmp/frida-server --version"):
            return _completed(args, stdout="16.5.9\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        urlopen_func=fake_urlopen,
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(ServerManagerError, match="installed server version mismatch"):
        manager.install_remote_server(config)


def test_download_server_binary_reports_progress(tmp_path: Path) -> None:
    payload = b"fake frida-server binary"
    compressed = lzma.compress(payload)
    progress: list[tuple[int, int | None]] = []

    def fake_urlopen(request):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/releases/tags/17.8.1"):
            body = json.dumps(
                {
                    "assets": [
                        {
                            "name": "frida-server-17.8.1-android-arm64.xz",
                            "browser_download_url": "https://downloads.example.test/frida-server.xz",
                        }
                    ]
                }
            ).encode("utf-8")
            return _Response(body)
        if url == "https://downloads.example.test/frida-server.xz":
            return _Response(compressed, headers={"Content-Length": str(len(compressed))})
        raise AssertionError(f"unexpected download url: {url}")

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        urlopen_func=fake_urlopen,
        cache_dir=tmp_path / "cache",
    )

    downloaded = manager.download_server_binary(
        "17.8.1",
        device_abi="arm64-v8a",
        asset_arch="android-arm64",
        force=True,
        progress_callback=lambda downloaded, total: progress.append((downloaded, total)),
    )

    assert downloaded.archive_path.read_bytes() == compressed
    assert downloaded.binary_path.read_bytes() == payload
    assert progress[0] == (0, len(compressed))
    assert progress[-1] == (len(compressed), len(compressed))
