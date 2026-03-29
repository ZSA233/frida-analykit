from __future__ import annotations

import atexit
import asyncio
import os
import time
from pathlib import Path
from typing import Callable, Iterable, Protocol, TypeAlias, TypeVar, cast

import click
import frida
from frida.core import Session

from ..compat import FridaCompat
from ..config import AppConfig
from ..dev_env import DevEnvManager
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


def _global_env_manager() -> DevEnvManager:
    return DevEnvManager.for_global()


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
