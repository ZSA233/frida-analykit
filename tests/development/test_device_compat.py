from __future__ import annotations

from pathlib import Path

from tests.support.paths import REPO_ROOT
from types import SimpleNamespace

import pytest

from frida_analykit.development.device_compat import (
    DeviceCompatProbeError,
    DeviceCompatResult,
    DeviceCompatSummary,
    _run_version_probe_suite,
    build_device_doctor_config,
    estimate_compat_boundary,
    format_device_compat_summary,
    resolve_device_compat_serials,
    run_device_compat_scan,
)
from frida_analykit.device import DEFAULT_DEVICE_TEST_APP_ID
from frida_analykit.development.managed_envs import sample_frida_versions


def test_sample_frida_versions_uses_latest_oldest_then_gap_midpoint() -> None:
    sampled = sample_frida_versions(
        ("16.5.9", "16.6.6", "17.0.1", "17.8.2", "17.9.1"),
        iterations=5,
    )

    assert sampled == ("17.9.1", "16.5.9", "17.0.1", "16.6.6", "17.8.2")


def test_sample_frida_versions_respects_single_iteration_limit() -> None:
    sampled = sample_frida_versions(
        ("16.5.9", "16.6.6", "17.0.1"),
        iterations=1,
    )

    assert sampled == ("17.0.1",)


def test_estimate_compat_boundary_reports_success_failure_cutoff() -> None:
    boundary = estimate_compat_boundary(
        [
            DeviceCompatResult("17.9.1", "spawn", "fail", "inject", "boom", 1.0),
            DeviceCompatResult("17.8.2", "spawn", "success", None, "ok", 1.0),
            DeviceCompatResult("16.6.6", "spawn", "success", None, "ok", 1.0),
        ]
    )

    assert boundary == "sampled compatibility reached 17.8.2; sampled failure begins at 17.9.1"


def test_format_device_compat_summary_renders_grouped_output() -> None:
    summary = DeviceCompatSummary(
        serial="SERIAL123",
        remote_host="127.0.0.1:31123",
        sampled_versions=("17.9.1", "16.6.6"),
        results=(
            DeviceCompatResult("17.9.1", "spawn", "success", None, "spawn injection probe succeeded", 2.0, app="com.demo"),
            DeviceCompatResult("16.6.6", "spawn", "unavailable", "env", "no managed env for frida==16.6.6", 0.1),
        ),
    )

    rendered = format_device_compat_summary(summary)

    assert "Device: SERIAL123" in rendered
    assert "Remote host: 127.0.0.1:31123" in rendered
    assert "Sampled versions: 17.9.1, 16.6.6" in rendered
    assert "Probe: spawn" in rendered
    assert "- 17.9.1: success app=com.demo" in rendered
    assert "- 16.6.6: unavailable stage=env" in rendered


def test_run_device_compat_scan_reports_install_hint_for_missing_explicit_env(monkeypatch) -> None:
    repo_root = REPO_ROOT
    config = build_device_doctor_config(repo_root, app=None)
    resolve_calls: list[str] = []

    class FakeHelper:
        def __init__(self, repo_root, env, serial, *, python_executable, frida_version, remote_host, remote_servername):
            resolve_calls.append(serial)
            self.serial = serial
            self.frida_version = frida_version

        def current_frida_version(self) -> str:
            return self.frida_version

        def resolve_device_app(
            self,
            *,
            explicit_app: str | None = None,
            timeout: int = 30,
            require_attach: bool = False,
            attempt_reporter=None,
        ) -> tuple[str, str]:
            raise AssertionError("device app selection should not run when no sampled env is available")

    monkeypatch.setattr("frida_analykit.development.device_compat.list_managed_frida_envs", lambda repo_root: ())
    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceHelpers", FakeHelper)

    summaries = run_device_compat_scan(
        repo_root,
        env={},
        config=config,
        serials=("SERIAL123",),
        requested_versions=("17.9.0",),
        probe_kinds=("spawn",),
    )

    result = summaries[0].results[0]
    assert result.status == "unavailable"
    assert result.stage == "env"
    assert "no managed env for frida==17.9.0" in result.detail
    assert "make env-create FRIDA_VERSION=17.9.0" in result.detail
    assert "--install-missing-env" in result.detail
    assert resolve_calls == []


