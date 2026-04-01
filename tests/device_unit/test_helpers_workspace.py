from __future__ import annotations

import json
from pathlib import Path

from tests.support.paths import REPO_ROOT
from types import SimpleNamespace

import pytest

from frida_analykit.config import AppConfig
from frida_analykit.device import DEFAULT_DEVICE_TEST_APP_ID, DeviceHelpers


def test_device_helpers_workspace_accepts_extra_dependencies(tmp_path: Path) -> None:
    repo_root = REPO_ROOT
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
    assert package_json["dependencies"]["@zsa233/frida-analykit-agent-device-tests"] == "file:/tmp/device-tests.tgz"
    assert package_json["overrides"]["frida-java-bridge"] == f"file:{repo_root / 'node_modules' / 'frida-java-bridge'}"
    assert package_json["devDependencies"]["@types/frida-gum"] == (
        f"file:{repo_root / 'node_modules' / '@types' / 'frida-gum'}"
    )
    assert package_json["devDependencies"]["typescript"] == (
        f"file:{repo_root / 'node_modules' / 'typescript'}"
    )
    assert package_json["devDependencies"]["frida-compile"] == "^19.0.4"
    assert tsconfig_json["compilerOptions"]["types"] == ["frida-gum"]


def test_device_helpers_create_workspace_creates_missing_parent_dirs(tmp_path: Path) -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    workspace = helpers.create_workspace(tmp_path / "nested" / "workspace", app=None)

    assert workspace.root.is_dir()
    assert workspace.agent_path.is_file()
    assert workspace.config_path.is_file()


def test_device_helpers_pack_local_package_uses_workspace_local_npm_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = REPO_ROOT
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


def test_device_helpers_build_workspace_uses_shared_repo_npm_cache_and_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
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
    lock_events: list[tuple[str, Path]] = []

    def fake_run_cli_with_env(args, *, timeout=120, extra_env=None):
        captured["args"] = args
        captured["timeout"] = timeout
        captured["extra_env"] = extra_env
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    class FakeLock:
        def __init__(self, path: Path) -> None:
            self.path = path
            lock_events.append(("init", path))

        def acquire(self) -> None:
            lock_events.append(("acquire", self.path))

        def release(self) -> None:
            lock_events.append(("release", self.path))

    monkeypatch.setattr(helpers, "run_cli_with_env", fake_run_cli_with_env)
    monkeypatch.setitem(DeviceHelpers.build_workspace.__globals__, "DeviceTestLock", FakeLock)

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
    assert captured["extra_env"] == {"npm_config_cache": str(repo_root / ".pytest_cache" / "frida-analykit-npm-cache")}
    assert (repo_root / ".pytest_cache" / "frida-analykit-npm-cache").is_dir()
    assert lock_events == [
        ("init", repo_root / ".pytest_cache" / "frida-analykit-workspace-build.lock"),
        ("acquire", repo_root / ".pytest_cache" / "frida-analykit-workspace-build.lock"),
        ("release", repo_root / ".pytest_cache" / "frida-analykit-workspace-build.lock"),
    ]


def test_device_helpers_workspace_config_keeps_server_device_nested(tmp_path: Path) -> None:
    repo_root = REPO_ROOT
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


def test_device_helpers_ensure_matching_server_skips_install_when_version_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial="SERIAL123",
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    workspace = helpers.create_workspace(tmp_path, app=None)
    captured: list[object] = []

    class FakeManager:
        def inspect_remote_server(self, config):
            captured.append(config)
            return SimpleNamespace(installed_version="16.6.6", executable=True)

    monkeypatch.setitem(
        DeviceHelpers.ensure_matching_server.__globals__,
        "FridaServerManager",
        lambda: FakeManager(),
    )
    monkeypatch.setattr(
        helpers,
        "run_cli",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected install")),
    )

    helpers.ensure_matching_server(workspace.config_path)

    assert len(captured) == 1


