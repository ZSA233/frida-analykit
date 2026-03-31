from __future__ import annotations

import io
from pathlib import Path

import pytest

from frida_analykit.device import orchestrator


def test_build_device_test_command_includes_serial_and_forwarded_vars() -> None:
    command = orchestrator.build_device_test_command(
        "SERIAL123",
        repo_root=Path("/tmp/repo"),
        make_target="device-test",
        device_test_app="com.demo.app",
        device_test_skip_app="1",
    )

    assert command == [
        "make",
        "-C",
        "/tmp/repo",
        "device-test",
        "ANDROID_SERIAL=SERIAL123",
        "DEVICE_TEST_APP=com.demo.app",
        "DEVICE_TEST_SKIP_APP=1",
    ]


def test_run_device_test_all_returns_nonzero_when_any_child_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    output = io.StringIO()
    commands: list[list[str]] = []
    envs: list[dict[str, str] | None] = []

    class FakeProcess:
        def __init__(self, serial: str, returncode: int) -> None:
            self.stdout = io.StringIO(f"{serial}-line\n")
            self._returncode = returncode

        def wait(self) -> int:
            return self._returncode

    returncodes = iter([0, 1])

    def fake_popen(command, cwd=None, env=None, stdout=None, stderr=None, text=None, bufsize=None):
        commands.append(command)
        envs.append(env)
        return FakeProcess(command[4].split("=", 1)[1], next(returncodes))

    monkeypatch.setattr(orchestrator.subprocess, "Popen", fake_popen)

    result = orchestrator.run_device_test_all(
        ("SERIAL123", "SERIAL456"),
        repo_root=Path("/tmp/repo"),
        make_target="device-test",
        output=output,
    )

    assert result == 1
    assert commands[0][4] == "ANDROID_SERIAL=SERIAL123"
    assert commands[1][4] == "ANDROID_SERIAL=SERIAL456"
    assert envs[0] is not None
    assert envs[0]["PYTHONUNBUFFERED"] == "1"
    rendered = output.getvalue()
    assert "[SERIAL123] SERIAL123-line" in rendered
    assert "[SERIAL456] SERIAL456-line" in rendered
    assert "[SERIAL456] exited with code 1" in rendered


def test_build_child_env_forces_pytest_colors_for_tty_output() -> None:
    class TtyOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    env = orchestrator._build_child_env({}, TtyOutput())

    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PYTEST_ADDOPTS"] == "--color=yes"
    assert env["PY_COLORS"] == "1"
    assert env["CLICOLOR_FORCE"] == "1"
    assert env["FORCE_COLOR"] == "1"


def test_build_child_env_respects_no_color_and_existing_pytest_color() -> None:
    class TtyOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    no_color_env = orchestrator._build_child_env({"NO_COLOR": "1"}, TtyOutput())
    explicit_env = orchestrator._build_child_env({"PYTEST_ADDOPTS": "-q --color=no"}, TtyOutput())

    assert no_color_env["PYTHONUNBUFFERED"] == "1"
    assert "PYTEST_ADDOPTS" not in no_color_env
    assert explicit_env["PYTEST_ADDOPTS"] == "-q --color=no"


def test_main_prefers_device_test_serials_env_over_android_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVICE_TEST_SERIALS", "SERIAL123,SERIAL456")
    monkeypatch.setenv("ANDROID_SERIAL", "IGNORED")
    monkeypatch.setenv("DEVICE_TEST_SKIP_APP", "1")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        orchestrator,
        "resolve_device_test_serials",
        lambda **kwargs: (captured.setdefault("resolve_kwargs", kwargs), ("SERIAL123", "SERIAL456"))[1],
    )
    monkeypatch.setattr(
        orchestrator,
        "run_device_test_all",
        lambda serials, **kwargs: captured.update(serials=serials, kwargs=kwargs) or 0,
    )

    result = orchestrator.main([])

    assert result == 0
    assert captured["serials"] == ("SERIAL123", "SERIAL456")
    assert captured["kwargs"]["device_test_skip_app"] == "1"
    assert captured["resolve_kwargs"]["requested_serials"] == ["SERIAL123", "SERIAL456"]
