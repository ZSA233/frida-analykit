from __future__ import annotations

import pytest


@pytest.mark.device
def test_server_stop_is_idempotent(device_helpers, device_admin_workspace) -> None:
    workspace = device_admin_workspace

    first = device_helpers.run_cli(["server", "stop", "--config", str(workspace.config_path)], timeout=60)
    second = device_helpers.run_cli(["server", "stop", "--config", str(workspace.config_path)], timeout=60)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "no matching remote frida-server was running" in second.stdout


@pytest.mark.device
def test_server_boot_force_restart_recovers_after_local_exit(
    device_helpers,
    device_admin_workspace,
    device_server_runtime,
) -> None:
    workspace = device_admin_workspace
    # The shared session runtime keeps frida-server alive for ordinary tests.
    # This lifecycle test manages boot/stop manually, so start from a clean
    # slate instead of racing the long-lived runtime's boot child.
    device_server_runtime.stop(workspace.config_path)
    process = device_helpers.start_boot_process(workspace.config_path, force_restart=True)
    restarted = None

    try:
        conflict = device_helpers.run_cli(["server", "boot", "--config", str(workspace.config_path)], timeout=30)
        assert conflict.returncode != 0
        assert "already running" in (conflict.stdout + conflict.stderr)

        process.kill()
        process.wait(timeout=10)

        restarted = device_helpers.start_boot_process(workspace.config_path, force_restart=True)
        device_helpers.wait_for_remote_ready()
    finally:
        if restarted is not None:
            device_helpers.stop_boot_process(restarted, workspace.config_path)
        else:
            device_helpers.run_cli(["server", "stop", "--config", str(workspace.config_path)], timeout=60)
        device_server_runtime.invalidate()
