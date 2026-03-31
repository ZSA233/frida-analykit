from __future__ import annotations

import atexit
import asyncio
import os
import shlex
import time
from pathlib import Path
from typing import Callable, Iterable, Protocol, TypeAlias, TypeVar, cast

import click
import frida
from frida.core import Session

from ..compat import FridaCompat
from ..config import AppConfig
from ..env import EnvManager
from ..diagnostics import set_verbose
from ..frontend import FrontendError, WatchProcess, build_agent_bundle, load_frontend_project, start_watch
from ..repl import LazyJsHandleProxy, build_repl_namespace
from ..server import FridaServerManager, ServerManagerError
from ..session import ScriptWrapper, SessionWrapper

F = TypeVar("F", bound=Callable[..., object])
ClickDecorator: TypeAlias = Callable[[F], F]


class RuntimeApplication(Protocol):
    identifier: str
    pid: int | None


class RuntimeDevice(Protocol):
    def attach(self, pid: int) -> Session: ...

    def spawn(self, argv: list[str]) -> int: ...

    def resume(self, pid: int) -> None: ...


ReplNamespaceValue: TypeAlias = AppConfig | int | SessionWrapper | ScriptWrapper | RuntimeDevice | LazyJsHandleProxy


def _load_config(path: str) -> AppConfig:
    return AppConfig.from_yaml(path)


def _load_optional_config(path: str) -> AppConfig | None:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return None
    return AppConfig.from_yaml(candidate)


def _frontend_project_option() -> ClickDecorator:
    return click.option(
        "--project-dir",
        type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
        default=None,
        help="Override the TypeScript agent workspace root. Defaults to the config directory.",
    )


def _verbose_option() -> ClickDecorator:
    return click.option(
        "--verbose",
        is_flag=True,
        help="Print diagnostic command execution details, including subprocess commands and captured output.",
    )


def _frontend_install_option() -> ClickDecorator:
    return click.option(
        "--install",
        is_flag=True,
        help="Run `npm install` automatically when the workspace has no node_modules directory.",
    )


def _frontend_build_option() -> ClickDecorator:
    return click.option(
        "--build",
        "build_agent",
        is_flag=True,
        help="Run `npm run build` before loading the agent bundle.",
    )


def _frontend_watch_option() -> ClickDecorator:
    return click.option(
        "--watch",
        "watch_agent",
        is_flag=True,
        help="Start `npm run watch`, wait for the first rebuilt bundle, then load it.",
    )


def _run_repl(namespace: dict[str, ReplNamespaceValue]) -> None:
    try:
        from ptpython.repl import embed
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise click.ClickException(
            "REPL support is not installed. Reinstall with `uv sync --extra repl`."
        ) from exc

    os.environ["REPL"] = "1"
    asyncio.run(embed(globals(), namespace, return_asyncio_coroutine=True))


def _wait_forever() -> None:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def _find_app_pid(device: RuntimeDevice, compat: FridaCompat, app_id: str) -> int | None:
    applications = cast(Iterable[RuntimeApplication], compat.enumerate_applications(device, scope="minimal"))
    for app in applications:
        if getattr(app, "identifier", "").strip() == app_id:
            return getattr(app, "pid", None)
    return None


def _on_session_detached(reason: str, crash: frida._frida.Crash | None) -> None:
    click.echo(reason, err=True)
    if crash:
        click.echo(crash.report, err=True)


def _prepare_session(
    config: AppConfig,
    device: RuntimeDevice,
    pid: int,
    *,
    interactive: bool = False,
) -> tuple[RuntimeDevice, SessionWrapper, ScriptWrapper]:
    session = SessionWrapper.from_session(device.attach(pid), config=config, interactive=interactive)
    session.on("detached", _on_session_detached)
    script = session.open_script(str(config.jsfile))
    script.set_logger()
    script.load()
    return device, session, script


