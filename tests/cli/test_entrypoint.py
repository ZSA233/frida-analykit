from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import frida
import pytest
from click.testing import CliRunner

from frida_analykit._version import __version__
from frida_analykit.cli import cli
from frida_analykit.config import AppConfig, DEFAULT_SCRIPT_REPL_GLOBALS
from frida_analykit.development import DeviceCompatResult, DeviceCompatSummary
from frida_analykit.env import EnvError, ManagedEnv
from frida_analykit.scaffold import default_agent_package_spec
from frida_analykit.server import ServerManagerError

from .support import (
    _FakeCompat,
    _FakeCompatWithAttach,
    _config,
    _config_with_logs,
    _doctor_status,
    _remote_config,
    _remote_runtime_config,
    _usb_config,
)


def test_gen_dev_creates_v2_workspace(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["gen", "dev", "--work-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["@zsa233/frida-analykit-agent"] == default_agent_package_spec()
    assert "frida-java-bridge" not in package["dependencies"]
    assert package["scripts"]["build"] == "frida-compile index.ts -o _agent.js -c"
    assert package["scripts"]["watch"] == "frida-compile index.ts -o _agent.js -w"
    assert package["devDependencies"]["typescript"] == "^5.8.3"
    assert not (tmp_path / ".npmrc").exists()
    assert (tmp_path / "README.md").exists()
    assert "frida-analykit build --config config.yml" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "/helper" in (tmp_path / "index.ts").read_text(encoding="utf-8")
    assert "only bundles what your script uses" in (tmp_path / "README.md").read_text(encoding="utf-8")
    generated_config = AppConfig.from_yaml(tmp_path / "config.yml")
    assert generated_config.script.repl.globals == list(DEFAULT_SCRIPT_REPL_GLOBALS)


def test_default_agent_package_spec_maps_python_rc_to_npm_rc() -> None:
    assert default_agent_package_spec("2.0.0rc1") == "2.0.0-rc.1"


def test_cli_version_option_reports_installed_version() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0, result.output
    assert __version__ in result.output
    assert "frida-analykit" in result.output
