from pathlib import Path, PureWindowsPath

from frida_analykit.config import AppConfig, DEFAULT_SCRIPT_REPL_GLOBALS, _serialize_config_value


def test_config_paths_are_resolved_relative_to_source(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
app = "com.example.demo"
jsfile = "./dist/_agent.js"

[server]
host = "127.0.0.1:27042"
version = "17.8.2"

[agent]
datadir = "./data"
stdout = "./logs/stdout.log"
stderr = "./logs/stderr.log"

[script.rpc]
batch_max_bytes = 1234

[script.dextools]
output_dir = "./dextools"

[script.elftools]
output_dir = "./elftools"

[script.nettools]
output_dir = "./ssl"
""".strip(),
        encoding="utf-8",
    )

    config = AppConfig.from_file(config_path)

    assert config.app == "com.example.demo"
    assert config.jsfile == (tmp_path / "dist" / "_agent.js").resolve()
    assert config.server.version == "17.8.2"
    assert config.agent.datadir == (tmp_path / "data").resolve()
    assert config.agent.stdout == (tmp_path / "logs" / "stdout.log").resolve()
    assert config.agent.stderr == (tmp_path / "logs" / "stderr.log").resolve()
    assert config.script.dextools.output_dir == (tmp_path / "dextools").resolve()
    assert config.script.elftools.output_dir == (tmp_path / "elftools").resolve()
    assert config.script.rpc.batch_max_bytes == 1234
    assert config.script.nettools.output_dir == (tmp_path / "ssl").resolve()
    assert config.script.repl.globals == list(DEFAULT_SCRIPT_REPL_GLOBALS)


def test_config_accepts_custom_repl_globals(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
app = "com.example.demo"
jsfile = "./dist/_agent.js"

[server]
host = "127.0.0.1:27042"

[script.repl]
globals = ["Process", "Java"]
""".strip(),
        encoding="utf-8",
    )

    config = AppConfig.from_file(config_path)

    assert config.script.repl.globals == ["Process", "Java"]
    assert config.script.rpc.batch_max_bytes == 8 * 1024 * 1024
    assert config.script.elftools.output_dir is None


def test_config_yaml_compat_accepts_legacy_servername(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
jsfile: ./dist/_agent.js
server:
  host: local
  servername: /data/local/tmp/frida-server
""".strip(),
        encoding="utf-8",
    )

    config = AppConfig.from_file(config_path)

    assert config.server.path == "/data/local/tmp/frida-server"
    assert config.server.servername == "/data/local/tmp/frida-server"


def test_config_serializer_normalizes_windows_paths_to_forward_slashes() -> None:
    payload = {
        "agent": {
            "stdout": PureWindowsPath(r"logs\outerr.log"),
            "stderr": PureWindowsPath(r"logs\outerr.log"),
        },
        "script": {
            "dextools": {"output_dir": PureWindowsPath(r"data\dextools")},
        },
    }

    serialized = _serialize_config_value(payload)

    assert serialized["agent"]["stdout"] == "logs/outerr.log"
    assert serialized["agent"]["stderr"] == "logs/outerr.log"
    assert serialized["script"]["dextools"]["output_dir"] == "data/dextools"
