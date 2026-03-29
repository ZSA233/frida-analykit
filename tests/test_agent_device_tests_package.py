from __future__ import annotations

import importlib.util
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
from frida_analykit.config import AppConfig


def _load_device_helpers_type():
    conftest_path = Path(__file__).resolve().parent / "device" / "conftest.py"
    spec = importlib.util.spec_from_file_location("frida_analykit_device_conftest", conftest_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.DeviceHelpers


DeviceHelpers = _load_device_helpers_type()


def test_agent_device_tests_package_build_uses_dedicated_build_config() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    package_json = json.loads(
        (repo_root / "packages/frida-analykit-agent-device-tests/package.json").read_text(encoding="utf-8")
    )
    build_config = json.loads(
        (repo_root / "packages/frida-analykit-agent-device-tests/tsconfig.build.json").read_text(encoding="utf-8")
    )

    assert package_json["private"] is True
    assert package_json["main"] == "./dist/index.js"
    assert package_json["types"] == "./dist/index.d.ts"
    assert "dist/**/*" in package_json["files"]
    assert package_json["exports"]["."]["default"] == "./dist/index.js"
    assert package_json["exports"]["."]["types"] == "./dist/index.d.ts"
    assert package_json["peerDependencies"]["@zsa233/frida-analykit-agent"] == "*"
    assert package_json["scripts"]["build"] == "tsc -p tsconfig.build.json"
    assert package_json["scripts"]["prepack"] == "npm run build"
    assert build_config["extends"] == "./tsconfig.json"
    assert build_config["compilerOptions"]["noEmit"] is False
    assert build_config["compilerOptions"]["outDir"] == "./dist"
    assert build_config["compilerOptions"]["declaration"] is True


def test_device_helpers_workspace_accepts_extra_dependencies(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    helpers.create_ts_workspace_with_local_runtime(
        tmp_path,
        app=None,
        agent_package_spec="file:/tmp/runtime.tgz",
        extra_dependencies={
            "@zsa233/frida-analykit-agent-device-tests": "file:/tmp/device-tests.tgz",
        },
    )

    package_json = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    tsconfig_json = json.loads((tmp_path / "tsconfig.json").read_text(encoding="utf-8"))
    assert package_json["dependencies"]["@zsa233/frida-analykit-agent"] == "file:/tmp/runtime.tgz"
    assert (
        package_json["dependencies"]["@zsa233/frida-analykit-agent-device-tests"]
        == "file:/tmp/device-tests.tgz"
    )
    assert package_json["overrides"]["frida-java-bridge"] == f"file:{repo_root / 'node_modules' / 'frida-java-bridge'}"
    assert package_json["devDependencies"] == {
        "@types/frida-gum": f"file:{repo_root / 'node_modules' / '@types' / 'frida-gum'}",
        "typescript": f"file:{repo_root / 'node_modules' / 'typescript'}",
    }
    assert tsconfig_json["compilerOptions"]["types"] == ["frida-gum"]


def test_device_helpers_pack_local_package_uses_workspace_local_npm_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={"BASE_ENV": "1"},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    package_dir = repo_root / "packages" / "frida-analykit-agent-device-tests"
    expected_tarball = tmp_path / "device-tests.tgz"
    expected_tarball.write_text("stub", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout="device-tests.tgz\n",
            stderr="",
        )

    pack_globals = DeviceHelpers.pack_local_package.__globals__
    monkeypatch.setitem(pack_globals, "shutil", SimpleNamespace(which=lambda name: "/usr/bin/npm"))
    monkeypatch.setitem(pack_globals, "subprocess", SimpleNamespace(run=fake_run))

    tarball = helpers.pack_local_package(tmp_path, package_dir)

    assert tarball == expected_tarball
    assert captured["args"] == (["npm", "pack", str(package_dir)],)
    env = captured["kwargs"]["env"]
    assert env["BASE_ENV"] == "1"
    assert env["npm_config_cache"] == str(tmp_path / ".npm-cache")
    assert Path(env["npm_config_cache"]).is_dir()


def test_device_helpers_build_workspace_uses_workspace_local_npm_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={"BASE_ENV": "1"},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    workspace = helpers.create_workspace(tmp_path, app=None)
    workspace.agent_path.write_text("// built\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_cli_with_env(args, *, timeout=120, extra_env=None):
        captured["args"] = args
        captured["timeout"] = timeout
        captured["extra_env"] = extra_env
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(helpers, "run_cli_with_env", fake_run_cli_with_env)

    helpers.build_workspace(workspace, install=True, timeout=45)

    assert captured["args"] == [
        "build",
        "--config",
        str(workspace.config_path),
        "--project-dir",
        str(workspace.root),
        "--install",
    ]
    assert captured["timeout"] == 45
    assert captured["extra_env"] == {"npm_config_cache": str(workspace.root / ".npm-cache")}
    assert (workspace.root / ".npm-cache").is_dir()


def test_device_helpers_workspace_config_keeps_server_device_nested(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial="SERIAL123",
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    workspace = helpers.create_workspace(tmp_path, app="com.example.demo")
    config = AppConfig.from_yaml(workspace.config_path)

    assert config.app == "com.example.demo"
    assert config.server.device == "SERIAL123"
    assert config.agent.stdout == workspace.log_path
    assert config.jsfile == workspace.agent_path


def test_device_helpers_ts_workspace_config_keeps_server_device_nested(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial="SERIAL123",
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    workspace = helpers.create_ts_workspace_with_local_runtime(
        tmp_path,
        app="com.example.demo",
        agent_package_spec="file:/tmp/runtime.tgz",
    )
    config = AppConfig.from_yaml(workspace.config_path)

    assert config.app == "com.example.demo"
    assert config.server.device == "SERIAL123"
    assert config.agent.stdout == workspace.log_path
    assert config.jsfile == workspace.root / "_agent.js"


def test_device_helpers_launch_app_falls_back_to_am_start_when_monkey_fails() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    calls: list[list[str]] = []
    monkey_result = SimpleNamespace(returncode=1, stdout="", stderr="Unable to connect to window manager")
    resolve_result = SimpleNamespace(
        returncode=0,
        stdout="priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\ncom.demo/.MainActivity\n",
        stderr="",
    )
    fallback_result = SimpleNamespace(returncode=0, stdout="Starting: Intent { cmp=com.demo/.MainActivity }\n", stderr="")

    def fake_adb_run(args: list[str], *, timeout: int = 30):
        calls.append(args)
        if args[:3] == ["shell", "monkey", "-p"]:
            return monkey_result
        if args[:4] == ["shell", "cmd", "package", "resolve-activity"]:
            return resolve_result
        if args[:4] == ["shell", "am", "start", "-W"]:
            return fallback_result
        raise AssertionError(f"unexpected adb args: {args}")

    helpers.adb_run = fake_adb_run  # type: ignore[method-assign]

    result = helpers.launch_app("com.demo")

    assert result is fallback_result
    assert calls == [
        ["shell", "monkey", "-p", "com.demo", "-c", "android.intent.category.LAUNCHER", "1"],
        ["shell", "cmd", "package", "resolve-activity", "--brief", "com.demo"],
        ["shell", "am", "start", "-W", "-n", "com.demo/.MainActivity"],
    ]


def test_device_helpers_pidof_remote_server_falls_back_to_server_basename() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    calls: list[list[str]] = []

    def fake_adb_run(args: list[str], *, timeout: int = 30):
        calls.append(args)
        if "pidof /data/local/tmp/frida-server" in args[-1]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "pidof frida-server" in args[-1]:
            return SimpleNamespace(returncode=0, stdout="18390\n", stderr="")
        raise AssertionError(f"unexpected adb args: {args}")

    helpers.adb_run = fake_adb_run  # type: ignore[method-assign]

    pid = helpers.pidof_remote_server()

    assert pid == 18390
    assert calls[:2] == [
        ["shell", "sh -c 'pidof /data/local/tmp/frida-server'"],
        ["shell", "su 0 sh -c 'pidof /data/local/tmp/frida-server'"],
    ]
    assert any("pidof frida-server" in command[-1] for command in calls)


def test_device_helpers_start_boot_process_retries_when_remote_pid_is_not_visible_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    config_path = repo_root / "tests" / "fixtures" / "dummy-config.yml"
    wait_calls: list[int] = []

    class FakeProcess:
        stdout = None
        stderr = None

        def poll(self):
            return None

    fake_process = FakeProcess()

    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["subprocess"], "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(helpers, "_probe_remote_ready", lambda host="127.0.0.1:27042": None)

    def fake_wait_for_remote_server_pid(*, timeout: int = 30):
        wait_calls.append(timeout)
        if len(wait_calls) == 1:
            raise TimeoutError("pid not visible yet")
        return 18390

    monkeypatch.setattr(helpers, "wait_for_remote_server_pid", fake_wait_for_remote_server_pid)
    monotonic_values = iter([0.0, 0.0, 1.0, 1.0, 2.0])
    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["time"], "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(DeviceHelpers.start_boot_process.__globals__["time"], "sleep", lambda _: None)

    process = helpers.start_boot_process(config_path, force_restart=True, timeout=10)

    assert process is fake_process
    assert wait_calls == [5, 5]


def test_device_helpers_find_attachable_app_pid_keeps_polling_after_nonzero_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    launch_result = SimpleNamespace(returncode=1, stdout="", stderr="transient launch failure")
    pid_sequence = iter([None, 4321])
    probe_calls: list[int] = []

    monkeypatch.setattr(helpers, "launch_app", lambda package, timeout=30: launch_result)
    monkeypatch.setattr(helpers, "pidof_app", lambda package, timeout=30: next(pid_sequence))
    monkeypatch.setattr(
        helpers,
        "_probe_attachable_pid",
        lambda pid, host="127.0.0.1:27042", timeout=10: (probe_calls.append(pid), None)[1],
    )
    monkeypatch.setattr(DeviceHelpers.find_attachable_app_pid.__globals__["time"], "sleep", lambda _: None)

    pid, error = helpers.find_attachable_app_pid("com.demo", timeout=10)

    assert pid == 4321
    assert error is None
    assert probe_calls == [4321]


def test_device_helpers_find_attachable_app_pid_retries_launch_until_pid_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    launch_results = iter([
        SimpleNamespace(returncode=1, stdout="", stderr="activity manager unavailable"),
        SimpleNamespace(returncode=0, stdout="started", stderr=""),
    ])
    pid_sequence = iter([None, None, None, 5678])
    probe_calls: list[int] = []
    launch_calls: list[str] = []

    monkeypatch.setattr(
        helpers,
        "launch_app",
        lambda package, timeout=30: (launch_calls.append(package), next(launch_results))[1],
    )
    monkeypatch.setattr(helpers, "pidof_app", lambda package, timeout=30: next(pid_sequence))
    monkeypatch.setattr(
        helpers,
        "_probe_attachable_pid",
        lambda pid, host="127.0.0.1:27042", timeout=10: (probe_calls.append(pid), None)[1],
    )
    monotonic_values = iter([0.0, 0.0, 0.5, 2.5, 2.5, 5.0, 5.0, 5.5, 5.5])
    monkeypatch.setattr(DeviceHelpers.find_attachable_app_pid.__globals__["time"], "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(DeviceHelpers.find_attachable_app_pid.__globals__["time"], "sleep", lambda _: None)

    pid, error = helpers.find_attachable_app_pid("com.demo", timeout=10)

    assert pid == 5678
    assert error is None
    assert launch_calls == ["com.demo", "com.demo"]
    assert probe_calls == [5678]