def test_run_device_compat_scan_can_auto_create_missing_requested_env(monkeypatch) -> None:
    repo_root = REPO_ROOT
    config = build_device_doctor_config(repo_root, app=None)
    created_versions: list[str] = []
    seen_list_calls = {"count": 0}

    class FakeManager:
        def create(self, *, name=None, profile=None, frida_version=None, with_repl=True):
            created_versions.append(frida_version)
            return SimpleNamespace(name=f"frida-{frida_version}", frida_version=frida_version)

    class FakeHelper:
        def __init__(self, repo_root, env, serial, *, python_executable, frida_version, remote_host, remote_servername):
            self.serial = serial
            self.frida_version = frida_version

        def current_frida_version(self) -> str:
            return self.frida_version

        def resolve_device_app(
            self,
            *,
            explicit_app: str | None = None,
            timeout: int = 30,
            require_attach: bool = False,
            attempt_reporter=None,
        ) -> tuple[str, str]:
            return explicit_app or DEFAULT_DEVICE_TEST_APP_ID, "default-test-app"

    def fake_list_managed_frida_envs(repo_root):
        seen_list_calls["count"] += 1
        if seen_list_calls["count"] == 1:
            return ()
        return (
            SimpleNamespace(frida_version="17.9.0", python_path=Path("/tmp/env-17.9.0"), source="repo"),
        )

    monkeypatch.setattr("frida_analykit.development.device_compat.list_managed_frida_envs", fake_list_managed_frida_envs)
    monkeypatch.setattr("frida_analykit.development.device_compat.EnvManager.for_repo", lambda repo_root: FakeManager())
    monkeypatch.setattr("frida_analykit.development.device_compat.derive_remote_host", lambda serial: "127.0.0.1:31123")
    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceHelpers", FakeHelper)
    monkeypatch.setattr(
        "frida_analykit.development.device_compat._run_version_probe_suite",
        lambda helper, *, configured_app, preferred_app, probe_kinds, stage_reporter=None: (
            preferred_app or DEFAULT_DEVICE_TEST_APP_ID,
            {probe_kind: {"ping": "ok"} for probe_kind in probe_kinds},
        ),
    )

    summaries = run_device_compat_scan(
        repo_root,
        env={},
        config=config,
        serials=("SERIAL123",),
        requested_versions=("17.9.0",),
        probe_kinds=("spawn",),
        install_missing_env=True,
    )

    assert created_versions == ["17.9.0"]
    assert summaries[0].results[0].status == "success"
    assert summaries[0].results[0].version == "17.9.0"


def test_run_device_compat_scan_uses_default_test_app_when_no_app_is_configured(monkeypatch) -> None:
    repo_root = REPO_ROOT
    config = build_device_doctor_config(repo_root, app=None)
    resolve_calls: list[dict[str, object]] = []

    class FakeHelper:
        def __init__(self, repo_root, env, serial, *, python_executable, frida_version, remote_host, remote_servername):
            self.serial = serial
            self.frida_version = frida_version

        def current_frida_version(self) -> str:
            return self.frida_version

        def resolve_device_app(
            self,
            *,
            explicit_app: str | None = None,
            timeout: int = 30,
            require_attach: bool = False,
            attempt_reporter=None,
        ) -> tuple[str, str]:
            package = explicit_app or DEFAULT_DEVICE_TEST_APP_ID
            resolve_calls.append({"package": package, "timeout": timeout, "require_attach": require_attach})
            return package, "default-test-app"

    monkeypatch.setattr(
        "frida_analykit.development.device_compat.list_managed_frida_envs",
        lambda repo_root: (
            SimpleNamespace(frida_version="17.9.1", python_path=Path("/tmp/env-17.9.1"), source="repo"),
        ),
    )
    monkeypatch.setattr("frida_analykit.development.device_compat.derive_remote_host", lambda serial: "127.0.0.1:31123")
    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceHelpers", FakeHelper)
    monkeypatch.setattr(
        "frida_analykit.development.device_compat._run_version_probe_suite",
        lambda helper, *, configured_app, preferred_app, probe_kinds, stage_reporter=None: (
            preferred_app or DEFAULT_DEVICE_TEST_APP_ID,
            {probe_kind: {"ping": "ok"} for probe_kind in probe_kinds},
        ),
    )

    summaries = run_device_compat_scan(
        repo_root,
        env={},
        config=config,
        serials=("SERIAL123",),
        requested_versions=("17.9.1",),
        probe_kinds=("spawn",),
    )

    assert summaries[0].results[0].app == DEFAULT_DEVICE_TEST_APP_ID
    assert resolve_calls[0]["package"] == DEFAULT_DEVICE_TEST_APP_ID


