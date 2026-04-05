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
pytestmark = pytest.mark.device_app
DEX_DUMP_CASE = "dump_all_dex_streams_to_python_handler"
ELF_DUMP_CASE = "dump_streams_to_python_session_dir"
ELF_PRESET_CASE = "enhanced_cast_exposes_getppid_preset"
EXPECTED_AGENT_UNIT_SUITES = [
    "dex_tools",
    "elf_tools",
    "helper_core",
    "helper_runtime",
    "jni_env_wrappers",
    "jni_member_facade",
    "jni_member_facade_arrays",
    "jni_member_facade_nonvirtual",
]
AGENT_UNIT_ENTRY_SOURCE = """\
import "@zsa233/frida-analykit-agent/rpc"
import { installAgentUnitRpcExports } from "@zsa233/frida-analykit-agent-device-tests"

installAgentUnitRpcExports()
"""

FIXUP_STAGE_ORDER = [
    "phdr-rebase",
    "dynamic-rebase",
    "dynsym-fixups",
    "relocation-fixups",
    "section-rebuild",
    "header-finalize",
]
SHT_RELA = 4
SHT_REL = 9
EM_386 = 3
EM_ARM = 40
EM_X86_64 = 62
EM_AARCH64 = 183
JUMP_SLOT_TYPES_BY_MACHINE = {
    EM_ARM: 22,
    EM_AARCH64: 1026,
    EM_386: 7,
    EM_X86_64: 7,
}
RELATIVE_TYPES_BY_MACHINE = {
    EM_ARM: 23,
    EM_AARCH64: 1027,
    EM_386: 8,
    EM_X86_64: 8,
}


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


def _read_elf_entry(data: bytes) -> int:
    assert len(data) >= 32, f"ELF header too small: {len(data)}"
    elf_class = data[4]
    if elf_class == 1:
        return int.from_bytes(data[24:28], "little")
    if elf_class == 2:
        return int.from_bytes(data[24:32], "little")
    pytest.fail(f"unsupported ELF class in fixed artifact: {elf_class}")


def _read_elf_machine(data: bytes) -> int:
    assert len(data) >= 20, f"ELF header too small: {len(data)}"
    return int.from_bytes(data[18:20], "little")


def _read_elf_layout(data: bytes) -> dict[str, int]:
    elf_class = data[4]
    if elf_class == 1:
        return {
            "elf_class": elf_class,
            "pointer_size": 4,
            "shoff": int.from_bytes(data[32:36], "little"),
            "shentsize": int.from_bytes(data[46:48], "little"),
            "shnum": int.from_bytes(data[48:50], "little"),
            "shstrndx": int.from_bytes(data[50:52], "little"),
        }
    if elf_class == 2:
        return {
            "elf_class": elf_class,
            "pointer_size": 8,
            "shoff": int.from_bytes(data[40:48], "little"),
            "shentsize": int.from_bytes(data[58:60], "little"),
            "shnum": int.from_bytes(data[60:62], "little"),
            "shstrndx": int.from_bytes(data[62:64], "little"),
        }
    pytest.fail(f"unsupported ELF class in dump artifact: {elf_class}")


