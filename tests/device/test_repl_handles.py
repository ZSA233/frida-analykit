from __future__ import annotations

import json
import textwrap

import pytest

PROBE_MARKER = "FRIDA_ANALYKIT_DEVICE_PROBE="
pytestmark = pytest.mark.device_app


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
    script_mode: str = "sync",
) -> dict[str, object]:
    body_lines = textwrap.dedent(body).strip().splitlines()
    session_lines = [f"pid = {pid}"] if pid is not None else ["pid = device.spawn([config.app])"]
    if pid is None:
        session_lines.append("resume_pid = True")
    else:
        session_lines.append("resume_pid = False")
    if script_mode == "sync":
        open_script_line = "script = session.open_script(str(config.jsfile))"
        repl_lines = [
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
        ]
    elif script_mode == "async":
        open_script_line = "script = session.open_script_async(str(config.jsfile))"
        repl_lines = [
            "        Process = None",
            "        Module = None",
            "        Memory = None",
            "        Java = None",
            "        ObjC = None",
            "        Swift = None",
        ]
    else:
        raise ValueError(f"unsupported script_mode: {script_mode}")

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
        open_script_line,
        "script.set_logger()",
        "script.load()",
        "if resume_pid:",
        "    device.resume(pid)",
        "",
        "async def main() -> dict[str, object]:",
        "    try:",
        *repl_lines,
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


@pytest.fixture
def booted_device_repl_workspace(
    device_helpers,
    device_repl_workspace,
    device_app: str,
    device_server_ready,
) -> object:
    workspace = device_repl_workspace
    if workspace.log_path.exists():
        workspace.log_path.unlink()
    attach_pid, attach_error = device_helpers.find_attachable_app_pid(
        device_app,
        timeout=60,
        recover_remote=lambda: device_server_ready.ensure_running(workspace.config_path, timeout=60),
    )
    assert attach_pid is not None, attach_error
    yield workspace


@pytest.fixture
def running_device_repl_app_pid(
    device_helpers,
    device_app: str,
    booted_device_repl_workspace,
    device_server_ready,
) -> int:
    workspace = booted_device_repl_workspace
    attach_pid, attach_error = device_helpers.find_attachable_app_pid(
        device_app,
        timeout=30,
        recover_remote=lambda: device_server_ready.ensure_running(workspace.config_path, timeout=60),
    )
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
def test_repl_handle_projectable_frida_object_value_on_device(
    device_helpers,
    booted_device_repl_workspace,
    running_device_repl_app_pid: int,
) -> None:
    payload = _run_repl_probe(
        device_helpers,
        booted_device_repl_workspace,
        """
        module_value = Process.findModuleByAddress(Process.mainModule.base).value_
        return {
            "name": module_value["name"],
            "path": module_value["path"],
            "base": module_value["base"],
            "size": module_value["size"],
        }
        """,
        pid=running_device_repl_app_pid,
    )

    assert isinstance(payload["name"], str)
    assert payload["name"]
    assert isinstance(payload["path"], str)
    assert payload["path"]
    assert isinstance(payload["base"], str)
    assert payload["base"]
    assert isinstance(payload["size"], int)
    assert payload["size"] > 0


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
        script_mode="async",
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
        handle = await script.eval_async("Process.getCurrentThreadId")
        result = await handle.call_async()
        return {
            "thread_id": await result.resolve_async(),
        }
        """,
        pid=running_device_repl_app_pid,
        script_mode="async",
    )

    assert isinstance(payload["thread_id"], int)
    assert payload["thread_id"] > 0
