from __future__ import annotations

import json
import textwrap
import time
from collections.abc import Iterator

import pytest

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conftest import DeviceHelpers, DeviceWorkspace


PROBE_MARKER = "FRIDA_ANALYKIT_AGENT_UNIT_PROBE="
DEX_DUMP_CASE = "dump_all_dex_streams_to_python_handler"
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


def _suite_case_detail(result: dict[str, object], case_name: str) -> str:
    for case in result["cases"]:
        assert isinstance(case, dict)
        if case.get("name") == case_name:
            detail = case.get("detail")
            assert isinstance(detail, str), f"expected detail for case {case_name}, got {detail!r}"
            return detail
    pytest.fail(f"case `{case_name}` was not found in result: {result}")


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
        "dex_tools",
        "helper_core",
        "helper_runtime",
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
        "dex_tools",
        "helper_core",
        "helper_runtime",
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
        "dex_tools",
        "helper_core",
        "helper_runtime",
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
        "dex_tools",
        "helper_core",
        "helper_runtime",
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


@pytest.mark.device
def test_agent_unit_runner_reports_helper_core_suite_on_device(
    device_helpers: 'DeviceHelpers',
    booted_device_agent_unit_workspace,
    running_device_agent_unit_app_pid: int,
) -> None:
    payload = _run_agent_unit_probe(
        device_helpers,
        booted_device_agent_unit_workspace,
        "helper_core",
        pid=running_device_agent_unit_app_pid,
    )

    suites = payload["suites"]
    result = payload["result"]

    assert suites == [
        "dex_tools",
        "helper_core",
        "helper_runtime",
        "jni_env_wrappers",
        "jni_member_facade",
        "jni_member_facade_arrays",
        "jni_member_facade_nonvirtual",
    ]
    assert result["suite"] == "helper_core"
    assert result["failed"] == 0
    assert result["passed"] >= 5
    for case in result["cases"]:
        assert case["ok"] is True, case


@pytest.mark.device
def test_agent_unit_runner_reports_dex_tools_suite_on_device(
    device_helpers: 'DeviceHelpers',
    booted_device_agent_unit_workspace,
    running_device_agent_unit_app_pid: int,
) -> None:
    payload = _run_agent_unit_probe(
        device_helpers,
        booted_device_agent_unit_workspace,
        "dex_tools",
        pid=running_device_agent_unit_app_pid,
    )

    suites = payload["suites"]
    result = payload["result"]

    assert suites == [
        "dex_tools",
        "helper_core",
        "helper_runtime",
        "jni_env_wrappers",
        "jni_member_facade",
        "jni_member_facade_arrays",
        "jni_member_facade_nonvirtual",
    ]
    assert result["suite"] == "dex_tools"
    assert result["failed"] == 0
    assert result["passed"] >= 2
    for case in result["cases"]:
        assert case["ok"] is True, case

    dump_detail = json.loads(_suite_case_detail(result, DEX_DUMP_CASE))
    expected_count = int(dump_detail["dexCount"])
    dump_dir = booted_device_agent_unit_workspace.root / "data" / "dextools" / str(dump_detail["tag"])
    manifest_path = dump_dir / "classes.json"

    deadline = time.monotonic() + 30
    manifest: list[dict[str, object]] = []
    dex_files = []
    while time.monotonic() < deadline:
        dex_files = sorted(dump_dir.glob("classes*.dex"))
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if len(manifest) == expected_count and len(dex_files) == expected_count:
                break
        time.sleep(1)
    else:
        pytest.fail(
            "timed out waiting for dex dump outputs\n"
            f"dump_dir={dump_dir}\n"
            f"manifest_exists={manifest_path.exists()}\n"
            f"dex_files={[path.name for path in dex_files]}"
        )

    assert dump_dir.is_dir()
    assert len(manifest) == expected_count
    assert len(dex_files) == expected_count
    assert {item["output_name"] for item in manifest} == {path.name for path in dex_files}
    assert all(path.stat().st_size > 0 for path in dex_files)


@pytest.mark.device
def test_agent_unit_runner_reports_helper_runtime_suite_on_device(
    device_helpers: 'DeviceHelpers',
    booted_device_agent_unit_workspace,
    running_device_agent_unit_app_pid: int,
) -> None:
    payload = _run_agent_unit_probe(
        device_helpers,
        booted_device_agent_unit_workspace,
        "helper_runtime",
        pid=running_device_agent_unit_app_pid,
    )

    suites = payload["suites"]
    result = payload["result"]

    assert suites == [
        "dex_tools",
        "helper_core",
        "helper_runtime",
        "jni_env_wrappers",
        "jni_member_facade",
        "jni_member_facade_arrays",
        "jni_member_facade_nonvirtual",
    ]
    assert result["suite"] == "helper_runtime"
    assert result["failed"] == 0
    assert result["passed"] >= 5
    for case in result["cases"]:
        assert case["ok"] is True, case
