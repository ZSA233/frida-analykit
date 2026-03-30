from pathlib import Path

from frida_analykit.config import AppConfig, DEFAULT_SCRIPT_REPL_GLOBALS


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
  rpc:
    batch_max_bytes: 1234
  dextools:
    dex_dir: ./dextools
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
    assert config.script.dextools.dex_dir == (tmp_path / "dextools").resolve()
    assert config.script.rpc.batch_max_bytes == 1234
    assert config.script.nettools.ssl_log_secret == (tmp_path / "ssl").resolve()
    assert config.script.repl.globals == list(DEFAULT_SCRIPT_REPL_GLOBALS)


def test_config_accepts_custom_repl_globals(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
app: com.example.demo
jsfile: ./dist/_agent.js
server:
  host: 127.0.0.1:27042
script:
  repl:
    globals:
      - Process
      - Java
""".strip(),
        encoding="utf-8",
    )

    config = AppConfig.from_yaml(config_path)

    assert config.script.repl.globals == ["Process", "Java"]
    assert config.script.rpc.batch_max_bytes == 8 * 1024 * 1024
