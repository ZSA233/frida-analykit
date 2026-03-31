from __future__ import annotations

import shlex
import subprocess

from ..config import AppConfig
from ..diagnostics import format_command, verbose_echo
from .constants import _ROOT_FAILURE_MARKERS, _SU_FAILURE_MARKERS
from .helpers import _adb_prefix, _combined_output, _contains_any_marker
from .models import ServerManagerError, _ShellCommand
from .runtime import PopenProcess, ServerRuntime


class ServerAdbClient:
    def __init__(self, runtime: ServerRuntime) -> None:
        self._runtime = runtime

    def remove_forward(self, config: AppConfig, port: str) -> None:
        self.run_adb(
            config,
            ["forward", "--remove", f"tcp:{port}"],
            capture_output=True,
            check=False,
        )

    def run_adb(
        self,
        config: AppConfig,
        args: list[str],
        *,
        capture_output: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = self._command(config, args)
        verbose_echo(f"running adb command: {format_command(command)}")
        try:
            result = self._runtime.subprocess_run(
                command,
                check=check,
                capture_output=capture_output,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            self.log_process_result(
                command=command,
                returncode=exc.returncode,
                stdout=getattr(exc, "stdout", None),
                stderr=getattr(exc, "stderr", None),
            )
            raise
        self.log_process_result(
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        return result

    def shell(
        self,
        config: AppConfig,
        command: str,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        shell_args = ["shell", self.render_shell_command(self.plain_shell_command(command))]
        verbose_echo(f"remote shell command: {command}")
        return self.run_adb(config, shell_args, capture_output=True, check=check)

    def popen_adb(self, config: AppConfig, args: list[str]) -> tuple[list[str], PopenProcess]:
        effective_args = ["shell", "-T", *args[1:]] if args[:1] == ["shell"] else args
        command = self._command(config, effective_args)
        verbose_echo(f"starting adb process: {format_command(command)}")
        try:
            process = self._runtime.subprocess_popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return command, process
        except OSError as exc:
            raise ServerManagerError(f"failed to start `{format_command(command)}`: {exc}") from exc

    @staticmethod
    def plain_shell_command(command: str) -> _ShellCommand:
        return _ShellCommand(args=("sh", "-c", command), label="plain")

    @staticmethod
    def root_shell_commands(command: str) -> tuple[_ShellCommand, ...]:
        return (
            _ShellCommand(args=("su", "0", "sh", "-c", command), label="su 0"),
            _ShellCommand(args=("su", "root", "sh", "-c", command), label="su root"),
            _ShellCommand(args=("su", "-c", command), label="su -c"),
        )

    def boot_shell_commands(
        self,
        config: AppConfig,
        command: str,
    ) -> tuple[_ShellCommand, ...]:
        root_commands = self.root_shell_commands(command)
        usable_root_commands: list[_ShellCommand] = []

        for probe_command, root_command in zip(self.root_shell_commands("id -u"), root_commands):
            result = self.run_shell_command(config, probe_command, check=False)
            probe_output = (result.stdout or "").strip()
            if result.returncode == 0 and probe_output.splitlines()[:1] == ["0"]:
                usable_root_commands.append(root_command)
                verbose_echo(f"using root shell candidate `{root_command.label}` for server boot")
            elif self.should_retry_su_command(result):
                verbose_echo(f"root shell candidate `{root_command.label}` unavailable for server boot")

        if usable_root_commands:
            return tuple(usable_root_commands)
        verbose_echo("no usable root shell candidate detected for server boot; falling back to plain shell")
        return (self.plain_shell_command(command),)

    @staticmethod
    def render_shell_command(shell_command: _ShellCommand) -> str:
        return shlex.join(shell_command.args)

    @staticmethod
    def should_retry_with_root(result: subprocess.CompletedProcess[str]) -> bool:
        combined = _combined_output(result)
        if result.returncode == 0:
            return False
        return _contains_any_marker(combined, _ROOT_FAILURE_MARKERS)

    @staticmethod
    def should_retry_su_command(result: subprocess.CompletedProcess[str]) -> bool:
        return _contains_any_marker(_combined_output(result), _SU_FAILURE_MARKERS)

    def run_shell_command(
        self,
        config: AppConfig,
        shell_command: _ShellCommand,
        *,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_adb(
            config,
            ["shell", self.render_shell_command(shell_command)],
            capture_output=True,
            check=check,
        )

    def shell_with_auto_root(
        self,
        config: AppConfig,
        command: str,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        verbose_echo(f"remote shell command: {command}")
        plain_command = self.plain_shell_command(command)
        plain_result = self.run_shell_command(config, plain_command, check=False)
        if not self.should_retry_with_root(plain_result):
            if check and plain_result.returncode != 0:
                raise subprocess.CalledProcessError(
                    plain_result.returncode,
                    self._command(config, ["shell", self.render_shell_command(plain_command)]),
                    output=plain_result.stdout,
                    stderr=plain_result.stderr,
                )
            return plain_result

        last_result = plain_result
        for root_command in self.root_shell_commands(command):
            result = self.run_shell_command(config, root_command, check=False)
            last_result = result
            if result.returncode == 0:
                return result
            if not self.should_retry_su_command(result):
                break

        if check:
            raise subprocess.CalledProcessError(
                last_result.returncode,
                self._command(config, ["shell", self.render_shell_command(plain_command)]),
                output=last_result.stdout,
                stderr=last_result.stderr,
            )
        return last_result

    def probe_remote_binary_version(self, config: AppConfig, remote_path: str) -> subprocess.CompletedProcess[str]:
        return self.shell_with_auto_root(
            config,
            f"{shlex.quote(remote_path)} --version",
            check=False,
        )

    @staticmethod
    def log_process_result(
        *,
        command: list[str],
        returncode: int,
        stdout: str | None,
        stderr: str | None,
    ) -> None:
        verbose_echo(f"{format_command(command)} exited with code {returncode}")
        if stdout and stdout.strip():
            verbose_echo(f"stdout from {format_command(command)}:\n{stdout.rstrip()}")
        if stderr and stderr.strip():
            verbose_echo(f"stderr from {format_command(command)}:\n{stderr.rstrip()}")

    @staticmethod
    def terminate_process(process: PopenProcess) -> None:
        try:
            process.terminate()
        except BaseException:
            return
        try:
            process.wait(timeout=5)
        except BaseException:
            try:
                process.kill()
            except BaseException:
                return
            try:
                process.wait(timeout=5)
            except BaseException:
                return

    def _command(self, config: AppConfig, args: list[str]) -> list[str]:
        return [*_adb_prefix(config, adb_executable=self._runtime.adb_executable), *args]
