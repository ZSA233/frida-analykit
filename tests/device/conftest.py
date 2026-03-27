from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import frida
import pytest

try:  # pragma: no cover - Windows fallback is not exercised in CI
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX only
    fcntl = None


DEFAULT_REMOTE_HOST = "127.0.0.1:27042"
DEFAULT_REMOTE_SERVERNAME = "/data/local/tmp/frida-server"
DEFAULT_AGENT_SOURCE = """
console.log("FRIDA_ANALYKIT_DEVICE_OK");
send({
  type: "PROGRESSING",
  data: {
    tag: "device",
    id: 1,
    step: 0,
    time: Date.now(),
    extra: { intro: "device-ok" },
    error: null
  }
});
"""


@dataclass(frozen=True)
class DeviceWorkspace:
    root: Path
    config_path: Path
    agent_path: Path
    log_path: Path


class DeviceTestLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a+", encoding="utf-8")
        if fcntl is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def release(self) -> None:
        if self._handle is None:
            return
        if fcntl is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


class DeviceHelpers:
    def __init__(self, repo_root: Path, env: dict[str, str], serial: str | None) -> None:
        self.repo_root = repo_root
        self.env = env
        self.serial = serial

    def adb_run(self, args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        command = ["adb"]
        if self.serial:
            command.extend(["-s", self.serial])
        command.extend(args)
        return subprocess.run(
            command,
            cwd=self.repo_root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def run_cli(self, args: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "frida_analykit", *args],
            cwd=self.repo_root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def launch_app(self, package: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return self.adb_run(
            ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
            timeout=timeout,
        )

    def force_stop_app(self, package: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return self.adb_run(["shell", "am", "force-stop", package], timeout=timeout)

    def pidof_app(self, package: str, *, timeout: int = 30) -> int | None:
        result = self.adb_run(["shell", "pidof", package], timeout=timeout)
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        if not output:
            return None
        token = output.split()[0]
        return int(token) if token.isdigit() else None

    def wait_for_app_pid(self, package: str, *, timeout: int = 30) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pid = self.pidof_app(package, timeout=5)
            if pid is not None:
                return pid
            time.sleep(1)
        pytest.fail(f"timed out waiting for `{package}` to start")

    def pidof_remote_server(self, *, timeout: int = 30) -> int | None:
        result = self.adb_run(["shell", "su", "-c", f"pidof {DEFAULT_REMOTE_SERVERNAME}"], timeout=timeout)
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        if not output:
            return None
        token = output.split()[0]
        return int(token) if token.isdigit() else None

    def wait_for_remote_server_pid(self, *, timeout: int = 30) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pid = self.pidof_remote_server(timeout=5)
            if pid is not None:
                return pid
            time.sleep(1)
        pytest.fail(f"timed out waiting for `{DEFAULT_REMOTE_SERVERNAME}` to appear on the device")

    def wait_until_attachable(self, pid: int, *, host: str = DEFAULT_REMOTE_HOST, timeout: int = 30) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                device = frida.get_device_manager().add_remote_device(host)
                session = device.attach(pid)
                session.detach()
                return
            except Exception as exc:  # pragma: no cover - depends on real device state
                last_error = exc
                time.sleep(1)
        pytest.fail(f"timed out waiting to attach to pid {pid}: {last_error}")

    def find_attachable_app_pid(
        self,
        package: str,
        *,
        host: str = DEFAULT_REMOTE_HOST,
        timeout: int = 30,
    ) -> tuple[int | None, str | None]:
        launch = self.launch_app(package, timeout=30)
        if launch.returncode != 0:
            return None, launch.stderr.strip() or launch.stdout.strip() or "failed to launch app"

        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            pid = self.pidof_app(package, timeout=5)
            if pid is None:
                time.sleep(1)
                continue
            try:
                device = frida.get_device_manager().add_remote_device(host)
                session = device.attach(pid)
                session.detach()
                return pid, None
            except Exception as exc:  # pragma: no cover - depends on real device state
                last_error = exc
                time.sleep(1)
        return None, str(last_error) if last_error is not None else "attach probe timed out"

    def create_workspace(
        self,
        tmp_path: Path,
        *,
        app: str | None,
        agent_source: str = DEFAULT_AGENT_SOURCE,
    ) -> DeviceWorkspace:
        agent_path = tmp_path / "_agent.js"
        config_path = tmp_path / "config.yml"
        log_path = tmp_path / "logs" / "outerr.log"
        agent_path.write_text(textwrap.dedent(agent_source).strip() + "\n", encoding="utf-8")

        device_line = f"  device: {self.serial}\n" if self.serial else ""
        app_line = app or ""
        config_path.write_text(
            textwrap.dedent(
                f"""
                app: {app_line}
                jsfile: {agent_path}
                server:
                  host: {DEFAULT_REMOTE_HOST}
                  servername: {DEFAULT_REMOTE_SERVERNAME}
                {device_line}agent:
                  stdout: {log_path}
                  stderr: {log_path}
                script:
                  nettools: {{}}
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return DeviceWorkspace(
            root=tmp_path,
            config_path=config_path,
            agent_path=agent_path,
            log_path=log_path,
        )

    def _probe_remote_ready(self, *, host: str = DEFAULT_REMOTE_HOST) -> Exception | None:
        try:
            frida.get_device_manager().add_remote_device(host)
            return None
        except Exception as exc:  # pragma: no cover - depends on real device state
            return exc

    def wait_for_remote_ready(self, *, host: str = DEFAULT_REMOTE_HOST, timeout: int = 30) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            last_error = self._probe_remote_ready(host=host)
            if last_error is None:
                return
            time.sleep(1)
        pytest.fail(f"remote frida-server did not become ready on {host}: {last_error}")

    def start_boot_process(
        self,
        config_path: Path,
        *,
        force_restart: bool = True,
        timeout: int = 30,
    ) -> subprocess.Popen[str]:
        command = [sys.executable, "-m", "frida_analykit", "server", "boot", "--config", str(config_path)]
        if force_restart:
            command.append("--force-restart")
        process = subprocess.Popen(
            command,
            cwd=self.repo_root,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=5)
                pytest.fail(
                    "server boot exited before the remote endpoint became ready\n"
                    f"stdout:\n{stdout}\n"
                    f"stderr:\n{stderr}"
                )
            last_error = self._probe_remote_ready()
            if last_error is None:
                try:
                    self.wait_for_remote_server_pid(timeout=5)
                    return process
                except Exception:
                    last_error = None
            time.sleep(1)
        stdout = ""
        stderr = ""
        self.stop_boot_process(process, config_path)
        if process.stdout is not None:
            stdout = process.stdout.read()
        if process.stderr is not None:
            stderr = process.stderr.read()
        pytest.fail(
            "timed out waiting for `frida-analykit server boot` to expose the remote device\n"
            f"last connection error: {last_error}\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )

    def stop_boot_process(self, process: subprocess.Popen[str], config_path: Path) -> subprocess.CompletedProcess[str]:
        stop_result = self.run_cli(["server", "stop", "--config", str(config_path)], timeout=60)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        return stop_result

    def wait_for_log_contains(self, path: Path, marker: str, *, timeout: int = 20) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                content = path.read_text(encoding="utf-8", errors="replace")
                if marker in content:
                    return content
            time.sleep(1)
        content = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        pytest.fail(f"`{marker}` was not observed in {path}\ncontent:\n{content}")


def _require_device_enabled() -> None:
    if os.environ.get("FRIDA_ANALYKIT_ENABLE_DEVICE") != "1":
        pytest.skip("set FRIDA_ANALYKIT_ENABLE_DEVICE=1 to run device tests")


@pytest.fixture(scope="session")
def device_helpers() -> DeviceHelpers:
    _require_device_enabled()
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{src_root}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(src_root)
    )
    env["PYTHONUNBUFFERED"] = "1"
    return DeviceHelpers(repo_root, env, os.environ.get("ANDROID_SERIAL"))


@pytest.fixture(scope="session")
def device_admin_workspace(device_helpers: DeviceHelpers, tmp_path_factory: pytest.TempPathFactory) -> DeviceWorkspace:
    return device_helpers.create_workspace(tmp_path_factory.mktemp("device-admin"), app=None)


@pytest.fixture(scope="session", autouse=True)
def device_session_guard(
    device_helpers: DeviceHelpers,
    device_admin_workspace: DeviceWorkspace,
) -> Iterator[None]:
    # Device tests all talk to the same adb-forwarded frida-server endpoint, so
    # they must be serialized across pytest workers and repeated invocations.
    lock = DeviceTestLock(device_helpers.repo_root / ".pytest_cache" / "frida-analykit-device.lock")
    lock.acquire()
    try:
        device_helpers.run_cli(["server", "stop", "--config", str(device_admin_workspace.config_path)], timeout=60)
        yield
    finally:
        device_helpers.run_cli(["server", "stop", "--config", str(device_admin_workspace.config_path)], timeout=60)
        lock.release()


@pytest.fixture(scope="session")
def device_app() -> str:
    _require_device_enabled()
    app = os.environ.get("FRIDA_ANALYKIT_DEVICE_APP")
    if not app:
        pytest.skip("set FRIDA_ANALYKIT_DEVICE_APP=<package> to run device attachment tests")
    return app


@pytest.fixture
def booted_device_workspace(
    device_helpers: DeviceHelpers,
    device_app: str,
    tmp_path: Path,
    device_session_guard,
) -> Iterator[DeviceWorkspace]:
    workspace = device_helpers.create_workspace(tmp_path, app=device_app)
    process = device_helpers.start_boot_process(workspace.config_path, force_restart=True)
    try:
        yield workspace
    finally:
        device_helpers.stop_boot_process(process, workspace.config_path)

