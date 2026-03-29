from __future__ import annotations

from pathlib import Path

import click

from ...compat import FridaCompat
from ...server import FridaServerManager, ServerManagerError
from .. import common as cli_common
from ..common import _verbose_option


@click.command()
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_verbose_option()
def doctor(config_path: str, verbose: bool) -> None:
    cli_common._configure_verbose(verbose)
    compat = FridaCompat()
    report = compat.doctor_report()
    click.echo(f"Installed Frida: {report['installed_version']}")
    click.echo(f"Support status: {report['support_status']}")
    click.echo(f"Supported range: {report['support_range']}")
    click.echo(f"Supported: {'yes' if report['supported'] else 'no'}")
    click.echo(f"Matched profile: {report['matched_profile'] or 'none'}")
    click.echo(f"Tested version in profile: {report['tested_version'] or 'none'}")
    click.echo("Tested compatibility profiles:")
    for profile in report["profiles"]:
        click.echo(
            f"- {profile['name']}: {profile['series']} (tested {profile['tested_version']}, range {profile['range']})"
        )
    config = cli_common._load_optional_config(config_path)
    if config is None:
        click.echo(f"Config: {Path(config_path).expanduser()} (not found, skipped remote server checks)")
        return

    click.echo(f"Config: {config.source_path}")
    click.echo(f"Configured server path: {config.server.servername}")
    click.echo(f"Configured server host: {config.server.host}")
    click.echo(f"Configured server device: {config.server.device or 'none'}")
    click.echo(f"Configured server version: {config.server.version or 'none'}")

    if not config.server.is_remote:
        click.echo("Remote server checks: skipped (config.server.host uses local or usb mode)")
        return

    manager = FridaServerManager(compat=compat)
    try:
        status = manager.inspect_remote_server(config)
    except ServerManagerError as exc:
        click.echo(f"Remote server checks: error ({exc})")
        return

    click.echo(f"Install target version: {status.selected_version}")
    click.echo(f"ADB target device: {status.adb_target or 'unknown'}")
    if status.device_abi and status.asset_arch:
        click.echo(f"Device ABI: {status.device_abi} ({status.asset_arch})")
    elif status.error:
        click.echo(f"Device ABI: unknown ({status.error})")

    click.echo(f"Remote server exists: {'yes' if status.exists else 'no'}")
    if status.exists:
        click.echo(f"Remote server executable: {'yes' if status.executable else 'no'}")
    if status.installed_version:
        click.echo(f"Remote server version: {status.installed_version}")
        click.echo(f"Remote server supported: {'yes' if status.supported else 'no'}")
        click.echo(f"Remote server profile: {status.matched_profile or 'none'}")
