from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from frida_analykit.device import test_app as test_app_module
from frida_analykit.device import (
    DEFAULT_DEVICE_TEST_APP_ID,
    build_device_test_app,
    get_device_test_app_apk_path,
    get_device_test_app_project_dir,
    install_device_test_app,
    install_device_test_app_all,
    install_device_test_app_only,
    resolve_test_app_install_serials,
)


def test_default_device_test_app_project_uses_expected_package_id() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    project_dir = get_device_test_app_project_dir(repo_root)
    keystore_path = project_dir / "keystore" / "device-test-debug.keystore"
    build_gradle = (project_dir / "app" / "build.gradle").read_text(encoding="utf-8")

    assert project_dir == repo_root / "tests" / "android_test_app"
    assert (project_dir / "gradlew").is_file()
    assert (project_dir / "gradle" / "wrapper" / "gradle-wrapper.jar").is_file()
    assert keystore_path.is_file()
    assert DEFAULT_DEVICE_TEST_APP_ID in build_gradle
    assert 'storeFile deviceTestKeystoreFile' in build_gradle
    assert 'signingConfig signingConfigs.debug' in build_gradle
    assert DEFAULT_DEVICE_TEST_APP_ID in (project_dir / "app" / "src" / "main" / "AndroidManifest.xml").read_text(
        encoding="utf-8"
    )


