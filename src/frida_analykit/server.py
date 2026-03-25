from __future__ import annotations

import subprocess
import sys

import pexpect

from .config import AppConfig


def boot_server(config: AppConfig) -> None:
    if not config.server.is_remote:
        raise ValueError("server boot only supports remote adb-backed targets")

    device_arg = f"-s {config.server.device}" if config.server.device else ""
    _, port = config.server.host.rsplit(":", 1)
    subprocess.run(
        f"adb {device_arg} forward tcp:{port} tcp:{port}",
        shell=True,
        check=True,
    )

    adb_shell = pexpect.spawn(f"adb {device_arg} shell", logfile=sys.stdout.buffer)
    adb_shell.expect(r".*:\s*\/\s*[$#]")
    adb_shell.sendline("su")
    adb_shell.expect(r".*:\s*\/\s*[$#]")
    adb_shell.sendline(f"{config.server.servername} --version")
    adb_shell.expect(r".*:\s*\/\s*[$#]")
    adb_shell.sendline(f"{config.server.servername} -l 0.0.0.0:{port}")
    adb_shell.expect([pexpect.EOF, "Unable to start", r".*:\s*\/\s*[$#]"], timeout=None)
