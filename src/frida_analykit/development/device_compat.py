from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Protocol

from ..config import AppConfig
from ..device.defaults import (
    DEFAULT_DEVICE_FRIDA_VERSION,
    DEFAULT_REMOTE_SERVERNAME,
)
from ..device.helpers import DeviceHelpers
from ..device.models import DeviceAppResolutionError
from ..device.runtime import DeviceServerRuntime, should_retry_device_operation
from ..device.selection import derive_remote_host, resolve_device_serials
from ..env import EnvError, EnvManager
from .managed_envs import ManagedFridaEnvRef, list_managed_frida_envs, sample_frida_versions

DEVICE_COMPAT_MARKER = "FRIDA_ANALYKIT_DEVICE_COMPAT="
DEFAULT_DEVICE_COMPAT_PROBE_KINDS: Final[tuple[str, ...]] = ("spawn", "attach")
DEVICE_COMPAT_PROBE_MAX_ATTEMPTS: Final[int] = 2
DEVICE_COMPAT_RUNTIME_TIMEOUT: Final[int] = 60
DEVICE_COMPAT_AGENT_SOURCE = """
rpc.exports = {
  ping() {
    return "ok";
  }
};
"""


class DeviceCompatProbeError(RuntimeError):
    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(detail)
        self.stage = stage
        self.detail = detail


@dataclass(frozen=True, slots=True)
class DeviceCompatResult:
    version: str
    probe_kind: str
    status: str
    stage: str | None
    detail: str
    elapsed_seconds: float
    app: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceCompatSummary:
    serial: str
    remote_host: str
    sampled_versions: tuple[str, ...]
    results: tuple[DeviceCompatResult, ...]


class DeviceCompatReporter(Protocol):
    def on_scan_start(self, *, serials: Sequence[str]) -> None: ...

    def on_device_start(
        self,
        *,
        device_index: int,
        device_total: int,
        serial: str,
        remote_host: str,
        sampled_versions: Sequence[str],
    ) -> None: ...

    def on_device_stage(
        self,
        *,
        device_index: int,
        device_total: int,
        serial: str,
        stage: str,
        detail: str | None = None,
    ) -> None: ...

    def on_version_start(
        self,
        *,
        device_index: int,
        device_total: int,
        version_index: int,
        version_total: int,
        serial: str,
        version: str,
    ) -> None: ...

    def on_version_stage(
        self,
        *,
        device_index: int,
        device_total: int,
        version_index: int,
        version_total: int,
        serial: str,
        version: str,
        stage: str,
        detail: str | None = None,
    ) -> None: ...

    def on_version_result(
        self,
        *,
        device_index: int,
        device_total: int,
        version_index: int,
        version_total: int,
        serial: str,
        version: str,
        result: DeviceCompatResult,
    ) -> None: ...


def build_device_doctor_config(
    repo_root: Path,
    *,
    app: str | None,
    servername: str = DEFAULT_REMOTE_SERVERNAME,
    device: str | None = None,
) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": app,
            "jsfile": "_agent.js",
            "server": {
                "host": "127.0.0.1:27042",
                "servername": servername,
                "device": device,
            },
            "agent": {},
            "script": {"nettools": {}},
        }
    ).resolve_paths(repo_root, source_path=repo_root / "config.yml")


def resolve_device_compat_serials(
    *,
    explicit_serials: Sequence[str] = (),
    all_devices: bool,
    config_serial: str | None,
    env_serial: str | None,
    env: dict[str, str],
    cwd: Path,
) -> tuple[str, ...]:
    fallback = None
    if not explicit_serials and not all_devices:
        fallback = config_serial or env_serial
    return resolve_device_serials(
        explicit_serials,
        all_devices=all_devices,
        fallback_serial=fallback,
        multiple_devices_hint="pass --serial <serial>, use --all-devices, or set ANDROID_SERIAL=<serial>",
        env=env,
        cwd=cwd,
    )


