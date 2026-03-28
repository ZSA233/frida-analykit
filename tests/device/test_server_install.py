from __future__ import annotations

import os

import pytest


@pytest.mark.device
def test_server_install_with_version(device_helpers, tmp_path) -> None:
    workspace = device_helpers.create_workspace(tmp_path, app=None)

    result = device_helpers.run_cli(
        [
            "server",
            "install",
            "--config",
            str(workspace.config_path),
            "--version",
            device_helpers.frida_version,
        ],
        timeout=300,
    )

    assert result.returncode == 0, result.stderr
    assert "installed frida-server" in result.stdout
    assert "device abi:" in result.stdout


@pytest.mark.device
def test_server_install_with_local_server(device_helpers, tmp_path) -> None:
    local_server = os.environ.get("FRIDA_ANALYKIT_DEVICE_LOCAL_SERVER")
    if not local_server:
        pytest.skip("set FRIDA_ANALYKIT_DEVICE_LOCAL_SERVER=<path> to test --local-server installs")

    workspace = device_helpers.create_workspace(tmp_path, app=None)
    result = device_helpers.run_cli(
        [
            "server",
            "install",
            "--config",
            str(workspace.config_path),
            "--local-server",
            local_server,
        ],
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert "installed frida-server" in result.stdout
    assert f"local source: {local_server}" in result.stdout
