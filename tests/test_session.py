import io
from datetime import datetime
from pathlib import Path

from frida_analykit._version import __version__
from frida_analykit.config import AppConfig
from frida_analykit.logging import LoggerBundle
from frida_analykit.session import SessionWrapper, render_session_banner, try_inject_environ


def _config(
    tmp_path: Path,
    *,
    jsfile: str = "_agent.js",
    stdout: str | None = None,
    stderr: str | None = None,
) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": None,
            "jsfile": jsfile,
            "server": {"host": "local"},
            "agent": {"stdout": stdout, "stderr": stderr},
            "script": {"nettools": {}},
        }
    ).resolve_paths(tmp_path, source_path=tmp_path / "config.yml")


class _FakeScript:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.log_handler = None

    def on(self, signal: str, callback) -> None:
        self.handlers[signal] = callback

    def set_log_handler(self, handler) -> None:
        self.log_handler = handler


class _FakeSession:
    def __init__(self) -> None:
        self.script = _FakeScript()
        self.last_source: str | None = None

    def create_script(self, source: str, name=None, snapshot=None, runtime=None):
        self.last_source = source
        return self.script


def test_try_inject_environ_wraps_module_import_with_bootstrap_guard() -> None:
    script_src = "16 /index.js\n✄\nconsole.log('demo')\n"

    injected = try_inject_environ(script_src, {"OnRPC": True})

    assert 'globalThis.__FRIDA_ANALYKIT_CONFIG__' in injected
    assert 'await import("/index.js");' in injected
    assert "catch (error)" in injected
    assert 'console.error(`[frida-analykit/bootstrap] ${description}`);' in injected


def test_session_wrapper_reuses_existing_logger_bundle(monkeypatch, tmp_path: Path) -> None:
    shared = io.StringIO()
    bundle = LoggerBundle(stdout=shared, stderr=shared)
    calls: list[object] = []

    def fake_build_loggers(agent):
        calls.append(agent)
        return bundle

    monkeypatch.setattr("frida_analykit.session.build_loggers", fake_build_loggers)

    session = SessionWrapper(_FakeSession(), config=_config(tmp_path, stdout="logs/outerr.log", stderr="logs/outerr.log"))
    script = session.create_script("16 /index.js\n✄\n")

    script.set_logger()

    assert len(calls) == 1
    session._resolver._registry.handle_exception({"description": "boom"}, None)
    session._session.script.log_handler("info", "hello")
    session._session.script.log_handler("error", "trace")
    output = shared.getvalue()
    assert "[script-error] boom" in output
    assert "hello" in output
    assert "trace" in output


def test_open_script_prints_resolved_output_paths(tmp_path: Path, capsys) -> None:
    jsfile = tmp_path / "_agent.js"
    jsfile.write_text("16 /index.js\n✄\n", encoding="utf-8")
    config = _config(tmp_path, stdout="logs/stdout.log", stderr="logs/stderr.log")

    session = SessionWrapper(_FakeSession(), config=config)

    session.open_script(str(config.jsfile))

    output = capsys.readouterr().out
    assert "███████╗██████╗" in output
    assert f"v{__version__} ready at " in output
    assert "➜  Host:" in output
    assert "➜  Target:" in output
    assert "➜  Script:" in output
    assert "➜  Stdout:" in output
    assert "➜  Stderr:" in output
    assert "_agent.js" in output
    assert "stdout.log" in output
    assert "stderr.log" in output


def test_render_session_banner_includes_core_metadata(tmp_path: Path) -> None:
    config = _config(tmp_path, stdout="logs/outerr.log", stderr="logs/outerr.log").model_copy(
        update={"app": "com.example.demo"}
    )
    banner = render_session_banner(
        config,
        jsfile=config.jsfile,
        updated=datetime(2026, 3, 27, 12, 0, 0),
    )

    assert "███████╗██████╗" in banner
    assert f"v{__version__} ready at 12:00:00" in banner
    assert "➜  Host:" in banner
    assert "➜  Target:" in banner
    assert "➜  Script:" in banner
    assert "➜  Log Output:" in banner
    assert "com.example.demo" in banner
    assert "_agent.js" in banner
    assert "outerr.log" in banner
