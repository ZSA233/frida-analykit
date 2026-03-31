from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import textwrap
import time
from collections.abc import Callable
from pathlib import Path

from ..config import AppConfig
from ..scaffold import generate_dev_workspace
from ..server import FridaServerManager, ServerManagerError
from .constants import DEFAULT_DEVICE_TEST_APP_ID
from .defaults import (
    DEFAULT_AGENT_SOURCE,
    DEFAULT_REMOTE_HOST,
    DEFAULT_REMOTE_SERVERNAME,
    DEVICE_READY_POLL_INTERVAL,
    DEVICE_READY_TIMEOUT,
)
from .models import AppProbeResult, DeviceAppResolutionError, DeviceWorkspace
from .selection import derive_remote_host, safe_device_serial_token


class DeviceHelpers:
    def __init__(
        self,
        repo_root: Path,
        env: dict[str, str],
        serial: str | None,
        *,
        python_executable: Path,
        frida_version: str,
        remote_host: str | None = None,
        remote_servername: str = DEFAULT_REMOTE_SERVERNAME,
        adb_executable: str = "adb",
    ) -> None:
        self.repo_root = repo_root
        self.env = env
        self.serial = serial
        self.resolved_serial = serial
        self.python_executable = python_executable
        self.frida_version = frida_version
        self.adb_executable = adb_executable
        self.remote_host = remote_host or (derive_remote_host(serial) if serial else DEFAULT_REMOTE_HOST)
        self.remote_servername = remote_servername
        self._installed_packages_cache: frozenset[str] | None = None

    @property
    def lock_path(self) -> Path:
        token = safe_device_serial_token(self.resolved_serial or "default")
        return self.repo_root / ".pytest_cache" / f"frida-analykit-device-{token}.lock"

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
            f"  host: {self.remote_host}",
            f"  servername: {self.remote_servername}",
            f"  version: {self.frida_version}",
        ]
        if self.resolved_serial:
            lines.append(f"  device: {self.resolved_serial}")
        lines.extend(
            [
                "agent:",
                "  datadir: ./data",
                f"  stdout: {log_path}",
                f"  stderr: {log_path}",
                "script:",
                "  dextools:",
                "    output_dir: ./data/dextools",
                "  nettools: {}",
            ]
        )
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def adb_run(self, args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        command = [self.adb_executable]
        if self.resolved_serial:
            command.extend(["-s", self.resolved_serial])
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

    def ensure_matching_server(self, config_path: Path, *, timeout: int = 300) -> None:
        config = AppConfig.from_yaml(config_path)
        manager = FridaServerManager()
        try:
            status = manager.inspect_remote_server(config)
        except ServerManagerError:
            status = None
        if status is not None and status.installed_version == self.frida_version and status.executable:
            return

        install = self.run_cli(
            ["server", "install", "--config", str(config_path), "--version", self.frida_version],
            timeout=timeout,
        )
        if install.returncode != 0:
            raise RuntimeError(
                f"failed to install frida-server {self.frida_version}\n"
                f"stdout:\n{install.stdout}\n"
                f"stderr:\n{install.stderr}"
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

    def list_installed_packages(
        self,
        *,
        timeout: int = 30,
        force_refresh: bool = False,
    ) -> frozenset[str]:
        if self._installed_packages_cache is not None and not force_refresh:
            return self._installed_packages_cache

        for attempt in range(3):
            result = self.adb_run(["shell", "pm", "list", "packages"], timeout=timeout)
            if result.returncode == 0:
                packages = frozenset(
                    line[len("package:") :].strip()
                    for line in result.stdout.splitlines()
                    if line.startswith("package:")
                )
                self._installed_packages_cache = packages
                return packages

            if attempt == 2:
                detail = result.stderr.strip() or result.stdout.strip() or "failed to list packages"
                raise RuntimeError(detail)
            time.sleep(1)

        raise RuntimeError("failed to list packages")

    def package_exists(self, package: str, *, timeout: int = 30) -> bool:
        try:
            return package in self.list_installed_packages(timeout=timeout)
        except RuntimeError:
            pass

        for attempt in range(3):
            result = self.adb_run(["shell", "pm", "path", package], timeout=timeout)
            if result.returncode == 0:
                return any(line.startswith("package:") for line in result.stdout.splitlines())

            # Right after server install/boot on slower devices, adb shell / pm can
            # fail transiently under load. Retry before concluding the package is absent.
            if attempt == 2:
                return False
            time.sleep(1)
        return False

    def launch_app(self, package: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        launcher_component = self._resolve_launcher_component(package, timeout=timeout)
        component_launch: subprocess.CompletedProcess[str] | None = None
        if launcher_component is not None:
            component_launch = self.adb_run(
                ["shell", "am", "start", "-n", launcher_component],
                timeout=timeout,
            )
            if component_launch.returncode == 0:
                return component_launch

        launch = self.adb_run(
            ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
            timeout=timeout,
        )
        if launch.returncode == 0:
            return launch
        return component_launch or launch

    def force_stop_app(self, package: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return self.adb_run(["shell", "am", "force-stop", package], timeout=timeout)

    def wait_for_device_ready(
        self,
        *,
        timeout: int = DEVICE_READY_TIMEOUT,
        package: str | None = None,
    ) -> None:
        deadline = time.monotonic() + timeout
        package_to_probe = package or "android"
        last_error = "device not ready yet"

        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            wait_result = self.adb_run(["wait-for-device"], timeout=min(remaining, 30))
            if wait_result.returncode != 0:
                last_error = wait_result.stderr.strip() or wait_result.stdout.strip() or "adb wait-for-device failed"
                time.sleep(DEVICE_READY_POLL_INTERVAL)
                continue

            boot_result = self.adb_run(["shell", "getprop", "sys.boot_completed"], timeout=min(remaining, 10))
            if boot_result.returncode != 0 or boot_result.stdout.strip() != "1":
                alt_boot = self.adb_run(["shell", "getprop", "dev.bootcomplete"], timeout=min(remaining, 10))
                if alt_boot.returncode != 0 or alt_boot.stdout.strip() != "1":
                    last_error = (
                        boot_result.stderr.strip()
                        or boot_result.stdout.strip()
                        or alt_boot.stderr.strip()
                        or alt_boot.stdout.strip()
                        or "system boot not completed"
                    )
                    time.sleep(DEVICE_READY_POLL_INTERVAL)
                    continue

            package_result = self.adb_run(["shell", "pm", "path", package_to_probe], timeout=min(remaining, 15))
            if package_result.returncode == 0 and any(
                line.startswith("package:") for line in package_result.stdout.splitlines()
            ):
                return

            last_error = (
                package_result.stderr.strip()
                or package_result.stdout.strip()
                or f"package manager not ready for `{package_to_probe}`"
            )
            time.sleep(DEVICE_READY_POLL_INTERVAL)

        raise RuntimeError(f"timed out waiting for Android device readiness: {last_error}")

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
        raise RuntimeError(f"timed out waiting for `{package}` to start")

    def _probe_launchable_device_app(
        self,
        package: str,
        *,
        timeout: int = 30,
        attempt_reporter: Callable[[str], None] | None = None,
    ) -> AppProbeResult:
        def wait_for_stable_pid() -> AppProbeResult:
            self.wait_for_app_pid(package, timeout=timeout)

            # Some vendor ROMs return a non-zero status from monkey/am even though the
            # process actually starts. A live PID is the signal we care about here.
            time.sleep(2)
            stable_pid = self.pidof_app(package, timeout=5)
            if stable_pid is None:
                return AppProbeResult(ok=False, package=package, reason="pid-disappeared-after-launch")
            if attempt_reporter is not None:
                attempt_reporter(f"candidate `{package}` reached stable pid {stable_pid}")
            return AppProbeResult(ok=True, package=package)

        if not self.package_exists(package, timeout=timeout):
            return AppProbeResult(ok=False, package=package, reason="not-installed")

        if attempt_reporter is not None:
            attempt_reporter(f"candidate `{package}` installed; launching")
        self.force_stop_app(package, timeout=timeout)
        launch = self.launch_app(package, timeout=timeout)
        try:
            if attempt_reporter is not None:
                attempt_reporter(f"candidate `{package}` launched; waiting for pid")
            return wait_for_stable_pid()
        except RuntimeError as exc:
            if launch.returncode != 0:
                detail = launch.stderr.strip() or launch.stdout.strip() or "failed to launch app"
                return AppProbeResult(ok=False, package=package, reason=f"launch-failed: {detail}")

            # Some devices report a successful monkey launch even though no process
            # was created. Retry via the resolved launcher activity before giving up.
            launcher_component = self._resolve_launcher_component(package, timeout=timeout)
            if launcher_component is None:
                return AppProbeResult(ok=False, package=package, reason=str(exc))

            if attempt_reporter is not None:
                attempt_reporter(
                    f"candidate `{package}` monkey returned success without pid; retrying `{launcher_component}`"
                )
            fallback = self.adb_run(
                ["shell", "am", "start", "-W", "-n", launcher_component],
                timeout=timeout,
            )
            if fallback.returncode != 0:
                detail = fallback.stderr.strip() or fallback.stdout.strip() or "component launch failed"
                return AppProbeResult(ok=False, package=package, reason=f"launch-failed: {detail}")
            try:
                if attempt_reporter is not None:
                    attempt_reporter(f"candidate `{package}` component launch issued; waiting for pid")
                return wait_for_stable_pid()
            except RuntimeError:
                return AppProbeResult(ok=False, package=package, reason=str(exc))

    def resolve_device_app(
        self,
        *,
        explicit_app: str | None = None,
        timeout: int = 30,
        require_attach: bool = False,
        attempt_reporter: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        package = explicit_app or DEFAULT_DEVICE_TEST_APP_ID
        source = "configured" if explicit_app else "default-test-app"
        source_label = "configured app" if explicit_app else "default device test app"
        max_attempts = 3
        last_error: DeviceAppResolutionError | None = None

        self.wait_for_device_ready(timeout=max(timeout, 60), package=package)
        for attempt in range(1, max_attempts + 1):
            if attempt_reporter is not None:
                attempt_reporter(
                    f"probing {source_label} `{package}`"
                    if attempt == 1
                    else f"re-probing {source_label} `{package}` (attempt {attempt}/{max_attempts})"
                )
            result = self._probe_launchable_device_app(
                package,
                timeout=timeout,
                attempt_reporter=attempt_reporter,
            )
            if not result.ok:
                if attempt_reporter is not None:
                    attempt_reporter(f"{source_label} `{package}` rejected: {result.reason}")
                if result.reason == "not-installed":
                    if explicit_app:
                        raise DeviceAppResolutionError(
                            f"configured device app `{package}` was not found on the device; "
                            "install it first or choose another package explicitly."
                        )
                    serial_hint = self.resolved_serial or "<serial>"
                    raise DeviceAppResolutionError(
                        f"default device test app `{package}` is not installed on the device; "
                        f"run `make device-test-app-install ANDROID_SERIAL={serial_hint}` "
                        "or set FRIDA_ANALYKIT_DEVICE_APP=<package> / pass --app <package>."
                    )
                last_error = DeviceAppResolutionError(
                    f"{source_label} `{package}` is not usable for device tests: {result.reason}"
                )
            else:
                if require_attach:
                    attach_pid, attach_error = self.find_attachable_app_pid(
                        package,
                        host=self.remote_host,
                        timeout=timeout,
                    )
                    if attach_pid is None:
                        if attempt_reporter is not None:
                            attempt_reporter(f"{source_label} `{package}` attach probe failed: {attach_error}")
                        last_error = DeviceAppResolutionError(
                            f"{source_label} `{package}` is not attachable for device tests: {attach_error}"
                        )
                    else:
                        if attempt_reporter is not None:
                            attempt_reporter(f"selected {source} `{package}`")
                        return package, source
                else:
                    if attempt_reporter is not None:
                        attempt_reporter(f"selected {source} `{package}`")
                    return package, source

            if attempt < max_attempts:
                self.wait_for_device_ready(timeout=max(timeout, 60), package=package)
                time.sleep(2)

        raise last_error or DeviceAppResolutionError(
            f"{source_label} `{package}` is not usable for device tests"
        )

    def pidof_remote_server(self, *, timeout: int = 30) -> int | None:
        probe_names = [self.remote_servername]
        server_basename = Path(self.remote_servername).name
        if server_basename != self.remote_servername:
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
        raise TimeoutError(f"timed out waiting for `{self.remote_servername}` to appear on the device")

    def wait_until_attachable(self, pid: int, *, host: str | None = None, timeout: int = 30) -> None:
        deadline = time.monotonic() + timeout
        last_error: str | None = None
        remote_host = host or self.remote_host
        while time.monotonic() < deadline:
            attach_error = self._probe_attachable_pid(pid, host=remote_host, timeout=10)
            if attach_error is None:
                return
            last_error = attach_error
            time.sleep(1)
        raise RuntimeError(f"timed out waiting to attach to pid {pid}: {last_error}")

    def find_attachable_app_pid(
        self,
        package: str,
        *,
        host: str | None = None,
        timeout: int = 30,
    ) -> tuple[int | None, str | None]:
        remote_host = host or self.remote_host
        existing_pid = self.pidof_app(package, timeout=5)
        if existing_pid is not None:
            attach_error = self._probe_attachable_pid(existing_pid, host=remote_host, timeout=10)
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
            attach_error = self._probe_attachable_pid(pid, host=remote_host, timeout=10)
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
        tmp_path.mkdir(parents=True, exist_ok=True)
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
            raise RuntimeError("npm is required to pack the local npm package")

        env = dict(self.env)
        npm_cache_dir = tmp_path / ".npm-cache"
        npm_cache_dir.mkdir(parents=True, exist_ok=True)
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
            raise RuntimeError(
                f"failed to pack local npm package `{package_dir}`\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

        package_name = result.stdout.strip().splitlines()[-1]
        tarball = tmp_path / package_name
        if not tarball.is_file():
            raise RuntimeError(f"`npm pack` reported `{package_name}` but the tarball was not found at `{tarball}`")
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
            "frida-java-bridge": f"file:{self.repo_root / 'node_modules' / 'frida-java-bridge'}",
        }
        dev_dependencies = package.setdefault("devDependencies", {})
        dev_dependencies.update(
            {
            "@types/frida-gum": f"file:{self.repo_root / 'node_modules' / '@types' / 'frida-gum'}",
            "typescript": f"file:{self.repo_root / 'node_modules' / 'typescript'}",
            }
        )
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
            raise RuntimeError(
                "failed to build the device test workspace\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        if not workspace.agent_path.is_file():
            raise RuntimeError(f"expected built agent bundle at `{workspace.agent_path}`, but it was not created")

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

    def _probe_remote_ready(self, *, host: str | None = None) -> Exception | None:
        remote_host = host or self.remote_host
        script = f"""
        import frida

        device = frida.get_device_manager().add_remote_device({remote_host!r})
        # Keep the readiness probe lighter than enumerate_processes(): older
        # devices can stall while synchronizing the Android agent even though
        # the remote frida-server is already alive and ready for the next step.
        device.query_system_parameters()
        """
        result = self.run_python_probe(script, timeout=30)
        if result.returncode == 0:
            return None
        return RuntimeError(result.stderr.strip() or result.stdout.strip() or "remote probe failed")

    def wait_for_remote_ready(self, *, host: str | None = None, timeout: int = 30) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        remote_host = host or self.remote_host
        while time.monotonic() < deadline:
            last_error = self._probe_remote_ready(host=remote_host)
            if last_error is None:
                return
            time.sleep(1)
        raise RuntimeError(f"remote frida-server did not become ready on {remote_host}: {last_error}")

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
            raise RuntimeError(
                "failed to query the selected Frida version\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        return result.stdout.strip()

    def _probe_attachable_pid(self, pid: int, *, host: str | None = None, timeout: int = 30) -> str | None:
        remote_host = host or self.remote_host
        script = f"""
        import frida

        device = frida.get_device_manager().add_remote_device({remote_host!r})
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
            returncode = process.poll()
            if returncode is not None:
                stdout, stderr = process.communicate(timeout=5)
                if returncode == 0:
                    # Older devices sometimes detach the local boot command
                    # before the forwarded endpoint settles. Accept a clean
                    # exit when the remote server becomes reachable shortly
                    # afterwards.
                    last_error = self._wait_for_remote_boot_stable(
                        process,
                        allow_exited_process=True,
                        grace_timeout=5.0,
                    )
                    if last_error is None:
                        return process
                raise RuntimeError(
                    "server boot exited before the remote endpoint became ready\n"
                    f"stdout:\n{stdout}\n"
                    f"stderr:\n{stderr}"
                )
            last_error = self._wait_for_remote_boot_stable(process)
            if last_error is None:
                return process
            time.sleep(1)
        self.stop_boot_process(process, config_path)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
        raise RuntimeError(
            "timed out waiting for `frida-analykit server boot` to expose the remote device\n"
            f"last connection error: {last_error}\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )

    def _wait_for_remote_boot_stable(
        self,
        process: subprocess.Popen[str],
        *,
        allow_exited_process: bool = False,
        grace_timeout: float = 0.0,
    ) -> Exception | None:
        deadline = time.monotonic() + max(0.0, grace_timeout)
        last_error: Exception | None = None
        while True:
            if not allow_exited_process and process.poll() is not None:
                return RuntimeError("server boot exited during stabilization")
            ready_error = self._probe_remote_ready()
            if ready_error is None:
                try:
                    self.wait_for_remote_server_pid(timeout=5)
                except Exception as exc:
                    ready_error = exc
                else:
                    # Some devices briefly expose the forwarded port before the
                    # long-running server boot child fully settles. A short
                    # re-probe avoids handing a dead endpoint to the next step.
                    stable_error: Exception | None = None
                    for _ in range(2):
                        time.sleep(0.5)
                        if not allow_exited_process and process.poll() is not None:
                            return RuntimeError("server boot exited during stabilization")
                        stable_error = self._probe_remote_ready()
                        if stable_error is not None:
                            break
                    else:
                        return None
                    ready_error = stable_error
            last_error = ready_error
            if time.monotonic() >= deadline:
                return last_error
            time.sleep(0.5)

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
        raise RuntimeError(f"`{marker}` was not observed in {path}\ncontent:\n{content}")
