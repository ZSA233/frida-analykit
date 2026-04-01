from __future__ import annotations

import pytest


@pytest.mark.device
@pytest.mark.device_app
def test_injection_writes_device_marker(
    device_helpers,
    booted_device_workspace,
    device_app,
    device_server_ready,
) -> None:
    workspace = booted_device_workspace
    attempts: list[str] = []

    attach_pid, attach_probe_error = device_helpers.find_attachable_app_pid(
        device_app,
        timeout=30,
        recover_remote=lambda: device_server_ready.ensure_running(workspace.config_path, timeout=60),
    )
    if attach_pid is not None:
        attach_result = device_helpers.run_cli(
            ["attach", "--config", str(workspace.config_path), "--pid", str(attach_pid), "--detach-on-load"],
            timeout=120,
        )
        if attach_result.returncode == 0:
            log_output = device_helpers.wait_for_log_contains(workspace.log_path, "FRIDA_ANALYKIT_DEVICE_OK")
            combined = attach_result.stdout + attach_result.stderr + log_output
            assert "FRIDA_ANALYKIT_DEVICE_OK" in combined
            assert "device-ok" in combined
            return
        attempts.append(
            "attach failed\n"
            f"pid: {attach_pid}\n"
            f"stdout:\n{attach_result.stdout}\n"
            f"stderr:\n{attach_result.stderr}"
        )
    else:
        attempts.append(f"attach unavailable: {attach_probe_error}")

    if workspace.log_path.exists():
        workspace.log_path.unlink()
    device_helpers.force_stop_app(device_app, timeout=30)
    spawn_result = device_helpers.run_cli(
        ["spawn", "--config", str(workspace.config_path), "--detach-on-load"],
        timeout=120,
    )
    if spawn_result.returncode == 0:
        log_output = device_helpers.wait_for_log_contains(workspace.log_path, "FRIDA_ANALYKIT_DEVICE_OK")
        combined = spawn_result.stdout + spawn_result.stderr + log_output
        assert "FRIDA_ANALYKIT_DEVICE_OK" in combined
        assert "device-ok" in combined
        return

    attempts.append(
        "spawn failed\n"
        f"stdout:\n{spawn_result.stdout}\n"
        f"stderr:\n{spawn_result.stderr}"
    )
    pytest.fail("\n\n".join(attempts))
