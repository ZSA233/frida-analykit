from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
from frida_analykit.dev_env import DevEnvManager
from frida_analykit.scaffold import generate_dev_workspace

try:  # pragma: no cover - Windows fallback is not exercised in CI
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX only
    fcntl = None


DEFAULT_REMOTE_HOST = "127.0.0.1:27042"
DEFAULT_REMOTE_SERVERNAME = "/data/local/tmp/frida-server"
DEFAULT_DEVICE_FRIDA_VERSION = "16.6.6"
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
    def __init__(
        self,
        repo_root: Path,
        env: dict[str, str],
        serial: str | None,
        *,
        python_executable: Path,
        frida_version: str,
    ) -> None:
        self.repo_root = repo_root
        self.env = env
        self.serial = serial
        self.python_executable = python_executable
        self.frida_version = frida_version

    def _write_workspace_config(
        self,
        config_path: Path,
        *,
        app: str | None,
        jsfile: str | Path,
        log_path: Path,
    ) -> None:
        lines = [
            f"app: {app or ''}",
            f"jsfile: {jsfile}",
            "server:",
            f"  host: {DEFAULT_REMOTE_HOST}",
            f"  servername: {DEFAULT_REMOTE_SERVERNAME}",
            f"  version: {self.frida_version}",
        ]
        if self.serial:
            lines.append(f"  device: {self.serial}")
        lines.extend(
            [
                "agent:",
                f"  stdout: {log_path}",
                f"  stderr: {log_path}",
                "script:",
                "  nettools: {}",
            ]
        )
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

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
        return self.run_cli_with_env(args, timeout=timeout)

    def run_cli_with_env(
        self,
        args: list[str],
        *,
        timeout: int = 120,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [str(self.python_executable), "-m", "frida_analykit", *args],
            cwd=self.repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def _resolve_launcher_component(self, package: str, *, timeout: int = 30) -> str | None:
        result = self.adb_run(
            ["shell", "cmd", "package", "resolve-activity", "--brief", package],
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        for line in reversed(result.stdout.splitlines()):
            value = line.strip()
            if "/" in value:
                return value
        return None

    def launch_app(self, package: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        launch = self.adb_run(
            ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
            timeout=timeout,
        )
        if launch.returncode == 0:
            return launch

        launcher_component = self._resolve_launcher_component(package, timeout=timeout)
        if launcher_component is None:
            return launch

        # Some devices sporadically reject `monkey` with a transient window-manager error even though
        # the launcher activity is resolvable. Fall back to `am start` so device suites stay deterministic.
        fallback = self.adb_run(
            ["shell", "am", "start", "-W", "-n", launcher_component],
            timeout=timeout,
        )
        if fallback.returncode == 0:
            return fallback
        return launch

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
        probe_names = [DEFAULT_REMOTE_SERVERNAME]
        server_basename = Path(DEFAULT_REMOTE_SERVERNAME).name
        if server_basename != DEFAULT_REMOTE_SERVERNAME:
            # Android `pidof` often matches the process basename even when it was launched by an absolute path.
            probe_names.append(server_basename)
        command_templates = [
            lambda target: ["shell", shlex.join(("sh", "-c", f"pidof {target}"))],
            lambda target: ["shell", shlex.join(("su", "0", "sh", "-c", f"pidof {target}"))],
            lambda target: ["shell", shlex.join(("su", "root", "sh", "-c", f"pidof {target}"))],
            lambda target: ["shell", shlex.join(("su", "-c", f"pidof {target}"))],
        ]
        for probe_name in probe_names:
            for make_command in command_templates:
                result = self.adb_run(make_command(probe_name), timeout=timeout)
                if result.returncode != 0:
                    continue
                output = result.stdout.strip()
                if not output:
                    continue
                token = output.split()[0]
                return int(token) if token.isdigit() else None
        return None

    def wait_for_remote_server_pid(self, *, timeout: int = 30) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pid = self.pidof_remote_server(timeout=5)
            if pid is not None:
                return pid
            time.sleep(1)
        raise TimeoutError(f"timed out waiting for `{DEFAULT_REMOTE_SERVERNAME}` to appear on the device")

    def wait_until_attachable(self, pid: int, *, host: str = DEFAULT_REMOTE_HOST, timeout: int = 30) -> None:
        deadline = time.monotonic() + timeout
        last_error: str | None = None
        while time.monotonic() < deadline:
            attach_error = self._probe_attachable_pid(pid, host=host, timeout=10)
            if attach_error is None:
                return
            last_error = attach_error
            time.sleep(1)
        pytest.fail(f"timed out waiting to attach to pid {pid}: {last_error}")

    def find_attachable_app_pid(
        self,
        package: str,
        *,
        host: str = DEFAULT_REMOTE_HOST,
        timeout: int = 30,
    ) -> tuple[int | None, str | None]:
        existing_pid = self.pidof_app(package, timeout=5)
        if existing_pid is not None:
            attach_error = self._probe_attachable_pid(existing_pid, host=host, timeout=10)
            if attach_error is None:
                return existing_pid, None

        deadline = time.monotonic() + timeout
        last_error: str | None = None
        next_launch_time = time.monotonic()
        while time.monotonic() < deadline:
            pid = self.pidof_app(package, timeout=5)
            if pid is None:
                now = time.monotonic()
                if now >= next_launch_time:
                    launch = self.launch_app(package, timeout=30)
                    if launch.returncode != 0:
                        last_error = launch.stderr.strip() or launch.stdout.strip() or "failed to launch app"
                    next_launch_time = now + 2
                time.sleep(1)
                continue
            attach_error = self._probe_attachable_pid(pid, host=host, timeout=10)
            if attach_error is None:
                return pid, None
            last_error = attach_error
            time.sleep(1)
        return None, last_error or "attach probe timed out"

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
        self._write_workspace_config(
            config_path,
            app=app,
            jsfile=agent_path,
            log_path=log_path,
        )
        return DeviceWorkspace(
            root=tmp_path,
            config_path=config_path,
            agent_path=agent_path,
            log_path=log_path,
        )

    def pack_local_agent_runtime(self, tmp_path: Path, *, timeout: int = 300) -> Path:
        return self.pack_local_package(
            tmp_path,
            self.repo_root / "packages" / "frida-analykit-agent",
            timeout=timeout,
        )

    def pack_local_package(
        self,
        tmp_path: Path,
        package_dir: Path,
        *,
        timeout: int = 300,
    ) -> Path:
        if shutil.which("npm") is None:
            pytest.skip("npm is required to pack the local npm package")

        env = dict(self.env)
        npm_cache_dir = tmp_path / ".npm-cache"
        npm_cache_dir.mkdir(parents=True, exist_ok=True)
        # Use a workspace-local npm cache so device tests do not depend on the host user's global cache state.
        env["npm_config_cache"] = str(npm_cache_dir)

        result = subprocess.run(
            ["npm", "pack", str(package_dir)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if result.returncode != 0:
            pytest.fail(
                f"failed to pack local npm package `{package_dir}`\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

        package_name = result.stdout.strip().splitlines()[-1]
        tarball = tmp_path / package_name
        if not tarball.is_file():
            pytest.fail(f"`npm pack` reported `{package_name}` but the tarball was not found at `{tarball}`")
        return tarball

    def create_ts_workspace_with_local_runtime(
        self,
        tmp_path: Path,
        *,
        app: str | None,
        agent_package_spec: str,
        entry_source: str = 'import "@zsa233/frida-analykit-agent/rpc"\n',
        extra_dependencies: dict[str, str] | None = None,
    ) -> DeviceWorkspace:
        generate_dev_workspace(tmp_path, agent_package_spec=agent_package_spec)
        package_path = tmp_path / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        if extra_dependencies:
            dependencies = package.setdefault("dependencies", {})
            dependencies.update(extra_dependencies)
        package["overrides"] = {
            # Device workspaces install the packed runtime tarball, so pin its transitive Java bridge
            # to the repo-local copy instead of hitting the registry from each temporary workspace.
            "frida-java-bridge": f"file:{self.repo_root / 'node_modules' / 'frida-java-bridge'}",
        }
        package["devDependencies"] = {
            "@types/frida-gum": f"file:{self.repo_root / 'node_modules' / '@types' / 'frida-gum'}",
            "typescript": f"file:{self.repo_root / 'node_modules' / 'typescript'}",
        }
        package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        tsconfig_path = tmp_path / "tsconfig.json"
        tsconfig = json.loads(tsconfig_path.read_text(encoding="utf-8"))
        compiler_options = tsconfig.setdefault("compilerOptions", {})
        compiler_options["types"] = ["frida-gum"]
        tsconfig_path.write_text(json.dumps(tsconfig, indent=2) + "\n", encoding="utf-8")
        (tmp_path / "index.ts").write_text(entry_source, encoding="utf-8")

        agent_path = tmp_path / "_agent.js"
        config_path = tmp_path / "config.yml"
        log_path = tmp_path / "logs" / "outerr.log"
        self._write_workspace_config(
            config_path,
            app=app,
            jsfile="_agent.js",
            log_path=log_path,
        )
        return DeviceWorkspace(
            root=tmp_path,
            config_path=config_path,
            agent_path=agent_path,
            log_path=log_path,
        )

    def build_workspace(self, workspace: DeviceWorkspace, *, install: bool = True, timeout: int = 600) -> None:
        args = [
            "build",
            "--config",
            str(workspace.config_path),
            "--project-dir",
            str(workspace.root),
        ]
        if install:
            args.append("--install")
        npm_cache_dir = workspace.root / ".npm-cache"
        npm_cache_dir.mkdir(parents=True, exist_ok=True)
        result = self.run_cli_with_env(
            args,
            timeout=timeout,
            extra_env={"npm_config_cache": str(npm_cache_dir)},
        )
        if result.returncode != 0:
            pytest.fail(
                "failed to build the device test workspace\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        if not workspace.agent_path.is_file():
            pytest.fail(f"expected built agent bundle at `{workspace.agent_path}`, but it was not created")

    def run_python_probe(
        self,
        code: str,
        *,
        timeout: int = 180,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [str(self.python_executable), "-"],
            cwd=self.repo_root,
            env=env,
            input=textwrap.dedent(code),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def _probe_remote_ready(self, *, host: str = DEFAULT_REMOTE_HOST) -> Exception | None:
        script = f"""
        import frida
        frida.get_device_manager().add_remote_device({host!r})
        """
        result = self.run_python_probe(script, timeout=30)
        if result.returncode == 0:
            return None
        return RuntimeError(result.stderr.strip() or result.stdout.strip() or "remote probe failed")

    def wait_for_remote_ready(self, *, host: str = DEFAULT_REMOTE_HOST, timeout: int = 30) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            last_error = self._probe_remote_ready(host=host)
            if last_error is None:
                return
            time.sleep(1)
        pytest.fail(f"remote frida-server did not become ready on {host}: {last_error}")

    def current_frida_version(self, *, timeout: int = 30) -> str:
        result = subprocess.run(
            [str(self.python_executable), "-c", "import frida; print(frida.__version__)"],
            cwd=self.repo_root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if result.returncode != 0:
            pytest.fail(
                "failed to query the selected Frida version\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        return result.stdout.strip()

    def _probe_attachable_pid(self, pid: int, *, host: str = DEFAULT_REMOTE_HOST, timeout: int = 30) -> str | None:
        script = f"""
        import frida

        device = frida.get_device_manager().add_remote_device({host!r})
        session = device.attach({pid})
        session.detach()
        """
        result = self.run_python_probe(script, timeout=timeout)
        if result.returncode == 0:
            return None
        return result.stderr.strip() or result.stdout.strip() or "attach probe failed"

    def start_boot_process(
        self,
        config_path: Path,
        *,
        force_restart: bool = True,
        timeout: int = 30,
    ) -> subprocess.Popen[str]:
        command = [str(self.python_executable), "-m", "frida_analykit", "server", "boot", "--config", str(config_path)]
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


def _requested_device_frida_version() -> str:
    return os.environ.get("FRIDA_ANALYKIT_DEVICE_FRIDA_VERSION", DEFAULT_DEVICE_FRIDA_VERSION)


def _probe_python_frida_version(python_executable: Path, env: dict[str, str], *, cwd: Path) -> str | None:
    result = subprocess.run(
        [str(python_executable), "-c", "import frida; print(frida.__version__)"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    version = result.stdout.strip()
    return version or None


def _resolve_device_python(repo_root: Path, env: dict[str, str], requested_version: str) -> Path:
    current_python = Path(sys.executable)
    current_version = _probe_python_frida_version(current_python, env, cwd=repo_root)
    if current_version == requested_version:
        return current_python

    managers = [DevEnvManager.for_repo(repo_root), DevEnvManager.for_global()]
    for manager in managers:
        try:
            envs = manager.list_envs()
        except Exception:
            continue
        for managed in envs:
            if managed.frida_version != requested_version:
                continue
            actual_version = _probe_python_frida_version(managed.python_path, env, cwd=repo_root)
            if actual_version == requested_version:
                return managed.python_path

    pytest.skip(
        "device tests require a Python environment with "
        f"frida=={requested_version}. Create one with "
        f"`python scripts/dev_env.py create --frida-version {requested_version}` "
        "or rerun under a matching environment."
    )


@pytest.fixture(scope="session")
def device_helpers() -> DeviceHelpers:
    _require_device_enabled()
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    requested_version = _requested_device_frida_version()
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{src_root}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(src_root)
    )
    env["PYTHONUNBUFFERED"] = "1"
    env["FRIDA_ANALYKIT_DEVICE_FRIDA_VERSION"] = requested_version
    python_executable = _resolve_device_python(repo_root, env, requested_version)
    helpers = DeviceHelpers(
        repo_root,
        env,
        os.environ.get("ANDROID_SERIAL"),
        python_executable=python_executable,
        frida_version=requested_version,
    )
    actual_version = helpers.current_frida_version()
    if actual_version != requested_version:
        pytest.skip(
            f"selected device test python `{python_executable}` reports frida=={actual_version}, "
            f"expected {requested_version}"
        )
    return helpers


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