def test_device_helpers_ensure_matching_server_installs_when_version_mismatches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial="SERIAL123",
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    workspace = helpers.create_workspace(tmp_path, app=None)
    captured: dict[str, object] = {}

    class FakeManager:
        def inspect_remote_server(self, config):
            return SimpleNamespace(installed_version="17.9.1", executable=True)

    monkeypatch.setitem(
        DeviceHelpers.ensure_matching_server.__globals__,
        "FridaServerManager",
        lambda: FakeManager(),
    )
    monkeypatch.setattr(
        helpers,
        "run_cli",
        lambda args, timeout=120: captured.update(args=args, timeout=timeout)
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    helpers.ensure_matching_server(workspace.config_path)

    assert captured["args"] == [
        "server",
        "install",
        "--config",
        str(workspace.config_path),
        "--version",
        "16.6.6",
    ]
    assert captured["timeout"] == 300


def test_device_helpers_ts_workspace_config_keeps_server_device_nested(tmp_path: Path) -> None:
    repo_root = REPO_ROOT
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


def test_device_helpers_launch_app_prefers_launcher_component_start() -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    calls: list[list[str]] = []
    resolve_result = SimpleNamespace(
        returncode=0,
        stdout="priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\ncom.demo/.MainActivity\n",
        stderr="",
    )
    start_result = SimpleNamespace(returncode=0, stdout="Starting: Intent { cmp=com.demo/.MainActivity }\n", stderr="")

    def fake_adb_run(args: list[str], *, timeout: int = 30):
        calls.append(args)
        if args[:4] == ["shell", "cmd", "package", "resolve-activity"]:
            return resolve_result
        if args[:4] == ["shell", "am", "start", "-n"]:
            return start_result
        raise AssertionError(f"unexpected adb args: {args}")

    helpers.adb_run = fake_adb_run  # type: ignore[method-assign]

    result = helpers.launch_app("com.demo")

    assert result is start_result
    assert calls == [
        ["shell", "cmd", "package", "resolve-activity", "--brief", "com.demo"],
        ["shell", "am", "start", "-n", "com.demo/.MainActivity"],
    ]


def test_device_helpers_launch_app_falls_back_to_monkey_when_component_start_fails() -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    calls: list[list[str]] = []
    resolve_result = SimpleNamespace(
        returncode=0,
        stdout="priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\ncom.demo/.MainActivity\n",
        stderr="",
    )
    start_result = SimpleNamespace(returncode=1, stdout="", stderr="Activity manager busy")
    monkey_result = SimpleNamespace(returncode=0, stdout="Events injected: 1\n", stderr="")

    def fake_adb_run(args: list[str], *, timeout: int = 30):
        calls.append(args)
        if args[:4] == ["shell", "cmd", "package", "resolve-activity"]:
            return resolve_result
        if args[:4] == ["shell", "am", "start", "-n"]:
            return start_result
        if args[:3] == ["shell", "monkey", "-p"]:
            return monkey_result
        raise AssertionError(f"unexpected adb args: {args}")

    helpers.adb_run = fake_adb_run  # type: ignore[method-assign]

    result = helpers.launch_app("com.demo")

    assert result is monkey_result
    assert calls == [
        ["shell", "cmd", "package", "resolve-activity", "--brief", "com.demo"],
        ["shell", "am", "start", "-n", "com.demo/.MainActivity"],
        ["shell", "monkey", "-p", "com.demo", "-c", "android.intent.category.LAUNCHER", "1"],
    ]


def test_device_helpers_package_exists_uses_cached_package_list() -> None:
    repo_root = REPO_ROOT
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
        return SimpleNamespace(returncode=0, stdout="package:com.demo\npackage:com.other\n", stderr="")

    helpers.adb_run = fake_adb_run  # type: ignore[method-assign]

    assert helpers.package_exists("com.demo") is True
    assert helpers.package_exists("com.other") is True
    assert calls == [["shell", "pm", "list", "packages"]]


def test_device_helpers_list_installed_packages_retries_after_transient_adb_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    calls: list[list[str]] = []
    results = iter(
        [
            SimpleNamespace(returncode=1, stdout="", stderr="device busy"),
            SimpleNamespace(returncode=0, stdout="package:com.demo\n", stderr=""),
        ]
    )

    def fake_adb_run(args: list[str], *, timeout: int = 30):
        calls.append(args)
        return next(results)

    monkeypatch.setattr(helpers, "adb_run", fake_adb_run)
    monkeypatch.setattr("frida_analykit.device.helpers.time.sleep", lambda _: None)

    assert helpers.list_installed_packages() == frozenset({"com.demo"})
    assert calls == [
        ["shell", "pm", "list", "packages"],
        ["shell", "pm", "list", "packages"],
    ]


def test_device_helpers_package_exists_falls_back_to_pm_path_when_bulk_list_fails() -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    calls: list[list[str]] = []
    results = iter(
        [
            SimpleNamespace(returncode=1, stdout="", stderr="list failed"),
            SimpleNamespace(returncode=1, stdout="", stderr="list failed"),
            SimpleNamespace(returncode=1, stdout="", stderr="list failed"),
            SimpleNamespace(returncode=0, stdout="package:/data/app/com.demo/base.apk\n", stderr=""),
        ]
    )

    def fake_adb_run(args: list[str], *, timeout: int = 30):
        calls.append(args)
        return next(results)

    helpers.adb_run = fake_adb_run  # type: ignore[method-assign]

    assert helpers.package_exists("com.demo") is True
    assert calls[:3] == [
        ["shell", "pm", "list", "packages"],
        ["shell", "pm", "list", "packages"],
        ["shell", "pm", "list", "packages"],
    ]
    assert calls[3] == ["shell", "pm", "path", "com.demo"]


def test_device_helpers_resolve_device_app_prefers_explicit_app() -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    helpers._probe_launchable_device_app = lambda package, timeout=30, attempt_reporter=None: SimpleNamespace(ok=True, reason=None)  # type: ignore[method-assign]
    helpers.wait_for_device_ready = lambda timeout=120, package=None: None  # type: ignore[method-assign]

    package, source = helpers.resolve_device_app(explicit_app="com.demo.explicit")

    assert package == "com.demo.explicit"
    assert source == "configured"


def test_device_helpers_resolve_device_app_fails_for_missing_explicit_app() -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    helpers._probe_launchable_device_app = lambda package, timeout=30, attempt_reporter=None: SimpleNamespace(ok=False, reason="not-installed")  # type: ignore[method-assign]
    helpers.wait_for_device_ready = lambda timeout=120, package=None: None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="configured device app `com.demo.explicit` was not found"):
        helpers.resolve_device_app(explicit_app="com.demo.explicit")