def _read_section_name(table: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(table):
        return ""
    end = table.find(b"\x00", offset)
    if end == -1:
        end = len(table)
    return table[offset:end].decode("utf-8", errors="replace")


def _read_section_headers(data: bytes) -> list[dict[str, int | str]]:
    layout = _read_elf_layout(data)
    elf_class = layout["elf_class"]
    shoff = layout["shoff"]
    shentsize = layout["shentsize"]
    shnum = layout["shnum"]
    shstrndx = layout["shstrndx"]
    assert shoff > 0, "section header table missing from fixed ELF"
    assert shentsize > 0, "invalid section header entry size"
    assert shnum > 0, "invalid section header count"
    assert shstrndx < shnum, "invalid section header string table index"

    headers: list[dict[str, int | str]] = []
    for index in range(shnum):
        base = shoff + index * shentsize
        if elf_class == 1:
            header = {
                "name_offset": int.from_bytes(data[base:base + 4], "little"),
                "type": int.from_bytes(data[base + 4:base + 8], "little"),
                "offset": int.from_bytes(data[base + 16:base + 20], "little"),
                "size": int.from_bytes(data[base + 20:base + 24], "little"),
                "entsize": int.from_bytes(data[base + 36:base + 40], "little"),
            }
        else:
            header = {
                "name_offset": int.from_bytes(data[base:base + 4], "little"),
                "type": int.from_bytes(data[base + 4:base + 8], "little"),
                "offset": int.from_bytes(data[base + 24:base + 32], "little"),
                "size": int.from_bytes(data[base + 32:base + 40], "little"),
                "entsize": int.from_bytes(data[base + 56:base + 64], "little"),
            }
        headers.append(header)

    shstr = headers[shstrndx]
    shstr_offset = int(shstr["offset"])
    shstr_size = int(shstr["size"])
    shstr_bytes = data[shstr_offset:shstr_offset + shstr_size]
    for header in headers:
        header["name"] = _read_section_name(shstr_bytes, int(header["name_offset"]))
    return headers


def _find_rebased_non_relative_relocation(
    raw_bytes: bytes,
    fixed_bytes: bytes,
    *,
    load_bias: int,
    module_size: int,
) -> dict[str, int | str] | None:
    layout = _read_elf_layout(fixed_bytes)
    machine = _read_elf_machine(fixed_bytes)
    relative_type = RELATIVE_TYPES_BY_MACHINE.get(machine)
    jump_slot_type = JUMP_SLOT_TYPES_BY_MACHINE.get(machine)
    assert relative_type is not None, f"unsupported ELF machine for relocation test: {machine}"
    assert jump_slot_type is not None, f"unsupported ELF machine for relocation test: {machine}"

    for section in _read_section_headers(fixed_bytes):
        section_name = str(section["name"])
        section_type = int(section["type"])
        if section_name not in {".rel.dyn", ".rela.dyn"}:
            continue
        if section_type not in {SHT_REL, SHT_RELA}:
            continue

        section_offset = int(section["offset"])
        section_size = int(section["size"])
        entry_size = int(section["entsize"])
        if entry_size <= 0:
            continue

        for entry_offset in range(section_offset, section_offset + section_size, entry_size):
            raw_r_offset = int.from_bytes(
                raw_bytes[entry_offset:entry_offset + layout["pointer_size"]],
                "little",
            )
            fixed_r_offset = int.from_bytes(
                fixed_bytes[entry_offset:entry_offset + layout["pointer_size"]],
                "little",
            )
            info_offset = entry_offset + (4 if layout["elf_class"] == 1 else 8)
            info_value = int.from_bytes(fixed_bytes[info_offset:info_offset + layout["pointer_size"]], "little")
            reloc_type = info_value & 0xFF if layout["elf_class"] == 1 else info_value & 0xFFFFFFFF
            if reloc_type in {relative_type, jump_slot_type}:
                continue
            if raw_r_offset < load_bias:
                continue
            expected_offset = raw_r_offset - load_bias
            if not (0 <= expected_offset < module_size):
                continue
            return {
                "section": section_name,
                "type": reloc_type,
                "raw_r_offset": raw_r_offset,
                "fixed_r_offset": fixed_r_offset,
                "expected_r_offset": expected_offset,
            }
    return None


def _apply_raw_to_fixed_fixups(raw: bytes, fixups: dict[str, object]) -> bytes:
    raw_size = int(fixups["raw_size"])
    fixed_size = int(fixups["fixed_size"])
    stages = fixups["stages"]
    assert isinstance(stages, list)
    assert raw_size == len(raw)

    output = bytearray(raw)
    assert [stage["name"] for stage in stages] == FIXUP_STAGE_ORDER

    for stage in stages:
        assert isinstance(stage, dict)
        patches = stage["patches"]
        assert isinstance(patches, list)
        for patch in patches:
            assert isinstance(patch, dict)
            patch_type = str(patch["t"])
            if patch_type == "f":
                width = int(patch["w"])
                offset = int(patch["o"])
                value = str(patch["a"])
                assert value.startswith("0x")
                output[offset:offset + width] = bytes.fromhex(value[2:].rjust(width * 2, "0"))[::-1]
                continue
            if patch_type == "s":
                width = int(patch["w"])
                values = patch["v"]
                assert isinstance(values, list)
                for slot in values:
                    assert isinstance(slot, list)
                    assert len(slot) == 3
                    offset = int(slot[0])
                    value = str(slot[2])
                    assert value.startswith("0x")
                    output[offset:offset + width] = bytes.fromhex(value[2:].rjust(width * 2, "0"))[::-1]
                continue
            if patch_type == "x":
                offset = int(patch["o"])
                replace_size = int(patch["r"])
                data = bytes.fromhex(str(patch["x"]))
                if replace_size == 0 and offset == len(output):
                    output.extend(data)
                else:
                    output[offset:offset + replace_size] = data
                continue
            raise AssertionError(f"unsupported fixup patch type: {patch_type}")

    assert len(output) == fixed_size
    return bytes(output)


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


@pytest.fixture
def booted_device_agent_unit_workspace(
    device_helpers: 'DeviceHelpers',
    device_agent_unit_workspace,
    device_app: str,
    device_server_ready,
) -> Iterator[object]:
    workspace = device_agent_unit_workspace
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
def running_device_agent_unit_app_pid(
    device_helpers: 'DeviceHelpers',
    device_app: str,
    booted_device_agent_unit_workspace,
    device_server_ready,
) -> int:
    workspace = booted_device_agent_unit_workspace
    attach_pid, attach_error = device_helpers.find_attachable_app_pid(
        device_app,
        timeout=30,
        recover_remote=lambda: device_server_ready.ensure_running(workspace.config_path, timeout=60),
    )
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
    assert suites == EXPECTED_AGENT_UNIT_SUITES

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

    assert suites == EXPECTED_AGENT_UNIT_SUITES
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

    assert suites == EXPECTED_AGENT_UNIT_SUITES
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

    assert suites == EXPECTED_AGENT_UNIT_SUITES
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

    assert suites == EXPECTED_AGENT_UNIT_SUITES
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

    assert suites == EXPECTED_AGENT_UNIT_SUITES
    assert result["suite"] == "dex_tools"
    assert result["failed"] == 0
    assert result["passed"] >= 2
    for case in result["cases"]:
        assert case["ok"] is True, case

    dump_detail = json.loads(_suite_case_detail(result, DEX_DUMP_CASE))
    expected_count = int(dump_detail["dexCount"])
    assert dump_detail["relativeDumpDir"] == dump_detail["tag"]
    dump_dir = booted_device_agent_unit_workspace.root / "data" / "dextools" / str(dump_detail["tag"])
    manifest_path = dump_dir / "manifest.json"

    deadline = time.monotonic() + 30
    manifest: dict[str, object] = {}
    dex_files = []
    while time.monotonic() < deadline:
        dex_files = sorted(dump_dir.glob("classes*.dex"))
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest.get("files")
            if isinstance(files, list) and len(files) == expected_count and len(dex_files) == expected_count:
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
    assert manifest["tag"] == dump_detail["tag"]
    assert manifest["effective_tag"] == dump_detail["tag"]
    assert manifest["actual_relative_dir"] == dump_detail["tag"]
    assert manifest["received_count"] == expected_count
    assert len(manifest["files"]) == expected_count
    assert len(dex_files) == expected_count
    assert not (dump_dir / "classes.json").exists()
    assert {item["output_name"] for item in manifest["files"]} == {path.name for path in dex_files}
    assert all(path.stat().st_size > 0 for path in dex_files)


@pytest.mark.device
def test_agent_unit_runner_reports_elf_tools_suite_on_device(
    device_helpers: 'DeviceHelpers',
    booted_device_agent_unit_workspace,
    running_device_agent_unit_app_pid: int,
) -> None:
    payload = _run_agent_unit_probe(
        device_helpers,
        booted_device_agent_unit_workspace,
        "elf_tools",
        pid=running_device_agent_unit_app_pid,
    )

    suites = payload["suites"]
    result = payload["result"]

    assert suites == EXPECTED_AGENT_UNIT_SUITES
    assert result["suite"] == "elf_tools"
    assert result["failed"] == 0
    assert result["passed"] >= 4
    for case in result["cases"]:
        assert case["ok"] is True, case

    dump_detail = json.loads(_suite_case_detail(result, ELF_DUMP_CASE))
    assert dump_detail["relativeDumpDir"] == dump_detail["tag"]
    dump_dir = (
        booted_device_agent_unit_workspace.root
        / "data"
        / "elftools"
        / str(dump_detail["tag"])
    )
    expected_files = [
        "libc.raw.so",
        "libc.fixed.so",
        "fixups.json",
        "symbols.json",
        "proc_maps.txt",
        "manifest.json",
    ]

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if dump_dir.is_dir() and all((dump_dir / name).is_file() for name in expected_files):
            break
        time.sleep(1)
    else:
        pytest.fail(
            "timed out waiting for elf dump outputs\n"
            f"dump_dir={dump_dir}\n"
            f"expected_files={expected_files}"
        )

    raw_bytes = (dump_dir / "libc.raw.so").read_bytes()
    fixed_bytes = (dump_dir / "libc.fixed.so").read_bytes()
    fixups = json.loads((dump_dir / "fixups.json").read_text(encoding="utf-8"))
    manifest = json.loads((dump_dir / "manifest.json").read_text(encoding="utf-8"))
    artifact_kinds = {item["kind"] for item in dump_detail["artifacts"]}
    assert raw_bytes
    assert len(fixed_bytes) > 0
    assert "fixups" in artifact_kinds
    assert "rebuilt" not in artifact_kinds
    assert _apply_raw_to_fixed_fixups(raw_bytes, fixups) == fixed_bytes
    assert [stage["name"] for stage in fixups["stages"]] == FIXUP_STAGE_ORDER
    assert fixed_bytes[7] == 0
    assert int.from_bytes(fixed_bytes[16:18], "little") == 3
    assert int.from_bytes(fixed_bytes[18:20], "little") == 183
    assert int.from_bytes(fixed_bytes[20:24], "little") == 1
    fixed_entry = _read_elf_entry(fixed_bytes)
    header_after = manifest["fix"]["header_after"]
    module_size = int(manifest["module"]["size"])
    module_base = int(manifest["module"]["base"], 16)
    load_bias = int(manifest["module"]["load_bias"])
    assert fixed_entry == header_after["eEntry"]
    assert fixed_entry == 0 or 0 <= fixed_entry < module_size
    assert fixed_entry != module_base
    relocation_probe = _find_rebased_non_relative_relocation(
        raw_bytes,
        fixed_bytes,
        load_bias=load_bias,
        module_size=module_size,
    )
    assert relocation_probe is not None, "expected at least one non-RELATIVE/JUMP_SLOT relocation in .rel[a].dyn"
    assert relocation_probe["fixed_r_offset"] == relocation_probe["expected_r_offset"]
    assert 0 <= int(relocation_probe["fixed_r_offset"]) < module_size
    assert manifest["fix"]["change_record"]["output_name"] == "fixups.json"
    assert manifest["fix"]["stages"] == [{"name": stage["name"], "detail": stage["detail"]} for stage in fixups["stages"]]
    assert manifest["fix"]["change_record"]["stage_count"] == len(fixups["stages"])
    assert manifest["fix"]["change_record"]["patch_count"] == sum(len(stage["patches"]) for stage in fixups["stages"])
    assert manifest["fix"]["change_record"]["raw_size"] == len(raw_bytes)
    assert manifest["fix"]["change_record"]["fixed_size"] == len(fixed_bytes)
    assert manifest["requested_output_dir"] is None
    assert manifest["actual_relative_dir"] == dump_detail["tag"]
    assert (dump_dir / "symbols.json").stat().st_size > 0
    preset_detail = json.loads(_suite_case_detail(result, ELF_PRESET_CASE))
    assert preset_detail["symbol"] == "getppid"
    assert preset_detail["logTag"]


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

    assert suites == EXPECTED_AGENT_UNIT_SUITES
    assert result["suite"] == "helper_runtime"
    assert result["failed"] == 0
    assert result["passed"] >= 5
    for case in result["cases"]:
        assert case["ok"] is True, case
