from pathlib import Path

from frida_analykit.config import AgentConfig
from frida_analykit.logging import build_loggers


def test_file_loggers_do_not_write_ansi_sequences(tmp_path: Path) -> None:
    outerr = tmp_path / "outerr.log"
    loggers = build_loggers(AgentConfig(stdout=outerr, stderr=outerr))

    print("stderr line", file=loggers.stderr)
    loggers.stderr.flush()

    assert "\x1b[" not in outerr.read_text(encoding="utf-8")
