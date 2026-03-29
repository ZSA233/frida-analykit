from __future__ import annotations

from pathlib import Path

import click

from ...compat import FridaCompat
from ...frontend import FrontendError, build_agent_bundle, load_frontend_project, start_watch
from .. import common as cli_common
from ..common import _frontend_build_option, _frontend_install_option, _frontend_project_option, _frontend_watch_option, _verbose_option


@click.command()
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_frontend_project_option()
@_frontend_install_option()
@_verbose_option()
def build(config_path: str, project_dir: Path | None, install: bool, verbose: bool) -> None:
    cli_common._configure_verbose(verbose)
    config = cli_common._load_config(config_path)
    try:
        project = load_frontend_project(config, project_dir=project_dir)
        bundle_path = build_agent_bundle(project, install=install)
    except FrontendError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"built `{bundle_path}`")


@click.command()
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_frontend_project_option()
@_frontend_install_option()
@_verbose_option()
def watch(config_path: str, project_dir: Path | None, install: bool, verbose: bool) -> None:
    cli_common._configure_verbose(verbose)
    config = cli_common._load_config(config_path)
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


@click.command()
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@click.option("--repl", is_flag=True, help="Open a ptpython REPL after the script loads.")
@_frontend_build_option()
@_frontend_watch_option()
@_frontend_project_option()
@_frontend_install_option()
@click.option("--detach-on-load", is_flag=True, hidden=True)
@_verbose_option()
def spawn(
    config_path: str,
    repl: bool,
    build_agent: bool,
    watch_agent: bool,
    project_dir: Path | None,
    install: bool,
    detach_on_load: bool,
    verbose: bool,
) -> None:
    cli_common._configure_verbose(verbose)
    compat = FridaCompat()
    config = cli_common._load_config(config_path)
    if not config.app:
        raise click.ClickException("config.app is required for spawn")
    watcher = cli_common._prepare_frontend_assets(
        config=config,
        build_agent=build_agent,
        watch_agent=watch_agent,
        project_dir=project_dir,
        install=install,
    )

    try:
        device = cli_common._resolve_runtime_device(config, compat)
        pid = device.spawn([config.app])
        device, session, script = cli_common._prepare_session(config, device, pid, interactive=repl)
        device.resume(pid)
        cli_common._post_attach(
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


@click.command()
@click.option("-p", "--pid", type=int, default=None)
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@click.option("--repl", is_flag=True, help="Open a ptpython REPL after the script loads.")
@_frontend_build_option()
@_frontend_watch_option()
@_frontend_project_option()
@_frontend_install_option()
@click.option("--detach-on-load", is_flag=True, hidden=True)
@_verbose_option()
def attach(
    pid: int | None,
    config_path: str,
    repl: bool,
    build_agent: bool,
    watch_agent: bool,
    project_dir: Path | None,
    install: bool,
    detach_on_load: bool,
    verbose: bool,
) -> None:
    cli_common._configure_verbose(verbose)
    compat = FridaCompat()
    config = cli_common._load_config(config_path)
    watcher = cli_common._prepare_frontend_assets(
        config=config,
        build_agent=build_agent,
        watch_agent=watch_agent,
        project_dir=project_dir,
        install=install,
    )
    try:
        device = cli_common._resolve_runtime_device(config, compat)
        resolved_pid = pid
        if resolved_pid is None and config.app:
            resolved_pid = cli_common._find_app_pid(device, compat, config.app)
        if resolved_pid is None:
            raise click.ClickException("unable to resolve a target pid; set config.app or pass --pid")

        _, session, script = cli_common._prepare_session(config, device, resolved_pid, interactive=repl)
        cli_common._post_attach(
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
