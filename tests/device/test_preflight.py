from __future__ import annotations

import pytest


@pytest.mark.device
def test_device_preflight(device_helpers, device_app, tmp_path) -> None:
    state = device_helpers.adb_run(["get-state"])
    assert state.returncode == 0, state.stderr
    assert state.stdout.strip() == "device"

    assert device_helpers.current_frida_version() == device_helpers.frida_version

    package_probe = device_helpers.adb_run(["shell", "pm", "path", device_app])
    assert package_probe.returncode == 0, package_probe.stderr
    assert "package:" in package_probe.stdout

    workspace = device_helpers.create_workspace(tmp_path, app=device_app)
    assert workspace.agent_path.exists()
    assert workspace.config_path.exists()
    assert f"version: {device_helpers.frida_version}" in workspace.config_path.read_text(encoding="utf-8")