def test_run_device_compat_scan_prefers_config_app_before_default_test_app(monkeypatch) -> None:
    repo_root = REPO_ROOT
    config = build_device_doctor_config(repo_root, app="com.demo.config")
    resolve_calls: list[dict[str, object]] = []

    class FakeHelper:
        def __init__(self, repo_root, env, serial, *, python_executable, frida_version, remote_host, remote_servername):
            self.serial = serial
            self.frida_version = frida_version

        def current_frida_version(self) -> str:
            return self.frida_version

        def resolve_device_app(
            self,
            *,
            explicit_app: str | None = None,
            timeout: int = 30,
            require_attach: bool = False,
            attempt_reporter=None,
        ) -> tuple[str, str]:
            package = explicit_app or DEFAULT_DEVICE_TEST_APP_ID
            resolve_calls.append({"package": package, "timeout": timeout, "require_attach": require_attach})
            assert package == "com.demo.config"
            return package, "configured"

    monkeypatch.setattr(
        "frida_analykit.development.device_compat.list_managed_frida_envs",
        lambda repo_root: (
            SimpleNamespace(frida_version="17.9.1", python_path=Path("/tmp/env-17.9.1"), source="repo"),
        ),
    )
    monkeypatch.setattr("frida_analykit.development.device_compat.derive_remote_host", lambda serial: "127.0.0.1:31123")
    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceHelpers", FakeHelper)
    monkeypatch.setattr(
        "frida_analykit.development.device_compat._run_version_probe_suite",
        lambda helper, *, configured_app, preferred_app, probe_kinds, stage_reporter=None: (
            preferred_app or configured_app or DEFAULT_DEVICE_TEST_APP_ID,
            {probe_kind: {"ping": "ok"} for probe_kind in probe_kinds},
        ),
    )

    summaries = run_device_compat_scan(
        repo_root,
        env={},
        config=config,
        serials=("SERIAL123",),
        requested_versions=("17.9.1",),
        probe_kinds=("spawn",),
    )

    assert summaries[0].results[0].app == "com.demo.config"
    assert resolve_calls[0]["package"] == "com.demo.config"


