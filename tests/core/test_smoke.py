import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.support.paths import REPO_ROOT

import pytest


def _attachable_target_program(*, sleep_seconds: int) -> str:
    return textwrap.dedent(
        f"""
        import ctypes
        import sys
        import time

        if sys.platform.startswith("linux"):
            try:
                libc = ctypes.CDLL(None, use_errno=True)
                pr_set_ptracer = 0x59616D61
                pr_set_ptracer_any = ctypes.c_ulong(-1).value
                libc.prctl.argtypes = [
                    ctypes.c_int,
                    ctypes.c_ulong,
                    ctypes.c_ulong,
                    ctypes.c_ulong,
                    ctypes.c_ulong,
                ]
                libc.prctl.restype = ctypes.c_int
                libc.prctl(pr_set_ptracer, pr_set_ptracer_any, 0, 0, 0)
            except Exception:
                pass

        time.sleep({sleep_seconds})
        """
    ).strip()


def _sibling_attach_probe_program() -> str:
    return textwrap.dedent(
        """
        import sys
        import time
        import frida

        pid = int(sys.argv[1])
        deadline = time.monotonic() + 5.0
        while True:
            try:
                session = frida.get_local_device().attach(pid)
                session.detach()
                raise SystemExit(0)
            except frida.ProcessNotFoundError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        """
    ).strip()


def _local_attach_supported(repo_root: Path, env: dict[str, str]) -> bool:
    target = subprocess.Popen([sys.executable, "-c", _attachable_target_program(sleep_seconds=5)])
    try:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                _sibling_attach_probe_program(),
                str(target.pid),
            ],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return probe.returncode == 0
    finally:
        target.terminate()
        target.wait(timeout=10)


@pytest.mark.smoke
def test_attach_smoke_with_local_device(tmp_path: Path) -> None:
    if os.environ.get("FRIDA_ANALYKIT_ENABLE_SMOKE") != "1":
        pytest.skip("set FRIDA_ANALYKIT_ENABLE_SMOKE=1 to run smoke checks")

    repo_root = REPO_ROOT
    src_root = repo_root / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(src_root)
    if not _local_attach_supported(repo_root, env):
        pytest.skip("local Frida attachment is not available in this environment")

    agent_path = tmp_path / "_agent.js"
    config_path = tmp_path / "config.yml"
    log_path = tmp_path / "stdout.log"

    agent_path.write_text(
        textwrap.dedent(
            """
            rpc.exports = {
              ping() {
                return "pong";
              }
            };
            send({
              type: "PROGRESSING",
              data: {
                tag: "smoke",
                id: 1,
                step: 0,
                time: Date.now(),
                extra: { intro: "loaded" },
                error: null
              }
            });
            """
        ).strip(),
        encoding="utf-8",
    )
    config_path.write_text(
        textwrap.dedent(
            f"""
            app:
            jsfile: {agent_path}
            server:
              host: local
            agent:
              stdout: {log_path}
              stderr: {log_path}
            script:
              nettools:
                ssl_log_secret: {tmp_path / "ssl"}
            """
        ).strip(),
        encoding="utf-8",
    )

    target = subprocess.Popen([sys.executable, "-c", _attachable_target_program(sleep_seconds=60)])
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "frida_analykit",
                "attach",
                "--config",
                str(config_path),
                "--pid",
                str(target.pid),
                "--detach-on-load",
            ],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "➜  Host:" in result.stdout
        assert "➜  Script:" in result.stdout
        assert "➜  Log Output:" in result.stdout
        assert agent_path.name in result.stdout
        assert log_path.name in result.stdout
    finally:
        target.terminate()
        target.wait(timeout=10)
