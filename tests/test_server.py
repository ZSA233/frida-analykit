import io
import json
import lzma
import shlex
import subprocess
from pathlib import Path

import pytest

from frida_analykit.compat import FridaCompat
from frida_analykit.config import AppConfig
from frida_analykit.diagnostics import set_verbose
from frida_analykit.server import FridaServerManager, ServerManagerError


class _FakeFrida:
    __version__ = "17.8.2"


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(payload)
        self.headers = headers or {}

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


def _plain_shell(args: list[str], command: str) -> bool:
    return args[-2:] == ["shell", shlex.join(("sh", "-c", command))]


def _su0_shell(args: list[str], command: str) -> bool:
    return args[-2:] == ["shell", shlex.join(("su", "0", "sh", "-c", command))]


def _suroot_shell(args: list[str], command: str) -> bool:
    return args[-2:] == ["shell", shlex.join(("su", "root", "sh", "-c", command))]


def _suc_shell(args: list[str], command: str) -> bool:
    return args[-2:] == ["shell", shlex.join(("su", "-c", command))]


def _auto_root_shell(args: list[str], command: str) -> bool:
    return any(
        matcher(args, command)
        for matcher in (_plain_shell, _su0_shell, _suroot_shell, _suc_shell)
    )


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        interrupt: bool = False,
        running: bool = True,
    ) -> None:
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._interrupt = interrupt
        self._running = running

    def wait(self, timeout=None):
        if timeout is not None and self._running:
            raise subprocess.TimeoutExpired(cmd="fake-adb-shell", timeout=timeout)
        if self._interrupt and timeout is None:
            raise KeyboardInterrupt
        return self._returncode

    def communicate(self, timeout=None):
        return self._stdout, self._stderr

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


def test_detect_device_abi_maps_android_properties(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)
    adb_calls: list[list[str]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
        if _plain_shell(args, "getprop ro.product.cpu.abilist64"):
            return _completed(args, stdout="arm64-v8a,armeabi-v7a\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    assert manager.detect_device_abi(config) == ("arm64-v8a", "android-arm64")
    assert adb_calls[0][:3] == ["adb", "-s", "emulator-5554"]


def test_detect_device_abi_maps_system_product_properties(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
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
        if _plain_shell(args, "cat /proc/cpuinfo"):
            return _completed(args, stdout="Processor\t: AArch64 Processor rev 13\n")
        return _completed(args)

    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=fake_run,
        cache_dir=tmp_path / "cache",
    )

    assert manager.detect_device_abi(config) == ("arm64-v8a", "android-arm64")


def test_boot_remote_server_forwards_port_and_starts_foreground_process(tmp_path: Path) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    adb_calls: list[list[str]] = []
    popen_calls: list[list[str]] = []

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
        adb_calls.append(args)
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

    assert _plain_shell(adb_calls[0], "pidof /data/local/tmp/frida-server")
    assert ["adb", "-s", "emulator-5554", "forward", "tcp:27042", "tcp:27042"] in adb_calls
    assert any(_plain_shell(args, "/data/local/tmp/frida-server --version") for args in adb_calls)
    assert len(popen_calls) == 1
    assert popen_calls[0][:4] == ["adb", "-s", "emulator-5554", "shell"]
    assert popen_calls[0][-1].startswith("sh -c ")
    assert "trap cleanup HUP INT TERM EXIT" in popen_calls[0][-1]
    assert "/data/local/tmp/frida-server -l 0.0.0.0:27042" in popen_calls[0][-1]
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
        if args[:4] == ["adb", "-s", "emulator-5554", "shell"] and args[-1].startswith("su 0 sh -c "):
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
    assert popen_calls[0][:4] == ["adb", "-s", "emulator-5554", "shell"]
    assert popen_calls[0][-1].startswith("su 0 sh -c ")


def test_boot_remote_server_rejects_existing_process_without_force_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _remote_config(tmp_path, version="17.8.1")
    manager = FridaServerManager(
        compat=FridaCompat(_FakeFrida()),
        subprocess_run=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("adb should not be called")),
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


def test_inspect_remote_server_reports_existing_version(tmp_path: Path) -> None:
    config = _remote_config(tmp_path)

    def fake_run(args: list[str], *, check: bool, capture_output: bool, text: bool):
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
