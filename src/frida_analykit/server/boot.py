from __future__ import annotations

import shlex
import subprocess
import time

from ..config import AppConfig
from ..diagnostics import verbose_echo
from .adb import ServerAdbClient
from .helpers import _extract_version, _tail_text, optional_host_port, require_host_port
from .install import ServerInstaller
from .models import ServerManagerError, _BootExecutionResult
from .runtime import PopenProcess, ServerRuntime


class ServerBootController:
    def __init__(
        self,
        runtime: ServerRuntime,
        adb: ServerAdbClient,
        installer: ServerInstaller,
    ) -> None:
        self._runtime = runtime
        self._adb = adb
        self._installer = installer

    def boot_remote_server(self, config: AppConfig, *, force_restart: bool = False) -> None:
        config = self._installer.resolve_target_config(config, action="server boot")
        port = require_host_port(config.server.host, action="server boot")
        existing_pids = self.list_remote_server_pids(config)
        if existing_pids:
            if not force_restart:
                pid_list = ", ".join(str(pid) for pid in sorted(existing_pids))
                raise ServerManagerError(
                    "remote frida-server already running "
                    f"(pids: {pid_list}); run `frida-analykit server stop --config ...` "
                    "or retry with `frida-analykit server boot --force-restart`"
                )
            verbose_echo(f"force restarting remote frida-server pids: {sorted(existing_pids)}")
            self._kill_remote_pids(config, existing_pids)

        try:
            self._installer.ensure_remote_forward(config, action="server boot")
            before_pids = self.list_remote_server_pids(config)

            version_probe = self._adb.probe_remote_binary_version(config, config.server.path)
            installed_version = _extract_version(
                "\n".join(part for part in (version_probe.stdout, version_probe.stderr) if part)
            )
            if version_probe.returncode != 0:
                raise ServerManagerError(
                    f"failed to execute `{config.server.path} --version` on the target device"
                )
            if installed_version is None:
                verbose_echo(
                    f"unable to parse a frida-server version from `{config.server.path} --version`; continuing with boot"
                )

            launch_command = self._build_boot_command(config.server.path, port)
            execution = self._start_boot_process(config, launch_command)
            command, process = execution.command, execution.process
            if execution.returncode is not None:
                returncode = execution.returncode
                stdout = execution.stdout
                stderr = execution.stderr
            else:
                try:
                    returncode = process.wait()
                    stdout, stderr = self._collect_process_output(process)
                    self._adb.log_process_result(
                        command=command,
                        returncode=returncode,
                        stdout=stdout,
                        stderr=stderr,
                    )
                except KeyboardInterrupt:
                    verbose_echo("keyboard interrupt received while waiting for remote frida-server")
                    self._adb.terminate_process(process)
                    self.cleanup_booted_remote_server(config, before_pids=before_pids)
                    return
                except BaseException:
                    self._adb.terminate_process(process)
                    self.cleanup_booted_remote_server(config, before_pids=before_pids)
                    raise

            if returncode != 0:
                self.cleanup_booted_remote_server(config, before_pids=before_pids)
                raise ServerManagerError(
                    self._format_boot_failure(
                        config,
                        port=port,
                        returncode=returncode,
                        stdout=stdout,
                        stderr=stderr,
                    )
                )
        finally:
            self._adb.remove_forward(config, port)

    def stop_remote_server(self, config: AppConfig) -> set[int]:
        config = self._installer.resolve_target_config(config, action="server stop")
        pids = self.list_remote_server_pids(config)
        if pids:
            self._kill_remote_pids(config, pids)
        port = optional_host_port(config.server.host)
        if port is not None:
            self._adb.remove_forward(config, port)
        return pids

    def list_remote_server_pids(self, config: AppConfig) -> set[int]:
        config = self._installer.resolve_target_config(config, action="remote server pid lookup")
        basename = config.server.path.rsplit("/", 1)[-1]
        identifiers = (config.server.path, basename)

        pidof_candidates = [config.server.path]
        if basename != config.server.path:
            pidof_candidates.append(basename)

        for candidate in pidof_candidates:
            result = self._adb.shell_with_auto_root(
                config,
                f"pidof {shlex.quote(candidate)}",
                check=False,
            )
            pids = self._parse_pid_list(result.stdout)
            if pids:
                verbose_echo(f"resolved remote server pids via pidof `{candidate}`: {sorted(pids)}")
                return pids

        for command in ("ps -A", "ps"):
            result = self._adb.shell_with_auto_root(config, command, check=False)
            pids = self._parse_ps_pid_list(result.stdout, identifiers=identifiers)
            if pids:
                verbose_echo(f"resolved remote server pids via `{command}`: {sorted(pids)}")
                return pids
        return set()

    def cleanup_booted_remote_server(self, config: AppConfig, *, before_pids: set[int]) -> None:
        launched_pids = self._find_new_remote_server_pids(config, before_pids=before_pids)
        if not launched_pids:
            verbose_echo("no newly launched remote frida-server process detected during cleanup")
            return
        verbose_echo(f"cleaning up remote frida-server pids: {sorted(launched_pids)}")
        self._kill_remote_pids(config, launched_pids)

    def _start_boot_process(self, config: AppConfig, command: str) -> _BootExecutionResult:
        attempts = list(self._adb.boot_shell_commands(config, command))
        last_error: OSError | None = None
        for index, shell_command in enumerate(attempts):
            try:
                adb_command, process = self._adb.popen_adb(
                    config,
                    ["shell", self._adb.render_shell_command(shell_command)],
                )
                try:
                    returncode = process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    return _BootExecutionResult(command=adb_command, process=process, root_label=shell_command.label)
                stdout, stderr = self._collect_process_output(process)
                self._adb.log_process_result(
                    command=adb_command,
                    returncode=returncode,
                    stdout=stdout,
                    stderr=stderr,
                )
                completed = subprocess.CompletedProcess(
                    adb_command,
                    returncode,
                    stdout=stdout or "",
                    stderr=stderr or "",
                )
                if returncode == 0 and index < len(attempts) - 1:
                    continue
                if shell_command.label == "plain" and self._adb.should_retry_with_root(completed):
                    continue
                if shell_command.label != "plain" and self._adb.should_retry_su_command(completed):
                    continue
                return _BootExecutionResult(
                    command=adb_command,
                    process=process,
                    root_label=shell_command.label,
                    returncode=returncode,
                    stdout=stdout,
                    stderr=stderr,
                )
            except OSError as exc:
                last_error = exc
                continue
        if last_error is None:
            raise ServerManagerError("failed to start remote shell command")
        raise ServerManagerError(f"failed to start remote shell command: {last_error}") from last_error

    @staticmethod
    def _parse_pid_list(raw: str) -> set[int]:
        pids: set[int] = set()
        for token in raw.split():
            if token.isdigit():
                pids.add(int(token))
        return pids

    @classmethod
    def _parse_ps_pid_list(cls, raw: str, *, identifiers: tuple[str, ...]) -> set[int]:
        pids: set[int] = set()
        for line in raw.splitlines():
            if not any(identifier in line for identifier in identifiers):
                continue
            parts = line.split()
            for token in parts[1:]:
                if token.isdigit():
                    pids.add(int(token))
                    break
        return pids

    def _find_new_remote_server_pids(self, config: AppConfig, *, before_pids: set[int]) -> set[int]:
        deadline = time.monotonic() + 2.0
        latest: set[int] = set()
        while time.monotonic() < deadline:
            latest = self.list_remote_server_pids(config)
            new_pids = latest - before_pids
            if new_pids:
                return new_pids
            time.sleep(0.2)
        return latest - before_pids

    def _kill_remote_pids(self, config: AppConfig, pids: set[int]) -> None:
        remaining = set(pids)
        for pid in sorted(remaining):
            self._adb.shell_with_auto_root(config, f"kill {pid}", check=False)
        after_term = self.list_remote_server_pids(config)
        remaining &= after_term
        if not remaining:
            return
        verbose_echo(f"force killing remote frida-server pids: {sorted(remaining)}")
        for pid in sorted(remaining):
            self._adb.shell_with_auto_root(config, f"kill -9 {pid}", check=False)

    @staticmethod
    def _build_boot_command(server_path: str, port: str) -> str:
        return f"exec {shlex.quote(server_path)} -l 0.0.0.0:{port} 1>/dev/null"

    @staticmethod
    def _collect_process_output(process: PopenProcess) -> tuple[str | None, str | None]:
        try:
            return process.communicate(timeout=1)
        except BaseException:
            stdout = process.stdout.read() if process.stdout is not None else None
            stderr = process.stderr.read() if process.stderr is not None else None
            return stdout, stderr

    def _format_boot_failure(
        self,
        config: AppConfig,
        *,
        port: str,
        returncode: int,
        stdout: str | None,
        stderr: str | None,
    ) -> str:
        message = f"`{config.server.path} -l 0.0.0.0:{port}` exited with code {returncode}"
        stderr_tail = _tail_text(stderr)
        stdout_tail = _tail_text(stdout)
        combined = "\n".join(part for part in (stderr_tail, stdout_tail) if part)
        if combined:
            message = f"{message}\n{combined}"

        if "Address already in use" not in combined:
            return message

        active_pids = self.list_remote_server_pids(config)
        if not active_pids:
            return message
        pid_list = ", ".join(str(pid) for pid in sorted(active_pids))
        return (
            f"{message}\n"
            f"remote frida-server is still running (pids: {pid_list}); "
            "run `frida-analykit server stop --config ...` or retry with "
            "`frida-analykit server boot --force-restart`"
        )