def test_device_helpers_resolve_device_app_uses_default_test_app_when_not_configured() -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    helpers._probe_launchable_device_app = lambda package, timeout=30, attempt_reporter=None: SimpleNamespace(  # type: ignore[method-assign]
        ok=package == DEFAULT_DEVICE_TEST_APP_ID,
        reason=None if package == DEFAULT_DEVICE_TEST_APP_ID else "not-installed",
    )
    helpers.wait_for_device_ready = lambda timeout=120, package=None: None  # type: ignore[method-assign]

    package, source = helpers.resolve_device_app()

    assert package == DEFAULT_DEVICE_TEST_APP_ID
    assert source == "default-test-app"


def test_device_helpers_resolve_device_app_retries_transient_launch_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    attempts: list[str] = []
    results = iter(
        [
            SimpleNamespace(ok=False, reason="launch-failed: activity manager busy"),
            SimpleNamespace(ok=True, reason=None),
        ]
    )

    monkeypatch.setattr(
        helpers,
        "_probe_launchable_device_app",
        lambda package, timeout=30, attempt_reporter=None: attempts.append(package) or next(results),
    )
    ready_calls: list[tuple[int, str | None]] = []
    monkeypatch.setattr(
        helpers,
        "wait_for_device_ready",
        lambda timeout=120, package=None: ready_calls.append((timeout, package)),
    )
    monkeypatch.setattr("frida_analykit.device.helpers.time.sleep", lambda _: None)

    package, source = helpers.resolve_device_app()

    assert package == DEFAULT_DEVICE_TEST_APP_ID
    assert source == "default-test-app"
    assert attempts == [DEFAULT_DEVICE_TEST_APP_ID, DEFAULT_DEVICE_TEST_APP_ID]
    assert ready_calls == [
        (60, DEFAULT_DEVICE_TEST_APP_ID),
        (60, DEFAULT_DEVICE_TEST_APP_ID),
    ]