def resolve_scan_envs(
    repo_root: Path,
    *,
    requested_versions: Sequence[str] = (),
    iterations: int,
) -> tuple[tuple[str, ...], tuple[ManagedFridaEnvRef, ...]]:
    env_map = {item.frida_version: item for item in list_managed_frida_envs(repo_root)}
    sampled_versions = _resolve_sampled_versions(tuple(env_map), requested_versions=requested_versions, iterations=iterations)
    return sampled_versions, tuple(env_map[version] for version in sampled_versions if version in env_map)


def _unique_requested_versions(versions: Sequence[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for version in versions:
        if version in seen:
            continue
        seen.add(version)
        ordered.append(version)
    return tuple(ordered)


def _resolve_sampled_versions(
    available_versions: Sequence[str],
    *,
    requested_versions: Sequence[str],
    iterations: int,
) -> tuple[str, ...]:
    if requested_versions:
        return _unique_requested_versions(requested_versions)
    return sample_frida_versions(tuple(available_versions), iterations)


def _normalize_probe_kinds(probe_kinds: Sequence[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for probe_kind in probe_kinds:
        if probe_kind in seen:
            continue
        seen.add(probe_kind)
        ordered.append(probe_kind)
    return tuple(ordered) or DEFAULT_DEVICE_COMPAT_PROBE_KINDS


def _manual_env_install_hint(version: str) -> str:
    return (
        f"create one with `make env-create FRIDA_VERSION={version}` "
        f"or `python scripts/env.py gen --frida-version {version}`"
    )


def _missing_managed_env_detail(version: str, *, can_auto_install: bool) -> str:
    detail = f"no managed env for frida=={version}; {_manual_env_install_hint(version)}"
    if can_auto_install:
        detail += "; or rerun with `--install-missing-env`"
    return detail


def _resolve_scan_env_map(
    repo_root: Path,
    *,
    requested_versions: Sequence[str],
    install_missing_env: bool,
) -> tuple[dict[str, ManagedFridaEnvRef], dict[str, str]]:
    env_map = {item.frida_version: item for item in list_managed_frida_envs(repo_root)}
    missing_details: dict[str, str] = {}
    requested = _unique_requested_versions(requested_versions)
    if not requested:
        return env_map, missing_details

    missing_versions = [version for version in requested if version not in env_map]
    if not missing_versions:
        return env_map, missing_details

    if not install_missing_env:
        for version in missing_versions:
            missing_details[version] = _missing_managed_env_detail(version, can_auto_install=True)
        return env_map, missing_details

    manager = EnvManager.for_repo(repo_root)
    for version in missing_versions:
        try:
            manager.create(name=None, frida_version=version, with_repl=False)
        except EnvError as exc:
            missing_details[version] = (
                f"failed to create repo-local managed env for frida=={version}: {exc}; "
                f"{_manual_env_install_hint(version)}"
            )

    env_map = {item.frida_version: item for item in list_managed_frida_envs(repo_root)}
    for version in missing_versions:
        if version not in env_map and version not in missing_details:
            missing_details[version] = _missing_managed_env_detail(version, can_auto_install=False)
    return env_map, missing_details


def estimate_compat_boundary(results: Sequence[DeviceCompatResult]) -> str:
    successes = sorted((result.version for result in results if result.status == "success"))
    failures = sorted((result.version for result in results if result.status == "fail"))
    unavailable = sorted((result.version for result in results if result.status == "unavailable"))
    if unavailable and not successes and not failures:
        return f"no managed env available for sampled versions: {', '.join(unavailable)}"
    if failures and not successes:
        return f"all sampled versions failed; first sampled failure: {failures[0]}"
    if successes and not failures:
        return f"all sampled versions succeeded through {successes[-1]}"
    if successes and failures:
        return f"sampled compatibility reached {successes[-1]}; sampled failure begins at {failures[0]}"
    return "no sampled result"


def format_device_compat_summary(summary: DeviceCompatSummary) -> str:
    lines = [
        f"Device: {summary.serial}",
        f"Remote host: {summary.remote_host}",
        f"Sampled versions: {', '.join(summary.sampled_versions) or 'none'}",
    ]
    probe_kinds = _normalize_probe_kinds(result.probe_kind for result in summary.results)
    for probe_kind in probe_kinds:
        probe_results = tuple(result for result in summary.results if result.probe_kind == probe_kind)
        lines.append(f"Probe: {probe_kind}")
        for result in probe_results:
            suffix = f" app={result.app}" if result.app else ""
            stage = f" stage={result.stage}" if result.stage else ""
            lines.append(
                f"- {result.version}: {result.status}{stage}{suffix} "
                f"({result.elapsed_seconds:.2f}s) {result.detail}"
            )
        lines.append(f"Estimated boundary: {estimate_compat_boundary(probe_results)}")
    return "\n".join(lines)


def _extract_probe_payload(stdout: str, stderr: str) -> dict[str, object]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(DEVICE_COMPAT_MARKER):
            return json.loads(line[len(DEVICE_COMPAT_MARKER) :])
    raise DeviceCompatProbeError(
        "inject",
        f"compatibility probe marker was not found\nstdout:\n{stdout}\nstderr:\n{stderr}",
    )


def _run_spawn_injection_probe(helper: DeviceHelpers, workspace_config: Path) -> dict[str, object]:
    script = "\n".join(
        [
            "import json",
            "import time",
            "import traceback",
            "",
            "from frida_analykit.compat import FridaCompat",
            "from frida_analykit.config import AppConfig",
            "from frida_analykit.server import FridaServerManager",
            "from frida_analykit.session import SessionWrapper",
            "",
            f'config = AppConfig.from_yaml(r"{workspace_config}")',
            "FridaServerManager().ensure_remote_forward(config, action='doctor device compatibility probe')",
            "compat = FridaCompat()",
            "device = compat.get_device(config.server.host)",
            "try:",
            "    pid = None",
            "    session = None",
            "    payload = {}",
            "    stage = 'spawn'",
            "    try:",
            "        pid = device.spawn([config.app])",
            "        stage = 'inject'",
            "        session = SessionWrapper.from_session(device.attach(pid), config=config, interactive=False)",
            "        script = session.open_script(str(config.jsfile))",
            "        script.load()",
            "        device.resume(pid)",
            "        payload = {",
            "            'exports': sorted(script.list_exports_sync()),",
            "            'ping': script.exports_sync.ping(),",
            "        }",
            "        time.sleep(0.5)",
            f"        print({DEVICE_COMPAT_MARKER!r} + json.dumps({{'ok': True, 'payload': payload}}, ensure_ascii=False))",
            "    except Exception as exc:",
            "        if pid is not None:",
            "            try:",
            "                device.resume(pid)",
            "            except Exception:",
            "                pass",
            "        detail = ''.join(traceback.format_exception_only(type(exc), exc)).strip() or str(exc) or exc.__class__.__name__",
            f"        print({DEVICE_COMPAT_MARKER!r} + json.dumps({{'ok': False, 'stage': stage, 'detail': detail}}, ensure_ascii=False))",
            "        raise",
            "    finally:",
            "        if session is not None:",
            "            try:",
            "                session.detach()",
            "            except Exception:",
            "                pass",
            "finally:",
            "    pass",
        ]
    )
    result = helper.run_python_probe(script, timeout=240)
    probe = _extract_probe_payload(result.stdout, result.stderr)
    if not bool(probe.get("ok")):
        raise DeviceCompatProbeError(
            str(probe.get("stage") or "inject"),
            str(probe.get("detail") or "compatibility probe failed"),
        )
    payload = probe.get("payload")
    if not isinstance(payload, dict) or payload.get("ping") != "ok":
        raise DeviceCompatProbeError("inject", f"unexpected compatibility probe payload: {payload}")
    if result.returncode != 0:
        raise DeviceCompatProbeError(
            "inject",
            f"compatibility probe failed after reporting success\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
    return payload


def _run_attach_injection_probe(
    helper: DeviceHelpers,
    workspace_config: Path,
    *,
    pid: int,
) -> dict[str, object]:
    script = "\n".join(
        [
            "import json",
            "import time",
            "import traceback",
            "",
            "from frida_analykit.compat import FridaCompat",
            "from frida_analykit.config import AppConfig",
            "from frida_analykit.server import FridaServerManager",
            "from frida_analykit.session import SessionWrapper",
            "",
            f'config = AppConfig.from_yaml(r"{workspace_config}")',
            "FridaServerManager().ensure_remote_forward(config, action='doctor device compatibility probe')",
            "compat = FridaCompat()",
            "device = compat.get_device(config.server.host)",
            f"pid = {pid}",
            "session = None",
            "try:",
            "    try:",
            "        session = SessionWrapper.from_session(device.attach(pid), config=config, interactive=False)",
            "        script = session.open_script(str(config.jsfile))",
            "        script.load()",
            "        payload = {",
            "            'exports': sorted(script.list_exports_sync()),",
            "            'ping': script.exports_sync.ping(),",
            "        }",
            "        time.sleep(0.5)",
            f"        print({DEVICE_COMPAT_MARKER!r} + json.dumps({{'ok': True, 'payload': payload}}, ensure_ascii=False))",
            "    except Exception as exc:",
            "        detail = ''.join(traceback.format_exception_only(type(exc), exc)).strip() or str(exc) or exc.__class__.__name__",
            f"        print({DEVICE_COMPAT_MARKER!r} + json.dumps({{'ok': False, 'stage': 'inject', 'detail': detail}}, ensure_ascii=False))",
            "        raise",
            "finally:",
            "    if session is not None:",
            "        try:",
            "            session.detach()",
            "        except Exception:",
            "            pass",
        ]
    )
    result = helper.run_python_probe(script, timeout=240)
    probe = _extract_probe_payload(result.stdout, result.stderr)
    if not bool(probe.get("ok")):
        raise DeviceCompatProbeError(
            str(probe.get("stage") or "inject"),
            str(probe.get("detail") or "compatibility probe failed"),
        )
    payload = probe.get("payload")
    if not isinstance(payload, dict) or payload.get("ping") != "ok":
        raise DeviceCompatProbeError("inject", f"unexpected compatibility probe payload: {payload}")
    if result.returncode != 0:
        raise DeviceCompatProbeError(
            "inject",
            f"compatibility probe failed after reporting success\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
    return payload


def _resolve_spawn_probe_app(
    helper: DeviceHelpers,
    *,
    explicit_app: str | None,
    attempt_reporter: Callable[[str], None] | None = None,
    timeout: int = 30,
) -> tuple[str, str]:
    return helper.resolve_device_app(
        explicit_app=explicit_app,
        timeout=timeout,
        require_attach=False,
        attempt_reporter=attempt_reporter,
    )


def _prepare_probe_app(helper: DeviceHelpers, package: str) -> None:
    helper.force_stop_app(package, timeout=30)


def _run_attach_probe(
    helper: DeviceHelpers,
    workspace_config: Path,
    *,
    package: str,
) -> dict[str, object]:
    _prepare_probe_app(helper, package)
    attach_pid, attach_error = helper.find_attachable_app_pid(package, host=helper.remote_host, timeout=30)
    if attach_pid is None:
        raise DeviceCompatProbeError("attach", f"failed to start an attachable process for `{package}`: {attach_error}")
    return _run_attach_injection_probe(helper, workspace_config, pid=attach_pid)


def _run_spawn_probe(
    helper: DeviceHelpers,
    workspace_config: Path,
    *,
    package: str,
) -> dict[str, object]:
    _prepare_probe_app(helper, package)
    return _run_spawn_injection_probe(helper, workspace_config)


def _run_probe_with_recovery(
    helper: DeviceHelpers,
    runtime: DeviceServerRuntime,
    *,
    admin_config_path: Path,
    workspace_config: Path,
    probe_kind: str,
    package: str,
    stage_reporter: Callable[[str, str | None], None] | None = None,
) -> dict[str, object]:
    last_error: DeviceCompatProbeError | None = None
    for attempt in range(1, DEVICE_COMPAT_PROBE_MAX_ATTEMPTS + 1):
        detail = (
            f"spawning `{package}`"
            if probe_kind == "spawn"
            else f"launching and attaching `{package}`"
        )
        if attempt > 1:
            detail = f"retry {attempt}/{DEVICE_COMPAT_PROBE_MAX_ATTEMPTS}: {detail}"
        if stage_reporter is not None:
            stage_reporter(probe_kind, detail)

        try:
            runtime.ensure_running(admin_config_path, timeout=DEVICE_COMPAT_RUNTIME_TIMEOUT)
            if probe_kind == "spawn":
                return _run_spawn_probe(
                    helper,
                    workspace_config,
                    package=package,
                )
            return _run_attach_probe(
                helper,
                workspace_config,
                package=package,
            )
        except DeviceCompatProbeError as exc:
            last_error = exc
        except RuntimeError as exc:
            last_error = DeviceCompatProbeError("boot", str(exc))

        if last_error is None or attempt >= DEVICE_COMPAT_PROBE_MAX_ATTEMPTS:
            break
        if not should_retry_device_operation(
            helper,
            stage=last_error.stage,
            detail=last_error.detail,
        ):
            break
        if stage_reporter is not None:
            stage_reporter(
                "recover",
                f"{probe_kind} retry {attempt + 1}/{DEVICE_COMPAT_PROBE_MAX_ATTEMPTS} "
                f"after transient {last_error.stage} failure",
            )
        runtime.invalidate()
        time.sleep(1)

    raise last_error or DeviceCompatProbeError(probe_kind, "compatibility probe failed")


def _run_version_probe_suite(
    helper: DeviceHelpers,
    *,
    configured_app: str | None,
    preferred_app: str | None,
    probe_kinds: Sequence[str],
    stage_reporter: Callable[[str, str | None], None] | None = None,
) -> tuple[str, dict[str, dict[str, object] | DeviceCompatProbeError]]:
    with TemporaryDirectory(prefix=f"frida-analykit-device-{helper.serial or 'device'}-") as temp_root:
        root = Path(temp_root)
        admin_workspace = helper.create_workspace(root / "admin", app=None, agent_source=DEVICE_COMPAT_AGENT_SOURCE)
        runtime = DeviceServerRuntime(helper)
        try:
            if stage_reporter is not None:
                stage_reporter("install", None)
            runtime.ensure_installed(admin_workspace.config_path)
            if stage_reporter is not None:
                stage_reporter("boot", None)
            runtime.ensure_running(admin_workspace.config_path, timeout=DEVICE_COMPAT_RUNTIME_TIMEOUT)
            selected_app = preferred_app

            if selected_app is None:
                if stage_reporter is not None:
                    stage_reporter("select-app", None)
                try:
                    selected_app, _ = _resolve_spawn_probe_app(
                        helper,
                        explicit_app=configured_app,
                        attempt_reporter=(
                            (lambda detail: stage_reporter("select-app", detail))
                            if stage_reporter is not None
                            else None
                        ),
                    )
                except DeviceAppResolutionError as exc:
                    raise DeviceCompatProbeError("select-app", str(exc)) from exc

            probe_results: dict[str, dict[str, object] | DeviceCompatProbeError] = {}
            for probe_kind in _normalize_probe_kinds(probe_kinds):
                workspace = helper.create_workspace(
                    root / f"probe-{probe_kind}",
                    app=selected_app,
                    agent_source=DEVICE_COMPAT_AGENT_SOURCE,
                )
                try:
                    # Reuse the shared device runtime semantics from the device
                    # test suite so transient server exits and slow restarts do
                    # not immediately become compatibility failures.
                    probe_results[probe_kind] = _run_probe_with_recovery(
                        helper,
                        runtime,
                        admin_config_path=admin_workspace.config_path,
                        workspace_config=workspace.config_path,
                        probe_kind=probe_kind,
                        package=selected_app,
                        stage_reporter=stage_reporter,
                    )
                except DeviceCompatProbeError as exc:
                    probe_results[probe_kind] = exc
            return selected_app, probe_results
        except RuntimeError as exc:
            raise DeviceCompatProbeError("boot", str(exc)) from exc
        finally:
            runtime.stop()


def _select_probe_app(
    helper: DeviceHelpers,
    *,
    configured_app: str | None,
    reporter: DeviceCompatReporter | None,
    device_index: int,
    device_total: int,
    serial: str,
) -> tuple[str | None, str | None]:
    if reporter is not None:
        reporter.on_device_stage(
            device_index=device_index,
            device_total=device_total,
            serial=serial,
            stage="select-app",
        )
    try:
        selected_app, _ = _resolve_spawn_probe_app(
            helper,
            explicit_app=configured_app,
            timeout=45,
            attempt_reporter=(
                (
                    lambda detail: reporter.on_device_stage(
                        device_index=device_index,
                        device_total=device_total,
                        serial=serial,
                        stage="select-app",
                        detail=detail,
                    )
                )
                if reporter is not None
                else None
            ),
        )
    except DeviceAppResolutionError as exc:
        if reporter is not None:
            reporter.on_device_stage(
                device_index=device_index,
                device_total=device_total,
                serial=serial,
                stage="select-app",
                detail=str(exc),
            )
        return None, str(exc)

    if reporter is not None:
        reporter.on_device_stage(
            device_index=device_index,
            device_total=device_total,
            serial=serial,
            stage="select-app",
            detail=f"selected `{selected_app}`",
        )
    return selected_app, None


def run_device_compat_scan(
    repo_root: Path,
    *,
    env: dict[str, str],
    config: AppConfig,
    serials: Sequence[str],
    requested_versions: Sequence[str] = (),
    iterations: int = 3,
    app: str | None = None,
    probe_kinds: Sequence[str] = DEFAULT_DEVICE_COMPAT_PROBE_KINDS,
    install_missing_env: bool = False,
    reporter: DeviceCompatReporter | None = None,
) -> tuple[DeviceCompatSummary, ...]:
    env_map, missing_env_details = _resolve_scan_env_map(
        repo_root,
        requested_versions=requested_versions,
        install_missing_env=install_missing_env,
    )
    sampled_versions = _resolve_sampled_versions(tuple(env_map), requested_versions=requested_versions, iterations=iterations)
    selected_probe_kinds = _normalize_probe_kinds(probe_kinds)
    results: list[DeviceCompatSummary] = []
    if reporter is not None:
        reporter.on_scan_start(serials=serials)

    device_total = len(serials)
    for device_index, serial in enumerate(serials, start=1):
        remote_host = derive_remote_host(serial)
        device_results: list[DeviceCompatResult] = []
        configured_app = app or config.app
        if reporter is not None:
            reporter.on_device_start(
                device_index=device_index,
                device_total=device_total,
                serial=serial,
                remote_host=remote_host,
                sampled_versions=sampled_versions,
            )

        preferred_app = None
        preferred_app_error = None
        if any(version in env_map for version in sampled_versions):
            selection_helper = DeviceHelpers(
                repo_root,
                env,
                serial,
                python_executable=Path(sys.executable),
                frida_version=config.server.version or DEFAULT_DEVICE_FRIDA_VERSION,
                remote_host=remote_host,
                remote_servername=config.server.servername,
            )
            preferred_app, preferred_app_error = _select_probe_app(
                selection_helper,
                configured_app=configured_app,
                reporter=reporter,
                device_index=device_index,
                device_total=device_total,
                serial=serial,
            )
        version_total = len(sampled_versions)
        for version_index, version in enumerate(sampled_versions, start=1):
            started_at = time.monotonic()

            def emit_result(result: DeviceCompatResult) -> None:
                device_results.append(result)
                if reporter is not None:
                    reporter.on_version_result(
                        device_index=device_index,
                        device_total=device_total,
                        version_index=version_index,
                        version_total=version_total,
                        serial=serial,
                        version=version,
                        result=result,
                    )

            if reporter is not None:
                reporter.on_version_start(
                    device_index=device_index,
                    device_total=device_total,
                    version_index=version_index,
                    version_total=version_total,
                    serial=serial,
                    version=version,
                )
                reporter.on_version_stage(
                    device_index=device_index,
                    device_total=device_total,
                    version_index=version_index,
                    version_total=version_total,
                    serial=serial,
                    version=version,
                    stage="env",
                )
            env_ref = env_map.get(version)
            if env_ref is None:
                detail = missing_env_details.get(version) or _missing_managed_env_detail(
                    version,
                    can_auto_install=not install_missing_env,
                )
                for probe_kind in selected_probe_kinds:
                    emit_result(
                        DeviceCompatResult(
                            version=version,
                            probe_kind=probe_kind,
                            status="unavailable",
                            stage="env",
                            detail=detail,
                            elapsed_seconds=time.monotonic() - started_at,
                        )
                    )
                continue

            helper = DeviceHelpers(
                repo_root,
                env,
                serial,
                python_executable=env_ref.python_path,
                frida_version=env_ref.frida_version,
                remote_host=remote_host,
                remote_servername=config.server.servername,
            )
            actual_version = None
            try:
                actual_version = helper.current_frida_version()
            except RuntimeError as exc:
                for probe_kind in selected_probe_kinds:
                    emit_result(
                        DeviceCompatResult(
                            version=version,
                            probe_kind=probe_kind,
                            status="unavailable",
                            stage="env",
                            detail=str(exc),
                            elapsed_seconds=time.monotonic() - started_at,
                        )
                    )
                continue
            if actual_version != version:
                for probe_kind in selected_probe_kinds:
                    emit_result(
                        DeviceCompatResult(
                            version=version,
                            probe_kind=probe_kind,
                            status="unavailable",
                            stage="env",
                            detail=f"selected env reports frida=={actual_version}, expected {version}",
                            elapsed_seconds=time.monotonic() - started_at,
                        )
                    )
                continue

            if preferred_app_error is not None:
                for probe_kind in selected_probe_kinds:
                    emit_result(
                        DeviceCompatResult(
                            version=version,
                            probe_kind=probe_kind,
                            status="fail",
                            stage="select-app",
                            detail=preferred_app_error,
                            elapsed_seconds=time.monotonic() - started_at,
                        )
                    )
                continue

            try:
                selected_app, probe_results = _run_version_probe_suite(
                    helper,
                    configured_app=configured_app,
                    preferred_app=preferred_app,
                    probe_kinds=selected_probe_kinds,
                    stage_reporter=(
                        (
                            lambda stage, detail=None: reporter.on_version_stage(
                                device_index=device_index,
                                device_total=device_total,
                                version_index=version_index,
                                version_total=version_total,
                                serial=serial,
                                version=version,
                                stage=stage,
                                detail=detail,
                            )
                        )
                        if reporter is not None
                        else None
                    ),
                )
            except DeviceCompatProbeError as exc:
                for probe_kind in selected_probe_kinds:
                    emit_result(
                        DeviceCompatResult(
                            version=version,
                            probe_kind=probe_kind,
                            status="fail",
                            stage=exc.stage,
                            detail=exc.detail,
                            elapsed_seconds=time.monotonic() - started_at,
                        )
                    )
                continue

            if configured_app is None:
                preferred_app = selected_app

            for probe_kind in selected_probe_kinds:
                probe_result = probe_results.get(probe_kind)
                if isinstance(probe_result, DeviceCompatProbeError):
                    emit_result(
                        DeviceCompatResult(
                            version=version,
                            probe_kind=probe_kind,
                            status="fail",
                            stage=probe_result.stage,
                            detail=probe_result.detail,
                            elapsed_seconds=time.monotonic() - started_at,
                        )
                    )
                    continue
                emit_result(
                    DeviceCompatResult(
                        version=version,
                        probe_kind=probe_kind,
                        status="success",
                        stage=None,
                        detail=f"{probe_kind} injection probe succeeded",
                        elapsed_seconds=time.monotonic() - started_at,
                        app=selected_app,
                    )
                )

        results.append(
            DeviceCompatSummary(
                serial=serial,
                remote_host=remote_host,
                sampled_versions=tuple(sampled_versions),
                results=tuple(device_results),
            )
        )

    return tuple(results)