def test_run_device_compat_scan_reports_progress_in_order(monkeypatch) -> None:
    repo_root = REPO_ROOT
    config = build_device_doctor_config(repo_root, app=None)
    events: list[tuple[str, object]] = []

    class FakeReporter:
        def on_scan_start(self, *, serials) -> None:
            events.append(("scan-start", tuple(serials)))

        def on_device_start(self, **kwargs) -> None:
            events.append(("device-start", kwargs["serial"]))

        def on_device_stage(self, **kwargs) -> None:
            events.append(("device-stage", kwargs["stage"], kwargs.get("detail")))

        def on_version_start(self, **kwargs) -> None:
            events.append(("version-start", kwargs["version"]))

        def on_version_stage(self, **kwargs) -> None:
            events.append(("version-stage", kwargs["version"], kwargs["stage"], kwargs.get("detail")))

        def on_version_result(self, **kwargs) -> None:
            result = kwargs["result"]
            events.append(("version-result", kwargs["version"], result.probe_kind, result.status, result.stage, result.app))

    class FakeHelper:
        def __init__(self, repo_root, env, serial, *, python_executable, frida_version, remote_host, remote_servername):
            self.serial = serial
            self.frida_version = frida_version

        def current_frida_version(self) -> str:
            return self.frida_version

        def resolve_device_app(
            self,
            *,
            explicit_app: str | None = None,
            timeout: int = 30,
            require_attach: bool = False,
            attempt_reporter=None,
        ) -> tuple[str, str]:
            package = explicit_app or DEFAULT_DEVICE_TEST_APP_ID
            if attempt_reporter is not None:
                source_label = "configured app" if explicit_app else "default device test app"
                source = "configured" if explicit_app else "default-test-app"
                attempt_reporter(f"probing {source_label} `{package}`")
                attempt_reporter(f"selected {source} `{package}`")
            return package, "configured" if explicit_app else "default-test-app"

    monkeypatch.setattr(
        "frida_analykit.development.device_compat.list_managed_frida_envs",
        lambda repo_root: (
            SimpleNamespace(frida_version="17.9.1", python_path=Path("/tmp/env-17.9.1"), source="repo"),
        ),
    )
    monkeypatch.setattr("frida_analykit.development.device_compat.derive_remote_host", lambda serial: f"127.0.0.1:{serial}")
    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceHelpers", FakeHelper)
    monkeypatch.setattr(
        "frida_analykit.development.device_compat._run_version_probe_suite",
        lambda helper, *, configured_app, preferred_app, probe_kinds, stage_reporter=None: (
            stage_reporter("install", None),
            stage_reporter("boot", None),
            stage_reporter("spawn", None),
            stage_reporter("attach", None),
            (
                preferred_app or DEFAULT_DEVICE_TEST_APP_ID,
                {
                    "spawn": {"ping": "ok"},
                    "attach": {"ping": "ok"},
                },
            ),
        )[-1],
    )

    summaries = run_device_compat_scan(
        repo_root,
        env={},
        config=config,
        serials=("SERIAL123",),
        requested_versions=("17.9.1",),
        reporter=FakeReporter(),
    )

    assert summaries[0].results[0].status == "success"
    assert events == [
        ("scan-start", ("SERIAL123",)),
        ("device-start", "SERIAL123"),
        ("device-stage", "select-app", None),
        ("device-stage", "select-app", f"probing default device test app `{DEFAULT_DEVICE_TEST_APP_ID}`"),
        ("device-stage", "select-app", f"selected default-test-app `{DEFAULT_DEVICE_TEST_APP_ID}`"),
        ("device-stage", "select-app", f"selected `{DEFAULT_DEVICE_TEST_APP_ID}`"),
        ("version-start", "17.9.1"),
        ("version-stage", "17.9.1", "env", None),
        ("version-stage", "17.9.1", "install", None),
        ("version-stage", "17.9.1", "boot", None),
        ("version-stage", "17.9.1", "spawn", None),
        ("version-stage", "17.9.1", "attach", None),
        ("version-result", "17.9.1", "spawn", "success", None, DEFAULT_DEVICE_TEST_APP_ID),
        ("version-result", "17.9.1", "attach", "success", None, DEFAULT_DEVICE_TEST_APP_ID),
    ]


def test_run_device_compat_scan_keeps_explicit_versions_without_iteration_cropping(monkeypatch) -> None:
    repo_root = REPO_ROOT
    config = build_device_doctor_config(repo_root, app=None)

    class FakeHelper:
        def __init__(self, repo_root, env, serial, *, python_executable, frida_version, remote_host, remote_servername):
            self.serial = serial
            self.frida_version = frida_version

        def current_frida_version(self) -> str:
            return self.frida_version

        def resolve_device_app(
            self,
            *,
            explicit_app: str | None = None,
            timeout: int = 30,
            require_attach: bool = False,
            attempt_reporter=None,
        ) -> tuple[str, str]:
            return explicit_app or DEFAULT_DEVICE_TEST_APP_ID, "default-test-app"

    monkeypatch.setattr(
        "frida_analykit.development.device_compat.list_managed_frida_envs",
        lambda repo_root: (
            SimpleNamespace(frida_version="16.5.9", python_path=Path("/tmp/env-16.5.9"), source="repo"),
            SimpleNamespace(frida_version="17.0.1", python_path=Path("/tmp/env-17.0.1"), source="repo"),
        ),
    )
    monkeypatch.setattr("frida_analykit.development.device_compat.derive_remote_host", lambda serial: "127.0.0.1:31123")
    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceHelpers", FakeHelper)
    monkeypatch.setattr(
        "frida_analykit.development.device_compat._run_version_probe_suite",
        lambda helper, *, configured_app, preferred_app, probe_kinds, stage_reporter=None: (
            preferred_app or DEFAULT_DEVICE_TEST_APP_ID,
            {probe_kind: {"ping": "ok"} for probe_kind in probe_kinds},
        ),
    )

    summaries = run_device_compat_scan(
        repo_root,
        env={},
        config=config,
        serials=("SERIAL123",),
        requested_versions=("17.0.1", "16.5.9", "17.0.1"),
        iterations=1,
        probe_kinds=("spawn",),
    )

    assert summaries[0].sampled_versions == ("17.0.1", "16.5.9")
    assert [item.version for item in summaries[0].results] == ["17.0.1", "16.5.9"]