def test_device_helpers_resolve_device_app_fails_fast_when_default_test_app_is_missing() -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial="SERIAL123",
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    helpers._probe_launchable_device_app = lambda package, timeout=30, attempt_reporter=None: SimpleNamespace(ok=False, reason="not-installed")  # type: ignore[method-assign]
    helpers.wait_for_device_ready = lambda timeout=120, package=None: None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="make device-test-app-install ANDROID_SERIAL=SERIAL123"):
        helpers.resolve_device_app()


def test_device_helpers_resolve_device_app_fails_for_default_attach_failure() -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    helpers._probe_launchable_device_app = lambda package, timeout=30, attempt_reporter=None: SimpleNamespace(ok=True, reason=None)  # type: ignore[method-assign]
    helpers.find_attachable_app_pid = lambda package, host=None, timeout=30: (None, "attach probe timed out")  # type: ignore[method-assign]
    helpers.wait_for_device_ready = lambda timeout=120, package=None: None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="default device test app `com.frida_analykit.test` is not attachable"):
        helpers.resolve_device_app(require_attach=True)


def test_device_helpers_resolve_device_app_retries_transient_attach_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )
    attach_results = iter([(None, "attach probe timed out"), (4321, None)])

    monkeypatch.setattr(
        helpers,
        "_probe_launchable_device_app",
        lambda package, timeout=30, attempt_reporter=None: SimpleNamespace(ok=True, reason=None),
    )
    monkeypatch.setattr(helpers, "find_attachable_app_pid", lambda package, host=None, timeout=30: next(attach_results))
    monkeypatch.setattr(helpers, "wait_for_device_ready", lambda timeout=120, package=None: None)
    monkeypatch.setattr("frida_analykit.device.helpers.time.sleep", lambda _: None)

    package, source = helpers.resolve_device_app(require_attach=True)

    assert package == DEFAULT_DEVICE_TEST_APP_ID
    assert source == "default-test-app"


def test_device_helpers_resolve_device_app_fails_for_explicit_attach_failure() -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    helpers._probe_launchable_device_app = lambda package, timeout=30, attempt_reporter=None: SimpleNamespace(ok=True, reason=None)  # type: ignore[method-assign]
    helpers.find_attachable_app_pid = lambda package, host=None, timeout=30: (None, "attach probe timed out")  # type: ignore[method-assign]
    helpers.wait_for_device_ready = lambda timeout=120, package=None: None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="is not attachable for device tests"):
        helpers.resolve_device_app(explicit_app="com.demo.explicit", require_attach=True)


def test_device_helpers_probe_launchable_device_app_accepts_nonzero_launch_with_live_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = REPO_ROOT
    helpers = DeviceHelpers(
        repo_root=repo_root,
        env={},
        serial=None,
        python_executable=Path("/usr/bin/python3"),
        frida_version="16.6.6",
    )

    monkeypatch.setattr(helpers, "package_exists", lambda package, timeout=30: True)
    monkeypatch.setattr(helpers, "force_stop_app", lambda package, timeout=30: None)
    monkeypatch.setattr(
        helpers,
        "launch_app",
        lambda package, timeout=30: SimpleNamespace(returncode=1, stdout="transient monkey failure", stderr=""),
    )
    monkeypatch.setattr(helpers, "wait_for_app_pid", lambda package, timeout=30: 4321)
    monkeypatch.setattr(helpers, "pidof_app", lambda package, timeout=5: 4321)
    monkeypatch.setattr("frida_analykit.device.helpers.time.sleep", lambda _: None)

    result = helpers._probe_launchable_device_app("com.demo")

    assert result.ok is True
    assert result.reason is None
