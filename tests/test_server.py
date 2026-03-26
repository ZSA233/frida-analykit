import io
import json
import lzma
import subprocess
from pathlib import Path

import pytest

from frida_analykit.compat import FridaCompat
from frida_analykit.config import AppConfig
from frida_analykit.diagnostics import set_verbose
from frida_analykit.server import FridaServerManager


class _FakeFrida:
    __version__ = "17.8.2"


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _remote_config(tmp_path: Path, *, version: str | None = None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": "_agent.js",
            "server": {
                "host": "127.0.0.1:27042",
                "device": "emulator-5554",
                "servername": "/data/local/tmp/frida-server",
                "version": version,
            },
            "agent": {},
            "script": {"nettools": {}},
        }
    ).resolve_paths(tmp_path, source_path=tmp_path / "config.yml")


def _completed(args: list[str], *, stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


def test_detect_device_abi_maps_android_properties(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)
    adb_calls: list[list[str]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args[-2:] == ["shell", "getprop ro.product.cpu.abilist64"]:
            return _completed(args, stdout="arm64-v8a,armeabi-v7a\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    assert manager.detect_device_abi(config) == ("arm64-v8a", "android-arm64")
    assert adb_calls[0][:3] == ["adb", "-s", "emulator-5554"]


def test_boot_remote_server_forwards_port_and_starts_foreground_process(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    adb_calls: list[list[str]] = []
    popen_calls: list[list[str]] = []

    class FakeProcess:
        def wait(self, timeout=None):
            return 0

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args[-3:] == ["forward", "tcp:27042", "tcp:27042"]:
            return _completed(args)
        if args[-2:] == ["shell", "su -c 'pidof /data/local/tmp/frida-server'"]:
            return _completed(args, returncode=1)
        if args[-2:] == ["shell", "su -c 'pidof frida-server'"]:
            return _completed(args, returncode=1)
        if args[-2:] == ["shell", "su -c 'ps -A'"]:
            return _completed(args)
        if args[-2:] == ["shell", "su -c ps"]:
            return _completed(args)
        if args[-2:] == ["shell", "su -c '/data/local/tmp/frida-server --version'"]:
            return _completed(args, stdout="17.8.1\n")
        if args[-3:] == ["forward", "--remove", "tcp:27042"]:
            return _completed(args)
        raise AssertionError(f"unexpected adb run command: {args}")

    def fake_popen(args: list[str]):
        popen_calls.append(args)
        return FakeProcess()

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        subprocess_popen=fake_popen,
        cache_dir=tmp_path / "cache",
    )

    manager.boot_remote_server(config)

    assert adb_calls[0] == ["adb", "-s", "emulator-5554", "forward", "tcp:27042", "tcp:27042"]
    assert [
        "adb",
        "-s",
        "emulator-5554",
        "shell",
        "su -c '/data/local/tmp/frida-server --version'",
    ] in adb_calls
    assert popen_calls == [
        [
            "adb",
            "-s",
            "emulator-5554",
            "shell",
            "su -c '/data/local/tmp/frida-server -l 0.0.0.0:27042'",
        ]
    ]
    assert adb_calls[-1] == ["adb", "-s", "emulator-5554", "forward", "--remove", "tcp:27042"]


def test_boot_remote_server_interrupt_kills_new_remote_process_and_removes_forward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    adb_calls: list[list[str]] = []
    terminated = {"called": False}
    killed: list[set[int]] = []

    class FakeProcess:
        def wait(self, timeout=None):
            raise KeyboardInterrupt

        def terminate(self):
            terminated["called"] = True

        def kill(self):
            terminated["called"] = True

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if args[-3:] == ["forward", "tcp:27042", "tcp:27042"]:
            return _completed(args)
        if args[-2:] == ["shell", "su -c '/data/local/tmp/frida-server --version'"]:
            return _completed(args, stdout="17.8.1\n")
        if args[-3:] == ["forward", "--remove", "tcp:27042"]:
            return _completed(args)
        raise AssertionError(f"unexpected adb run command: {args}")

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        subprocess_popen=lambda args: FakeProcess(),
        cache_dir=tmp_path / "cache",
    )

    pid_snapshots = [set(), {4242}]

    def fake_list_remote_server_pids(_config: AppConfig) -> set[int]:
        if pid_snapshots:
            return pid_snapshots.pop(0)
        return set()

    monkeypatch.setattr(manager, "list_remote_server_pids", fake_list_remote_server_pids)
    monkeypatch.setattr(
        manager,
        "_kill_remote_pids",
        lambda _config, pids: killed.append(set(pids)),
    )

    manager.boot_remote_server(config)

    assert terminated["called"] is True
    assert killed == [{4242}]
    assert adb_calls[-1] == ["adb", "-s", "emulator-5554", "forward", "--remove", "tcp:27042"]


def test_install_remote_server_downloads_extracts_and_pushes(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    pushed: list[list[str]] = []
    payload = b"fake frida-server binary"

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
            return _Response(lzma.compress(payload))
        raise AssertionError(f"unexpected download url: {url}")

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        pushed.append(args)
        if args[-2:] == ["shell", "getprop ro.product.cpu.abilist64"]:
            return _completed(args, stdout="arm64-v8a,armeabi-v7a\n")
        if len(args) >= 3 and args[-3] == "push":
            assert Path(args[-2]).exists()
            return _completed(args, stdout="1 file pushed\n")
        if args[-2:] == ["shell", "su -c 'ls /data/local/tmp/frida-server'"]:
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if args[-2:] == ["shell", "su -c '/data/local/tmp/frida-server --version'"]:
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
    assert result.local_binary.read_bytes() == payload
    assert any(len(args) >= 3 and args[-3] == "push" for args in pushed)
    assert any(args[-2:] == ["shell", "su -c 'mkdir -p /data/local/tmp'"] for args in pushed)
    assert any(
        args[-2:] == ["shell", "su -c 'mv /data/local/tmp/.frida-analykit-frida-server-17.8.1 /data/local/tmp/frida-server'"]
        for args in pushed
    )
    assert any(
        args[-2:] == ["shell", "su -c 'chmod 755 /data/local/tmp/frida-server'"]
        for args in pushed
    )


def test_inspect_remote_server_reports_existing_version(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        if args[-2:] == ["shell", "getprop ro.product.cpu.abilist64"]:
            return _completed(args, stdout="arm64-v8a\n")
        if args[-2:] == ["shell", "su -c 'ls /data/local/tmp/frida-server'"]:
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if args[-2:] == ["shell", "su -c '/data/local/tmp/frida-server --version'"]:
            return _completed(args, stdout="17.8.0\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    status = manager.inspect_remote_server(config)

    assert status.exists is True
    assert status.executable is True
    assert status.installed_version == "17.8.0"
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
        if args[-2:] == ["shell", "getprop ro.product.cpu.abilist64"]:
            return _completed(
                args,
                stdout="[ro.product.cpu.abilist64]: [arm64-v8a]\n[ro.product.cpu.abi]: [armeabi-v7a]\n",
            )
        if args[-2:] == ["shell", "su -c 'ls /data/local/tmp/frida-server'"]:
            return _completed(args, stdout="/data/local/tmp/frida-server\n")
        if args[-2:] == ["shell", "su -c '/data/local/tmp/frida-server --version'"]:
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
    assert "running adb command: adb -s emulator-5554 shell 'getprop ro.product.cpu.abilist64'" in captured.err
    assert "running adb command: adb -s emulator-5554 shell 'su -c '" in captured.err
    assert "stdout from adb -s emulator-5554 shell 'su -c '" in captured.err
    assert "resolved frida-server version `17.8.2`" in captured.err
    assert "Device ABI" not in captured.err