def test_run_device_compat_scan_reuses_selected_device_app_across_versions(monkeypatch) -> None:
    repo_root = REPO_ROOT
    config = build_device_doctor_config(repo_root, app=None)
    device_level_calls: list[tuple[bool, str]] = []
    seen_preferred_apps: list[tuple[str, str | None]] = []

    class FakeHelper:
        def __init__(self, repo_root, env, serial, *, python_executable, frida_version, remote_host, remote_servername):
            self.serial = serial
            self.frida_version = frida_version

        def current_frida_version(self) -> str:
            return self.frida_version

        def resolve_device_app(
            self,
            *,
            explicit_app: str | None = None,
            timeout: int = 30,
            require_attach: bool = False,
            attempt_reporter=None,
        ) -> tuple[str, str]:
            device_level_calls.append((require_attach, self.frida_version))
            return explicit_app or DEFAULT_DEVICE_TEST_APP_ID, "default-test-app"

    def fake_run_probe_suite(helper, *, configured_app, preferred_app, probe_kinds, stage_reporter=None):
        seen_preferred_apps.append((helper.frida_version, preferred_app))
        selected = preferred_app or DEFAULT_DEVICE_TEST_APP_ID
        return selected, {probe_kind: {"ping": "ok"} for probe_kind in probe_kinds}

    monkeypatch.setattr(
        "frida_analykit.development.device_compat.list_managed_frida_envs",
        lambda repo_root: (
            SimpleNamespace(frida_version="16.5.9", python_path=Path("/tmp/env-16.5.9"), source="repo"),
            SimpleNamespace(frida_version="17.0.1", python_path=Path("/tmp/env-17.0.1"), source="repo"),
        ),
    )
    monkeypatch.setattr("frida_analykit.development.device_compat.derive_remote_host", lambda serial: "127.0.0.1:31123")
    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceHelpers", FakeHelper)
    monkeypatch.setattr("frida_analykit.development.device_compat._run_version_probe_suite", fake_run_probe_suite)

    summaries = run_device_compat_scan(
        repo_root,
        env={},
        config=config,
        serials=("SERIAL123",),
        requested_versions=("16.5.9", "17.0.1"),
        probe_kinds=("spawn",),
    )

    assert device_level_calls == [(False, config.server.version or "16.6.6")]
    assert seen_preferred_apps == [
        ("16.5.9", DEFAULT_DEVICE_TEST_APP_ID),
        ("17.0.1", DEFAULT_DEVICE_TEST_APP_ID),
    ]
    assert [result.app for result in summaries[0].results] == [DEFAULT_DEVICE_TEST_APP_ID, DEFAULT_DEVICE_TEST_APP_ID]


