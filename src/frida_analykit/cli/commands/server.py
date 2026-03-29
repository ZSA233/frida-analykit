from __future__ import annotations

from pathlib import Path

import click

from ...server import FridaServerManager, ServerManagerError, boot_server, stop_server
from .. import common as cli_common
from ..common import _DownloadProgressReporter, _verbose_option


@click.group("server")
def server_group() -> None:
    """Remote frida-server management."""


@server_group.command("boot")
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@click.option(
    "--force-restart",
    is_flag=True,
    help="Kill an existing remote frida-server that matches config.server.servername before starting a new one.",
)
@_verbose_option()
def server_boot(config_path: str, force_restart: bool, verbose: bool) -> None:
    cli_common._configure_verbose(verbose)
    try:
        boot_server(cli_common._load_config(config_path), force_restart=force_restart)
    except ServerManagerError as exc:
        raise click.ClickException(str(exc)) from exc


@server_group.command("stop")
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_verbose_option()
def server_stop(config_path: str, verbose: bool) -> None:
    cli_common._configure_verbose(verbose)
    try:
        pids = stop_server(cli_common._load_config(config_path))
    except ServerManagerError as exc:
        raise click.ClickException(str(exc)) from exc
    if not pids:
        click.echo("no matching remote frida-server was running")
        return
    pid_list = ", ".join(str(pid) for pid in sorted(pids))
    click.echo(f"stopped remote frida-server pids: {pid_list}")


@server_group.command("install")
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@click.option(
    "--version",
    "server_version",
    default=None,
    help="Override the frida-server version to download instead of using config.server.version or the installed Frida version.",
)
@click.option(
    "--force-download",
    is_flag=True,
    help="Redownload the frida-server archive even when a cached copy is already available.",
)
@click.option(
    "--local-server",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=None,
    help="Push a local frida-server binary or .xz archive instead of downloading by version.",
)
@_verbose_option()
def server_install(
    config_path: str,
    server_version: str | None,
    force_download: bool,
    local_server: Path | None,
    verbose: bool,
) -> None:
    cli_common._configure_verbose(verbose)
    if local_server is not None and server_version is not None:
        raise click.ClickException("`--local-server` cannot be combined with `--version`")
    if local_server is not None and force_download:
        raise click.ClickException("`--force-download` can only be used together with `--version`")
    if local_server is None and server_version is None and force_download:
        raise click.ClickException("`--force-download` requires an explicit `--version`")

    config = cli_common._load_config(config_path)
    progress = _DownloadProgressReporter(label="Downloading frida-server") if server_version else None
    try:
        result = FridaServerManager().install_remote_server(
            config,
            version_override=server_version,
            local_server_path=local_server,
            force_download=force_download,
            download_progress=progress,
        )
    except ServerManagerError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if progress is not None:
            progress.close()
    click.echo(f"installed frida-server {result.installed_version}")
    click.echo(f"remote path: {result.remote_path}")
    if result.device_abi and result.asset_arch:
        click.echo(f"device abi: {result.device_abi} ({result.asset_arch})")
    elif result.local_source is not None:
        click.echo("device abi: skipped (local server source)")
    else:
        click.echo("device abi: unknown")
    if result.local_source is not None:
        click.echo(f"local source: {result.local_source}")
        if result.local_source_abi_hint and result.local_source_asset_arch_hint:
            click.echo(
                "local source arch hint: "
                f"{result.local_source_abi_hint} ({result.local_source_asset_arch_hint})"
            )
    else:
        click.echo(f"local cache: {result.local_binary}")