def test_build_device_test_app_uses_gradle_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    project_dir = repo_root / "tests" / "android_test_app"
    apk_path = get_device_test_app_apk_path(repo_root)
    (project_dir / "gradle" / "wrapper").mkdir(parents=True)
    (project_dir / "app" / "build" / "outputs" / "apk" / "debug").mkdir(parents=True)
    (project_dir / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    apk_path.write_text("apk", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("frida_analykit.device.test_app.subprocess.run", fake_run)

    built_apk = build_device_test_app(repo_root, env={"BASE_ENV": "1"}, timeout=123)

    assert built_apk == apk_path
    assert captured["args"] == ([str(project_dir / "gradlew"), "assembleDebug"],)
    assert captured["kwargs"]["cwd"] == project_dir
    assert captured["kwargs"]["env"]["BASE_ENV"] == "1"
    assert "JAVA_HOME" in captured["kwargs"]["env"]
    assert captured["kwargs"]["timeout"] == 123


def test_prepare_tool_env_overrides_invalid_java_home_with_resolved_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "frida_analykit.device.test_app._resolve_java_home",
        lambda env: "/resolved/java",
    )

    prepared = test_app_module._prepare_tool_env(
        {
            "JAVA_HOME": "/broken/java",
            "PATH": "/usr/bin",
        }
    )

    assert prepared["JAVA_HOME"] == "/resolved/java"
    assert prepared["PATH"].split(os.pathsep)[0] == "/resolved/java/bin"


def test_prepare_tool_env_keeps_valid_java_home(
    tmp_path: Path,
) -> None:
    java_home = tmp_path / "jdk"
    (java_home / "bin").mkdir(parents=True)
    (java_home / "bin" / "java").write_text("", encoding="utf-8")

    prepared = test_app_module._prepare_tool_env(
        {
            "JAVA_HOME": str(java_home),
            "PATH": "/usr/bin",
        }
    )

    assert prepared["JAVA_HOME"] == str(java_home)
    assert prepared["PATH"].split(os.pathsep)[0] == str(java_home / "bin")


def test_install_device_test_app_builds_then_installs_to_serial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    apk_path = repo_root / "tests" / "android_test_app" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    apk_path.parent.mkdir(parents=True)
    apk_path.write_text("apk", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr("frida_analykit.device.test_app.build_device_test_app", lambda *args, **kwargs: apk_path)

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="Success\n", stderr="")

    monkeypatch.setattr("frida_analykit.device.test_app.subprocess.run", fake_run)

    installed_apk = install_device_test_app("SERIAL123", repo_root, env={"BASE_ENV": "1"}, install_timeout=45)

    assert installed_apk == apk_path
    assert captured["args"] == (["adb", "-s", "SERIAL123", "install", "-r", str(apk_path)],)
    assert captured["kwargs"]["cwd"] == repo_root
    assert captured["kwargs"]["env"]["BASE_ENV"] == "1"
    assert "JAVA_HOME" in captured["kwargs"]["env"]
    assert captured["kwargs"]["timeout"] == 45


def test_install_device_test_app_only_installs_existing_apk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    apk_path = repo_root / "app-debug.apk"
    apk_path.write_text("apk", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="Success\n", stderr="")

    monkeypatch.setattr("frida_analykit.device.test_app.subprocess.run", fake_run)

    install_device_test_app_only("SERIAL123", apk_path, repo_root, env={"BASE_ENV": "1"}, install_timeout=67)

    assert captured["args"] == (["adb", "-s", "SERIAL123", "install", "-r", str(apk_path)],)
    assert captured["kwargs"]["cwd"] == repo_root
    assert captured["kwargs"]["env"]["BASE_ENV"] == "1"
    assert captured["kwargs"]["timeout"] == 67


def test_resolve_test_app_install_serials_prefers_requested_serials(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "frida_analykit.device.test_app.resolve_device_serials",
        lambda requested_serials, **kwargs: captured.update(requested_serials=requested_serials, kwargs=kwargs)
        or ("SERIAL123", "SERIAL456"),
    )

    resolved = resolve_test_app_install_serials(
        requested_serials=("SERIAL123", "SERIAL456"),
        fallback_serial="IGNORED",
        adb_executable="adb-custom",
        env={"BASE_ENV": "1"},
        cwd=Path("/tmp/repo"),
    )

    assert resolved == ("SERIAL123", "SERIAL456")
    assert captured["requested_serials"] == ("SERIAL123", "SERIAL456")
    assert captured["kwargs"]["all_devices"] is False
    assert captured["kwargs"]["fallback_serial"] == "IGNORED"
    assert captured["kwargs"]["adb_executable"] == "adb-custom"
    assert captured["kwargs"]["env"] == {"BASE_ENV": "1"}


def test_install_device_test_app_all_builds_once_and_installs_every_serial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    apk_path = repo_root / "app-debug.apk"
    apk_path.write_text("apk", encoding="utf-8")
    build_calls: list[Path] = []
    install_calls: list[tuple[str, Path]] = []
    output = io.StringIO()

    monkeypatch.setattr(
        "frida_analykit.device.test_app.build_device_test_app",
        lambda repo_root, **kwargs: build_calls.append(repo_root) or apk_path,
    )
    monkeypatch.setattr(
        "frida_analykit.device.test_app.install_device_test_app_only",
        lambda serial, apk_path, repo_root, **kwargs: install_calls.append((serial, apk_path)),
    )

    installed_apk = install_device_test_app_all(
        ("SERIAL123", "SERIAL456"),
        repo_root,
        env={"BASE_ENV": "1"},
        output=output,
    )

    assert installed_apk == apk_path
    assert build_calls == [repo_root]
    assert install_calls == [
        ("SERIAL123", apk_path),
        ("SERIAL456", apk_path),
    ]
    rendered = output.getvalue()
    assert "[SERIAL123] installing app-debug.apk" in rendered
    assert "[SERIAL123] install succeeded" in rendered
    assert "[SERIAL456] install succeeded" in rendered


def test_install_device_test_app_all_returns_error_when_any_install_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    apk_path = repo_root / "app-debug.apk"
    apk_path.write_text("apk", encoding="utf-8")
    output = io.StringIO()

    monkeypatch.setattr(
        "frida_analykit.device.test_app.build_device_test_app",
        lambda repo_root, **kwargs: apk_path,
    )

    def fake_install(serial, apk_path, repo_root, **kwargs):
        if serial == "SERIAL456":
            raise RuntimeError("boom")

    monkeypatch.setattr("frida_analykit.device.test_app.install_device_test_app_only", fake_install)

    with pytest.raises(RuntimeError, match="one or more devices"):
        install_device_test_app_all(("SERIAL123", "SERIAL456"), repo_root, output=output)

    rendered = output.getvalue()
    assert "[SERIAL123] install succeeded" in rendered
    assert "[SERIAL456] boom" in rendered