def test_run_device_compat_scan_reports_spawn_failures(monkeypatch) -> None:
    repo_root = REPO_ROOT
    config = build_device_doctor_config(repo_root, app=None)

    class FakeHelper:
        def __init__(self, repo_root, env, serial, *, python_executable, frida_version, remote_host, remote_servername):
            self.serial = serial
            self.frida_version = frida_version

        def current_frida_version(self) -> str:
            return self.frida_version

        def resolve_device_app(
            self,
            *,
            explicit_app: str | None = None,
            timeout: int = 30,
            require_attach: bool = False,
            attempt_reporter=None,
        ) -> tuple[str, str]:
            return explicit_app or DEFAULT_DEVICE_TEST_APP_ID, "default-test-app"

    monkeypatch.setattr(
        "frida_analykit.development.device_compat.list_managed_frida_envs",
        lambda repo_root: (
            SimpleNamespace(frida_version="17.9.1", python_path=Path("/tmp/env-17.9.1"), source="repo"),
        ),
    )
    monkeypatch.setattr("frida_analykit.development.device_compat.derive_remote_host", lambda serial: "127.0.0.1:31123")
    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceHelpers", FakeHelper)
    monkeypatch.setattr(
        "frida_analykit.development.device_compat._run_version_probe_suite",
        lambda helper, *, configured_app, preferred_app, probe_kinds, stage_reporter=None: (
            preferred_app or DEFAULT_DEVICE_TEST_APP_ID,
            {"spawn": DeviceCompatProbeError("spawn", "unable to pick a payload base")},
        ),
    )

    summaries = run_device_compat_scan(
        repo_root,
        env={},
        config=config,
        serials=("SERIAL123",),
        requested_versions=("17.9.1",),
        probe_kinds=("spawn",),
    )

    result = summaries[0].results[0]
    assert result.status == "fail"
    assert result.stage == "spawn"
    assert "unable to pick a payload base" in result.detail


def test_run_version_probe_suite_retries_transient_spawn_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_calls: list[tuple[str, object]] = []
    stages: list[tuple[str, str | None]] = []

    class FakeRuntime:
        def __init__(self, helper) -> None:
            runtime_calls.append(("init", helper.serial))

        def ensure_installed(self, config_path: Path) -> None:
            runtime_calls.append(("install", config_path))

        def ensure_running(self, config_path: Path, *, timeout: int = 30) -> None:
            runtime_calls.append(("ensure_running", (config_path, timeout)))

        def invalidate(self) -> None:
            runtime_calls.append(("invalidate", None))

        def stop(self) -> None:
            runtime_calls.append(("stop", None))

    class FakeHelper:
        serial = "SERIAL123"

        def create_workspace(self, root: Path, *, app: str | None, agent_source: str):
            return SimpleNamespace(config_path=root / "config.yml")

        def _probe_remote_ready(self):
            return None

    probe_results = iter(
        [
            DeviceCompatProbeError("spawn", "frida.TimedOutError: unexpectedly timed out while waiting for signal"),
            {"ping": "ok"},
        ]
    )

    def fake_run_spawn_probe(helper, workspace_config: Path, *, package: str):
        result = next(probe_results)
        if isinstance(result, DeviceCompatProbeError):
            raise result
        return result

    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceServerRuntime", FakeRuntime)
    monkeypatch.setattr("frida_analykit.development.device_compat._run_spawn_probe", fake_run_spawn_probe)
    monkeypatch.setattr("frida_analykit.development.device_compat.time.sleep", lambda _: None)

    selected_app, probe_results_map = _run_version_probe_suite(
        FakeHelper(),
        configured_app=None,
        preferred_app="com.demo",
        probe_kinds=("spawn",),
        stage_reporter=lambda stage, detail=None: stages.append((stage, detail)),
    )

    assert selected_app == "com.demo"
    assert probe_results_map["spawn"] == {"ping": "ok"}
    assert runtime_calls == [
        ("init", "SERIAL123"),
        ("install", Path(runtime_calls[1][1])),
        ("ensure_running", (Path(runtime_calls[2][1][0]), 60)),
        ("ensure_running", (Path(runtime_calls[3][1][0]), 60)),
        ("invalidate", None),
        ("ensure_running", (Path(runtime_calls[5][1][0]), 60)),
        ("stop", None),
    ]
    assert stages == [
        ("install", None),
        ("boot", None),
        ("spawn", "spawning `com.demo`"),
        ("recover", "spawn retry 2/2 after transient spawn failure"),
        ("spawn", "retry 2/2: spawning `com.demo`"),
    ]


