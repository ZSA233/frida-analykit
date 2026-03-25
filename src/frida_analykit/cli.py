from __future__ import annotations

import atexit
import os
import time
from pathlib import Path
from typing import Any

import click
import frida

from .compat import FridaCompat
from .config import AppConfig
from .frontend import FrontendError, WatchProcess, build_agent_bundle, load_frontend_project, start_watch
from .scaffold import generate_dev_workspace, scaffold_summary
from .server import boot_server
from .session import SessionWrapper


def _load_config(path: str) -> AppConfig:
    return AppConfig.from_yaml(path)


def _frontend_project_option():
    return click.option(
        "--project-dir",
        type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
        default=None,
        help="Override the TypeScript agent workspace root. Defaults to the config directory.",
    )


def _frontend_install_option():
    return click.option(
        "--install",
        is_flag=True,
        help="Run `npm install` automatically when the workspace has no node_modules directory.",
    )


def _frontend_build_option():
    return click.option(
        "--build",
        "build_agent",
        is_flag=True,
        help="Run `npm run build` before loading the agent bundle.",
    )


def _frontend_watch_option():
    return click.option(
        "--watch",
        "watch_agent",
        is_flag=True,
        help="Start `npm run watch`, wait for the first rebuilt bundle, then load it.",
    )


def _run_repl(namespace: dict[str, Any]) -> None:
    try:
        from ptpython.repl import embed
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise click.ClickException(
            "REPL support is not installed. Reinstall with `uv sync --extra repl`."
        ) from exc

    os.environ["REPL"] = "1"
    embed(globals(), namespace)


def _wait_forever() -> None:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def _find_app_pid(device, compat: FridaCompat, app_id: str) -> int | None:
    for app in compat.enumerate_applications(device, scope="minimal"):
        if getattr(app, "identifier", "").strip() == app_id:
            return getattr(app, "pid", None)
    return None


def _on_session_detached(reason: str, crash: frida._frida.Crash | None) -> None:
    click.echo(reason, err=True)
    if crash:
        click.echo(crash.report, err=True)


def _prepare_session(config: AppConfig, device: Any, pid: int):
    session = SessionWrapper.from_session(device.attach(pid), config=config)
    session.on("detached", _on_session_detached)
    script = session.open_script(str(config.jsfile))
    script.set_logger(config.agent.stdout, config.agent.stderr)
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
    device: Any,
    session: SessionWrapper,
    script: Any,
    pid: int,
    repl: bool,
    detach_on_load: bool,
) -> None:
    if detach_on_load:
        session.detach()
        return
    atexit.register(session.detach)
    if repl:
        _run_repl(
            {
                "config": config,
                "device": device,
                "pid": pid,
                "session": session,
                "script": script,
            }
        )
        return
    _wait_forever()


@click.group()
def cli() -> None:
    """Frida-Analykit v2 CLI."""


@cli.group("gen")
def gen_group() -> None:
    """Generate files for custom agent development."""


@gen_group.command("dev")
@click.option("--work-dir", default=".", show_default=True, type=click.Path(path_type=Path))
@click.option("--force", is_flag=True, help="Overwrite scaffold files if they already exist.")
@click.option(
    "--agent-package-spec",
    default=None,
    help="Override the npm dependency spec for @zsa233/frida-analykit-agent.",
)
def gen_dev(work_dir: Path, force: bool, agent_package_spec: str | None) -> None:
    created = generate_dev_workspace(
        work_dir,
        force=force,
        agent_package_spec=agent_package_spec,
    )
    click.echo(scaffold_summary(created))


@cli.group("server")
def server_group() -> None:
    """Remote frida-server management."""


@server_group.command("boot")
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
def server_boot(config_path: str) -> None:
    boot_server(_load_config(config_path))


@cli.command()
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_frontend_project_option()
@_frontend_install_option()
def build(config_path: str, project_dir: Path | None, install: bool) -> None:
    config = _load_config(config_path)
    try:
        project = load_frontend_project(config, project_dir=project_dir)
        bundle_path = build_agent_bundle(project, install=install)
    except FrontendError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"built `{bundle_path}`")


