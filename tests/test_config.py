from pathlib import Path

from frida_analykit.config import AppConfig


def test_config_paths_are_resolved_relative_to_source(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
app: com.example.demo
jsfile: ./dist/_agent.js
server:
  host: 127.0.0.1:27042
  version: 17.8.2
agent:
  datadir: ./data
  stdout: ./logs/stdout.log
  stderr: ./logs/stderr.log
script:
  nettools:
    ssl_log_secret: ./ssl
""".strip(),
        encoding="utf-8",
    )

    config = AppConfig.from_yaml(config_path)

    assert config.app == "com.example.demo"
    assert config.jsfile == (tmp_path / "dist" / "_agent.js").resolve()
    assert config.server.version == "17.8.2"
    assert config.agent.datadir == (tmp_path / "data").resolve()
    assert config.agent.stdout == (tmp_path / "logs" / "stdout.log").resolve()
    assert config.agent.stderr == (tmp_path / "logs" / "stderr.log").resolve()
    assert config.script.nettools.ssl_log_secret == (tmp_path / "ssl").resolve()