def test_run_version_probe_suite_surfaces_boot_failure_after_runtime_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_calls: list[tuple[str, object]] = []
    stages: list[tuple[str, str | None]] = []

    class FakeRuntime:
        def __init__(self, helper) -> None:
            runtime_calls.append(("init", helper.serial))

        def ensure_installed(self, config_path: Path) -> None:
            runtime_calls.append(("install", config_path))

        def ensure_running(self, config_path: Path, *, timeout: int = 30) -> None:
            runtime_calls.append(("ensure_running", (config_path, timeout)))
            raise RuntimeError("server boot exited before the remote endpoint became ready")

        def stop(self) -> None:
            runtime_calls.append(("stop", None))

    class FakeHelper:
        serial = "SERIAL123"

        def create_workspace(self, root: Path, *, app: str | None, agent_source: str):
            return SimpleNamespace(config_path=root / "config.yml")

    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceServerRuntime", FakeRuntime)
    monkeypatch.setattr("frida_analykit.development.device_compat._run_spawn_probe", lambda helper, workspace_config, *, package: {"ping": "ok"})

    with pytest.raises(DeviceCompatProbeError, match="server boot exited before the remote endpoint became ready") as excinfo:
        _run_version_probe_suite(
            FakeHelper(),
            configured_app=None,
            preferred_app="com.demo",
            probe_kinds=("spawn",),
            stage_reporter=lambda stage, detail=None: stages.append((stage, detail)),
        )

    assert excinfo.value.stage == "boot"
    assert runtime_calls == [
        ("init", "SERIAL123"),
        ("install", Path(runtime_calls[1][1])),
        ("ensure_running", (Path(runtime_calls[2][1][0]), 60)),
        ("stop", None),
    ]
    assert stages == [
        ("install", None),
        ("boot", None),
    ]


def test_run_version_probe_suite_does_not_retry_non_transient_spawn_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_calls: list[tuple[str, object]] = []

    class FakeRuntime:
        def __init__(self, helper) -> None:
            runtime_calls.append(("init", helper.serial))

        def ensure_installed(self, config_path: Path) -> None:
            runtime_calls.append(("install", config_path))

        def ensure_running(self, config_path: Path, *, timeout: int = 30) -> None:
            runtime_calls.append(("ensure_running", (config_path, timeout)))

        def invalidate(self) -> None:
            runtime_calls.append(("invalidate", None))

        def stop(self) -> None:
            runtime_calls.append(("stop", None))

    class FakeHelper:
        serial = "SERIAL123"

        def create_workspace(self, root: Path, *, app: str | None, agent_source: str):
            return SimpleNamespace(config_path=root / "config.yml")

        def _probe_remote_ready(self):
            return None

    monkeypatch.setattr("frida_analykit.development.device_compat.DeviceServerRuntime", FakeRuntime)
    monkeypatch.setattr(
        "frida_analykit.development.device_compat._run_spawn_probe",
        lambda helper, workspace_config, *, package: (_ for _ in ()).throw(
            DeviceCompatProbeError("spawn", "frida.NotSupportedError: unable to pick a payload base")
        ),
    )

    selected_app, probe_results_map = _run_version_probe_suite(
        FakeHelper(),
        configured_app=None,
        preferred_app="com.demo",
        probe_kinds=("spawn",),
    )

    assert selected_app == "com.demo"
    probe_error = probe_results_map["spawn"]
    assert isinstance(probe_error, DeviceCompatProbeError)
    assert probe_error.detail == "frida.NotSupportedError: unable to pick a payload base"
    assert runtime_calls == [
        ("init", "SERIAL123"),
        ("install", Path(runtime_calls[1][1])),
        ("ensure_running", (Path(runtime_calls[2][1][0]), 60)),
        ("ensure_running", (Path(runtime_calls[3][1][0]), 60)),
        ("stop", None),
    ]


def test_resolve_device_compat_serials_reports_doctor_specific_hint(monkeypatch) -> None:
    monkeypatch.setattr(
        "frida_analykit.device.selection.list_connected_android_devices",
        lambda **kwargs: (
            SimpleNamespace(serial="SERIAL123", state="device"),
            SimpleNamespace(serial="SERIAL456", state="device"),
        ),
    )

    with pytest.raises(RuntimeError, match="pass --serial <serial>, use --all-devices, or set ANDROID_SERIAL=<serial>"):
        resolve_device_compat_serials(
            explicit_serials=(),
            all_devices=False,
            config_serial=None,
            env_serial=None,
            env={},
            cwd=Path.cwd(),
        )