def _prepare_frontend_assets(
    *,
    config: AppConfig,
    build_agent: bool,
    watch_agent: bool,
    project_dir: Path | None,
    install: bool,
) -> WatchProcess | None:
    if build_agent and watch_agent:
        raise click.ClickException("choose either `--build` or `--watch`, not both")
    if not build_agent and not watch_agent:
        if project_dir is not None or install:
            raise click.ClickException("`--project-dir` and `--install` require `--build` or `--watch`")
        return None

    try:
        project = load_frontend_project(config, project_dir=project_dir)
        if build_agent:
            build_agent_bundle(project, install=install)
            return None
        watcher = start_watch(project, install=install)
        watcher.wait_until_ready()
        return watcher
    except FrontendError as exc:
        raise click.ClickException(str(exc)) from exc


def _post_attach(
    *,
    config: AppConfig,
    device: RuntimeDevice,
    session: SessionWrapper,
    script: ScriptWrapper,
    pid: int,
    repl: bool,
    detach_on_load: bool,
) -> None:
    if detach_on_load:
        session.detach()
        return
    atexit.register(session.detach)
    if repl:
        base_namespace: dict[str, ReplNamespaceValue] = {
            "config": config,
            "device": device,
            "pid": pid,
            "session": session,
            "script": script,
        }
        try:
            namespace = build_repl_namespace(
                base_namespace,
                script=script,
                global_names=config.script.repl.globals,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        _run_repl(
            cast(dict[str, ReplNamespaceValue], namespace)
        )
        return
    _wait_forever()


def _configure_verbose(verbose: bool) -> None:
    set_verbose(verbose)


def _doctor_command_for_config(config: AppConfig, *parts: str) -> str:
    base = ["frida-analykit", "doctor", *parts]
    if config.source_path is not None:
        base.extend(["--config", str(config.source_path)])
    return " ".join(shlex.quote(item) for item in base)


def _server_command_for_config(config: AppConfig, *parts: str) -> str:
    base = ["frida-analykit", "server", *parts]
    if config.source_path is not None:
        base.extend(["--config", str(config.source_path)])
    return " ".join(shlex.quote(item) for item in base)


def _best_effort_remote_status(config: AppConfig):
    try:
        return FridaServerManager().inspect_remote_server(config, probe_host=True)
    except ServerManagerError:
        return None


def _remote_protocol_click_exception(
    *,
    operation: str,
    config: AppConfig,
    detail: str,
) -> click.ClickException | None:
    status = _best_effort_remote_status(config)
    if status is None:
        return None

    local_version = str(FridaCompat().installed_version)
    target_version = getattr(status, "selected_version", None) or (config.server.version or local_version)
    target_source = getattr(status, "selected_version_source", None) or (
        "config.server.version" if config.server.version else "installed Frida"
    )
    remote_version = getattr(status, "installed_version", None) or "unknown"
    resolved_device = (
        getattr(status, "resolved_device", None)
        or getattr(status, "adb_target", None)
        or config.server.device
        or "unknown"
    )
    detail_suffix = f" ({detail})" if detail else ""
    doctor_command = _doctor_command_for_config(config)
    fix_command = _doctor_command_for_config(config, "fix")
    boot_command = _server_command_for_config(config, "boot")

    if getattr(status, "version_matches_target", None) is False:
        return click.ClickException(
            f"{operation} failed because the remote frida-server at `{config.server.host}` is protocol-incompatible "
            f"right now{detail_suffix}. Local Frida: `{local_version}`. Target server version: `{target_version}` "
            f"(from {target_source}). Remote installed version: `{remote_version}` on device `{resolved_device}`. "
            "This usually means the remote process was booted from a different frida-server version. "
            f"Run `{doctor_command}` to inspect it, or `{fix_command}` to reinstall the remote binary. "
            f"After reinstalling, rerun `{boot_command}` to restart the remote process."
        )

    if getattr(status, "protocol_compatible", None) is False or getattr(status, "host_reachable", None) is True:
        return click.ClickException(
            f"{operation} failed because the remote frida-server at `{config.server.host}` is protocol-incompatible "
            f"right now{detail_suffix}. Target device: `{resolved_device}`. Target server version: "
            f"`{target_version}` (from {target_source}). Remote installed version: `{remote_version}`. "
            f"Run `{doctor_command}` to inspect the remote version/protocol state. If the binary already matches, "
            f"rerun `{boot_command}` to restart the remote process."
        )
    return None


def _runtime_click_exception(
    *,
    command: str,
    target: str | int | None,
    config: AppConfig,
    exc: Exception,
) -> click.ClickException:
    detail = str(exc).strip()
    operation = command if target is None else f"{command} of `{target}`"

    if isinstance(exc, (frida.TransportError, frida.ServerNotRunningError, frida.ProtocolError)):
        if config.server.is_remote:
            boot_command = _server_command_for_config(config, "boot")
            detail_suffix = f" ({detail})" if detail else ""
            if isinstance(exc, frida.ProtocolError):
                diagnosed = _remote_protocol_click_exception(
                    operation=operation,
                    config=config,
                    detail=detail,
                )
                if diagnosed is not None:
                    return diagnosed
                problem = f"the remote frida-server at `{config.server.host}` is protocol-incompatible right now"
                guidance = (
                    "Check that it is still running, version-compatible, and reachable through the current adb "
                    "forward. Run `frida-analykit doctor` to inspect the remote version and protocol state."
                )
            else:
                problem = f"the forwarded Frida host `{config.server.host}` is not reachable right now"
                guidance = (
                    "Check that frida-server is still running on the device and that the adb forward for this host "
                    "is still alive."
                )
            return click.ClickException(
                f"{operation} failed because {problem}{detail_suffix}. {guidance} "
                f"`spawn` and `attach` do not boot `frida-server` automatically; "
                f"if you already ran `{boot_command}`, verify that the boot session is still alive, "
                f"otherwise run it again and retry."
            )
        return click.ClickException(f"{operation} failed: {detail or exc.__class__.__name__}")

    if isinstance(exc, frida.TimedOutError):
        if command == "spawn":
            return click.ClickException(
                f"{operation} timed out while waiting for the app to launch. "
                "Check whether the app blocks or exits during launch, then retry."
            )
        return click.ClickException(
            f"{operation} timed out while waiting for the target process to respond. "
            "Verify the target process is still alive, then retry."
        )

    if isinstance(exc, frida.ProcessNotFoundError):
        return click.ClickException(f"{operation} failed because the target process no longer exists.")

    return click.ClickException(f"{operation} failed: {detail or exc.__class__.__name__}")


def _resolve_runtime_device(config: AppConfig, compat: FridaCompat) -> RuntimeDevice:
    host = config.server.host
    if host in {"local", "local://"}:
        return cast(RuntimeDevice, compat.get_device(host))
    if host in {"usb", "usb://"}:
        return cast(RuntimeDevice, compat.get_device(host, device_id=config.server.device))
    if config.server.is_remote:
        try:
            FridaServerManager().ensure_remote_forward(config, action="device connection")
        except ServerManagerError as exc:
            raise click.ClickException(str(exc)) from exc
    return cast(RuntimeDevice, compat.get_device(host))


def _global_env_manager() -> EnvManager:
    return EnvManager.for_global()


class _DownloadProgressReporter:
    def __init__(self, *, label: str) -> None:
        self._label = label
        self._last_downloaded = 0
        self._bar_cm = None
        self._bar = None

    def __call__(self, downloaded: int, total: int | None) -> None:
        if self._bar is None:
            self._bar_cm = click.progressbar(
                length=total,
                label=self._label,
                show_eta=total is not None,
                show_percent=total is not None,
                show_pos=True,
            )
            self._bar = self._bar_cm.__enter__()
        delta = max(downloaded - self._last_downloaded, 0)
        if delta > 0:
            self._bar.update(delta)
        self._last_downloaded = downloaded

    def close(self) -> None:
        if self._bar_cm is None:
            return
        self._bar_cm.__exit__(None, None, None)
        self._bar_cm = None
        self._bar = None