@cli.command()
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_frontend_project_option()
@_frontend_install_option()
def watch(config_path: str, project_dir: Path | None, install: bool) -> None:
    config = _load_config(config_path)
    try:
        project = load_frontend_project(config, project_dir=project_dir)
        watcher = start_watch(project, install=install)
        watcher.wait_until_ready()
        click.echo(f"watching `{project.entrypoint}` -> `{project.bundle_path}`")
        watcher.wait()
    except FrontendError as exc:
        raise click.ClickException(str(exc)) from exc
    except KeyboardInterrupt:
        pass
    finally:
        if "watcher" in locals():
            watcher.close()


@cli.command()
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@click.option("--repl", is_flag=True, help="Open a ptpython REPL after the script loads.")
@_frontend_build_option()
@_frontend_watch_option()
@_frontend_project_option()
@_frontend_install_option()
@click.option("--detach-on-load", is_flag=True, hidden=True)
def spawn(
    config_path: str,
    repl: bool,
    build_agent: bool,
    watch_agent: bool,
    project_dir: Path | None,
    install: bool,
    detach_on_load: bool,
) -> None:
    compat = FridaCompat()
    config = _load_config(config_path)
    if not config.app:
        raise click.ClickException("config.app is required for spawn")
    watcher = _prepare_frontend_assets(
        config=config,
        build_agent=build_agent,
        watch_agent=watch_agent,
        project_dir=project_dir,
        install=install,
    )

    try:
        device = compat.get_device(config.server.host)
        pid = device.spawn([config.app])
        device, session, script = _prepare_session(config, device, pid)
        device.resume(pid)
        _post_attach(
            config=config,
            device=device,
            session=session,
            script=script,
            pid=pid,
            repl=repl,
            detach_on_load=detach_on_load,
        )
    finally:
        if watcher is not None:
            watcher.close()


@cli.command()
@click.option("-p", "--pid", type=int, default=None)
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@click.option("--repl", is_flag=True, help="Open a ptpython REPL after the script loads.")
@_frontend_build_option()
@_frontend_watch_option()
@_frontend_project_option()
@_frontend_install_option()
@click.option("--detach-on-load", is_flag=True, hidden=True)
def attach(
    pid: int | None,
    config_path: str,
    repl: bool,
    build_agent: bool,
    watch_agent: bool,
    project_dir: Path | None,
    install: bool,
    detach_on_load: bool,
) -> None:
    compat = FridaCompat()
    config = _load_config(config_path)
    watcher = _prepare_frontend_assets(
        config=config,
        build_agent=build_agent,
        watch_agent=watch_agent,
        project_dir=project_dir,
        install=install,
    )
    try:
        device = compat.get_device(config.server.host)
        resolved_pid = pid
        if resolved_pid is None and config.app:
            resolved_pid = _find_app_pid(device, compat, config.app)
        if resolved_pid is None:
            raise click.ClickException("unable to resolve a target pid; set config.app or pass --pid")

        _, session, script = _prepare_session(config, device, resolved_pid)
        _post_attach(
            config=config,
            device=device,
            session=session,
            script=script,
            pid=resolved_pid,
            repl=repl,
            detach_on_load=detach_on_load,
        )
    finally:
        if watcher is not None:
            watcher.close()


@cli.command()
def doctor() -> None:
    report = FridaCompat().doctor_report()
    click.echo(f"Installed Frida: {report['installed_version']}")
    click.echo(f"Supported: {'yes' if report['supported'] else 'no'}")
    if report["matched_profile"]:
        click.echo(f"Matched profile: {report['matched_profile']}")
    else:
        click.echo("Matched profile: none")
    click.echo("Tested compatibility profiles:")
    for profile in report["profiles"]:
        click.echo(
            f"- {profile['name']}: {profile['series']} (tested {profile['tested_version']}, range {profile['range']})"
        )


def main() -> int:
    try:
        cli(standalone_mode=False)
        return 0
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
