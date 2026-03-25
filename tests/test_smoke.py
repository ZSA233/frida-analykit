import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


def _local_attach_supported(repo_root: Path, env: dict[str, str]) -> bool:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import subprocess
                import sys
                import frida

                target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
                try:
                    session = frida.get_local_device().attach(target.pid)
                    session.detach()
                finally:
                    target.terminate()
                    target.wait(timeout=10)
                """
            ),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


@pytest.mark.smoke
def test_attach_smoke_with_local_device(tmp_path: Path) -> None:
    if os.environ.get("FRIDA_ANALYKIT_ENABLE_SMOKE") != "1":
        pytest.skip("set FRIDA_ANALYKIT_ENABLE_SMOKE=1 to run smoke checks")

    repo_root = Path(__file__).resolve().parents[1]
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

    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
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
        assert "frida-analykit" in result.stdout
    finally:
        target.terminate()
        target.wait(timeout=10)
