from __future__ import annotations

import json
import textwrap

import pytest

PROBE_MARKER = "FRIDA_ANALYKIT_DEVICE_PROBE="


def _extract_probe_payload(stdout: str, stderr: str) -> dict[str, object]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(PROBE_MARKER):
            return json.loads(line[len(PROBE_MARKER) :])
    pytest.fail(f"probe result marker was not found\nstdout:\n{stdout}\nstderr:\n{stderr}")


def _run_repl_probe(
    device_helpers,
    workspace,
    body: str,
    *,
    pid: int | None = None,
) -> dict[str, object]:
    body_lines = textwrap.dedent(body).strip().splitlines()
    session_lines = [f"pid = {pid}"] if pid is not None else ["pid = device.spawn([config.app])"]
    if pid is None:
        session_lines.append("resume_pid = True")
    else:
        session_lines.append("resume_pid = False")
    script_lines = [
        "import asyncio",
        "import json",
        "",
        "from frida_analykit.compat import FridaCompat",
        "from frida_analykit.config import AppConfig",
        "from frida_analykit.repl import build_repl_namespace",
        "from frida_analykit.server import FridaServerManager",
        "from frida_analykit.session import SessionWrapper",
        "",
        f'config = AppConfig.from_yaml(r"{workspace.config_path}")',
        "FridaServerManager().ensure_remote_forward(config, action='device test probe')",
        "compat = FridaCompat()",
        "device = compat.get_device(config.server.host)",
        *session_lines,
        "session = SessionWrapper.from_session(device.attach(pid), config=config, interactive=True)",
        "script = session.open_script(str(config.jsfile))",
        "script.set_logger()",
        "script.load()",
        "if resume_pid:",
        "    device.resume(pid)",
        "",
        "async def main() -> dict[str, object]:",
        "    try:",
        "        repl_namespace = build_repl_namespace(",
        "            {",
        "                'config': config,",
        "                'device': device,",
        "                'pid': pid,",
        "                'session': session,",
        "                'script': script,",
        "            },",
        "            script=script,",
        "            global_names=config.script.repl.globals,",
        "        )",
        "        Process = repl_namespace.get('Process')",
        "        Module = repl_namespace.get('Module')",
        "        Memory = repl_namespace.get('Memory')",
        "        Java = repl_namespace.get('Java')",
        "        ObjC = repl_namespace.get('ObjC')",
        "        Swift = repl_namespace.get('Swift')",
        *[f"        {line}" if line else "" for line in body_lines],
        "    finally:",
        "        try:",
        "            session.detach()",
        "        except Exception:",
        "            pass",
        "",
        "payload = asyncio.run(main())",
        f"print({PROBE_MARKER!r} + json.dumps(payload, ensure_ascii=False))",
        "",
    ]
    script = "\n".join(script_lines)
    result = device_helpers.run_python_probe(script, timeout=240)
    assert result.returncode == 0, (
        "python probe failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return _extract_probe_payload(result.stdout, result.stderr)


@pytest.fixture(scope="session")
def device_repl_workspace(
    device_helpers,
    device_app: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> object:
    workspace_root = tmp_path_factory.mktemp("device-repl")
    tarball = device_helpers.pack_local_agent_runtime(workspace_root)
    workspace = device_helpers.create_ts_workspace_with_local_runtime(
        workspace_root,
        app=device_app,
        agent_package_spec=f"file:{tarball}",
    )
    device_helpers.build_workspace(workspace, install=True)
    return workspace


@pytest.fixture(scope="session")
def booted_device_repl_workspace(
    device_helpers,
    device_repl_workspace,
    device_session_guard,
) -> object:
    workspace = device_repl_workspace
    if workspace.log_path.exists():
        workspace.log_path.unlink()
    process = device_helpers.start_boot_process(workspace.config_path, force_restart=True)
    try:
        yield workspace
    finally:
        device_helpers.stop_boot_process(process, workspace.config_path)


@pytest.fixture(scope="session")
def running_device_repl_app_pid(
    device_helpers,
    device_app: str,
    booted_device_repl_workspace,
) -> int:
    device_helpers.force_stop_app(device_app, timeout=30)
    attach_pid, attach_error = device_helpers.find_attachable_app_pid(device_app, timeout=30)
    assert attach_pid is not None, attach_error
    return attach_pid


@pytest.mark.device
def test_repl_handle_process_seed_path_on_device(
    device_helpers,
    booted_device_repl_workspace,
    running_device_repl_app_pid: int,
) -> None:
    payload = _run_repl_probe(
        device_helpers,
        booted_device_repl_workspace,
        """
        proc = script.jsh("Process")
        return {
            "label": str(proc),
            "props": sorted(name for name in dir(proc) if name in {"arch", "platform"}),
        }
        """,
        pid=running_device_repl_app_pid,
    )

    assert payload["label"] == "Process"
    assert "arch" in payload["props"] or "platform" in payload["props"]


@pytest.mark.device
def test_repl_namespace_exposes_default_process_handle_on_device(
    device_helpers,
    booted_device_repl_workspace,
    running_device_repl_app_pid: int,
) -> None:
    payload = _run_repl_probe(
        device_helpers,
        booted_device_repl_workspace,
        """
        return {
            "label": str(Process),
            "thread_id": Process.getCurrentThreadId().value_,
        }
        """,
        pid=running_device_repl_app_pid,
    )

    assert payload["label"] == "Process"
    assert isinstance(payload["thread_id"], int)
    assert payload["thread_id"] > 0


@pytest.mark.device
def test_repl_namespace_respects_removed_globals_on_device(
    device_helpers,
    booted_device_repl_workspace,
    running_device_repl_app_pid: int,
) -> None:
    payload = _run_repl_probe(
        device_helpers,
        booted_device_repl_workspace,
        """
        config.script.repl.globals = []
        empty_namespace = build_repl_namespace(
            {
                "config": config,
                "device": device,
                "pid": pid,
                "session": session,
                "script": script,
            },
            script=script,
            global_names=config.script.repl.globals,
        )
        return {
            "has_process": "Process" in empty_namespace,
        }
        """,
        pid=running_device_repl_app_pid,
    )

    assert payload["has_process"] is False


@pytest.mark.device
def test_repl_handle_scope_root_sync_call_and_value_on_device(
    device_helpers,
    booted_device_repl_workspace,
    running_device_repl_app_pid: int,
) -> None:
    payload = _run_repl_probe(
        device_helpers,
        booted_device_repl_workspace,
        """
        return {
            "thread_id": script.eval("Process").getCurrentThreadId().value_,
        }
        """,
        pid=running_device_repl_app_pid,
    )

    assert isinstance(payload["thread_id"], int)
    assert payload["thread_id"] > 0


@pytest.mark.device
def test_repl_handle_async_eval_and_resolve_on_device(
    device_helpers,
    booted_device_repl_workspace,
    running_device_repl_app_pid: int,
) -> None:
    payload = _run_repl_probe(
        device_helpers,
        booted_device_repl_workspace,
        """
        handle = await script.eval_async("Promise.resolve(Process.arch)")
        return {
            "arch": await handle.resolve_async(),
        }
        """,
        pid=running_device_repl_app_pid,
    )

    assert isinstance(payload["arch"], str)
    assert payload["arch"]


@pytest.mark.device
def test_repl_handle_scope_root_async_call_on_device(
    device_helpers,
    booted_device_repl_workspace,
    running_device_repl_app_pid: int,
) -> None:
    payload = _run_repl_probe(
        device_helpers,
        booted_device_repl_workspace,
        """
        handle = script.eval("Process").getCurrentThreadId
        result = await handle.call_async()
        return {
            "thread_id": await result.resolve_async(),
        }
        """,
        pid=running_device_repl_app_pid,
    )

    assert isinstance(payload["thread_id"], int)
    assert payload["thread_id"] > 0
