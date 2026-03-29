from __future__ import annotations

import json
import textwrap
from collections.abc import Iterator

import pytest

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conftest import DeviceHelpers, DeviceWorkspace


PROBE_MARKER = "FRIDA_ANALYKIT_AGENT_UNIT_PROBE="
AGENT_UNIT_ENTRY_SOURCE = """\
import "@zsa233/frida-analykit-agent/rpc"
import { installAgentUnitRpcExports } from "@zsa233/frida-analykit-agent-device-tests"

installAgentUnitRpcExports()
"""


def _extract_probe_payload(stdout: str, stderr: str) -> dict[str, object]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(PROBE_MARKER):
            return json.loads(line[len(PROBE_MARKER) :])
    pytest.fail(f"probe result marker was not found\nstdout:\n{stdout}\nstderr:\n{stderr}")


def _run_agent_unit_probe(
    device_helpers: 'DeviceHelpers',
    workspace,
    suite: str,
    *,
    pid: int | None = None,
) -> dict[str, object]:
    session_lines = [f"pid = {pid}"] if pid is not None else ["pid = device.spawn([config.app])"]
    if pid is None:
        session_lines.append("resume_pid = True")
    else:
        session_lines.append("resume_pid = False")
    script = "\n".join(
        [
            "import json",
            "",
            "from frida_analykit.compat import FridaCompat",
            "from frida_analykit.config import AppConfig",
            "from frida_analykit.server import FridaServerManager",
            "from frida_analykit.session import SessionWrapper",
            "",
            f'config = AppConfig.from_yaml(r"{workspace.config_path}")',
            "FridaServerManager().ensure_remote_forward(config, action='device agent unit probe')",
            "compat = FridaCompat()",
            "device = compat.get_device(config.server.host)",
            *session_lines,
            "session = SessionWrapper.from_session(device.attach(pid), config=config, interactive=False)",
            "script = session.open_script(str(config.jsfile))",
            "script.set_logger()",
            "script.load()",
            "if resume_pid:",
            "    device.resume(pid)",
            "try:",
            "    payload = {",
            "        'exports': sorted(script.list_exports_sync()),",
            "        'suites': script.exports_sync.list_agent_unit_suites(),",
            f"        'result': script.exports_sync.run_agent_unit_suite({suite!r}),",
            "    }",
            "finally:",
            "    try:",
            "        session.detach()",
            "    except Exception:",
            "        pass",
            f"print({PROBE_MARKER!r} + json.dumps(payload, ensure_ascii=False))",
            "",
        ]
    )
    result = device_helpers.run_python_probe(textwrap.dedent(script), timeout=240)
    assert result.returncode == 0, (
        "python probe failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return _extract_probe_payload(result.stdout, result.stderr)


@pytest.fixture(scope="session")
def device_agent_unit_workspace(
    device_helpers: 'DeviceHelpers',
    device_app: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> object:
    workspace_root = tmp_path_factory.mktemp("device-agent-unit")
    runtime_tarball = device_helpers.pack_local_package(
        workspace_root,
        device_helpers.repo_root / "packages" / "frida-analykit-agent",
    )
    test_tarball = device_helpers.pack_local_package(
        workspace_root,
        device_helpers.repo_root / "packages" / "frida-analykit-agent-device-tests",
    )
    workspace = device_helpers.create_ts_workspace_with_local_runtime(
        workspace_root,
        app=device_app,
        agent_package_spec=f"file:{runtime_tarball}",
        entry_source=AGENT_UNIT_ENTRY_SOURCE,
        extra_dependencies={
            "@zsa233/frida-analykit-agent-device-tests": f"file:{test_tarball}",
        },
    )
    device_helpers.build_workspace(workspace, install=True)
    return workspace


@pytest.fixture(scope="session")
def booted_device_agent_unit_workspace(
    device_helpers: 'DeviceHelpers',
    device_agent_unit_workspace,
    device_session_guard,
) -> Iterator[object]:
    workspace = device_agent_unit_workspace
    if workspace.log_path.exists():
        workspace.log_path.unlink()
    process = device_helpers.start_boot_process(workspace.config_path, force_restart=True)
    try:
        yield workspace
    finally:
        device_helpers.stop_boot_process(process, workspace.config_path)


@pytest.fixture(scope="session")
def running_device_agent_unit_app_pid(
    device_helpers: 'DeviceHelpers',
    device_app: str,
    booted_device_agent_unit_workspace,
) -> int:
    device_helpers.force_stop_app(device_app, timeout=30)
    attach_pid, attach_error = device_helpers.find_attachable_app_pid(device_app, timeout=30)
    assert attach_pid is not None, attach_error
    return attach_pid


@pytest.mark.device
def test_agent_unit_runner_reports_jni_wrapper_suite_on_device(
    device_helpers: 'DeviceHelpers',
    booted_device_agent_unit_workspace,
    running_device_agent_unit_app_pid: int,
) -> None:
    payload = _run_agent_unit_probe(
        device_helpers,
        booted_device_agent_unit_workspace,
        "jni_env_wrappers",
        pid=running_device_agent_unit_app_pid,
    )

    exports = payload["exports"]
    suites = payload["suites"]
    result = payload["result"]

    assert "rpc_runtime_info" in exports
    assert "list_agent_unit_suites" in exports
    assert "run_agent_unit_suite" in exports
    assert suites == [
        "jni_env_wrappers",
        "jni_member_facade",
        "jni_member_facade_arrays",
        "jni_member_facade_nonvirtual",
    ]

    assert result["suite"] == "jni_env_wrappers"
    assert result["failed"] == 0
    assert result["passed"] >= 10
    for case in result["cases"]:
        assert case["ok"] is True, case


@pytest.mark.device
def test_agent_unit_runner_reports_member_facade_suite_on_device(
    device_helpers: 'DeviceHelpers',
    booted_device_agent_unit_workspace,
    running_device_agent_unit_app_pid: int,
) -> None:
    payload = _run_agent_unit_probe(
        device_helpers,
        booted_device_agent_unit_workspace,
        "jni_member_facade",
        pid=running_device_agent_unit_app_pid,
    )

    suites = payload["suites"]
    result = payload["result"]

    assert suites == [
        "jni_env_wrappers",
        "jni_member_facade",
        "jni_member_facade_arrays",
        "jni_member_facade_nonvirtual",
    ]
    assert result["suite"] == "jni_member_facade"
    assert result["failed"] == 0
    assert result["passed"] >= 9
    for case in result["cases"]:
        assert case["ok"] is True, case


@pytest.mark.device
def test_agent_unit_runner_reports_array_member_facade_suite_on_device(
    device_helpers: 'DeviceHelpers',
    booted_device_agent_unit_workspace,
    running_device_agent_unit_app_pid: int,
) -> None:
    payload = _run_agent_unit_probe(
        device_helpers,
        booted_device_agent_unit_workspace,
        "jni_member_facade_arrays",
        pid=running_device_agent_unit_app_pid,
    )

    suites = payload["suites"]
    result = payload["result"]

    assert suites == [
        "jni_env_wrappers",
        "jni_member_facade",
        "jni_member_facade_arrays",
        "jni_member_facade_nonvirtual",
    ]
    assert result["suite"] == "jni_member_facade_arrays"
    assert result["failed"] == 0
    assert result["passed"] >= 2
    for case in result["cases"]:
        assert case["ok"] is True, case


@pytest.mark.device
def test_agent_unit_runner_reports_nonvirtual_member_facade_suite_on_device(
    device_helpers: 'DeviceHelpers',
    booted_device_agent_unit_workspace,
    running_device_agent_unit_app_pid: int,
) -> None:
    payload = _run_agent_unit_probe(
        device_helpers,
        booted_device_agent_unit_workspace,
        "jni_member_facade_nonvirtual",
        pid=running_device_agent_unit_app_pid,
    )

    suites = payload["suites"]
    result = payload["result"]

    assert suites == [
        "jni_env_wrappers",
        "jni_member_facade",
        "jni_member_facade_arrays",
        "jni_member_facade_nonvirtual",
    ]
    assert result["suite"] == "jni_member_facade_nonvirtual"
    assert result["failed"] == 0
    assert result["passed"] >= 2
    for case in result["cases"]:
        assert case["ok"] is True, case
