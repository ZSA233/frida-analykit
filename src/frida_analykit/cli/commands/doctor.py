from __future__ import annotations

import os
from pathlib import Path

import click

from ...compat import FridaCompat
from ...development import (
    build_device_doctor_config,
    format_device_compat_summary,
    resolve_device_compat_serials,
    run_device_compat_scan,
)
from ...device import DeviceSelectionError
from ...server import FridaServerManager, ServerManagerError
from .. import common as cli_common
from ..common import _verbose_option


class ClickDeviceCompatProgressReporter:
    def __init__(self, *, verbose: bool) -> None:
        self._verbose = verbose
        self._last_device_stage: dict[tuple[int, str], str] = {}
        self._last_version_stage: dict[tuple[int, int, str, str], str] = {}

    def on_scan_start(self, *, serials: tuple[str, ...] | list[str] | object) -> None:
        values = tuple(str(item) for item in serials)
        click.echo(f"Target devices: {', '.join(values) or 'none'}")

    def on_device_start(
        self,
        *,
        device_index: int,
        device_total: int,
        serial: str,
        remote_host: str,
        sampled_versions,
    ) -> None:
        self._last_device_stage.pop((device_index, serial), None)
        versions_text = ", ".join(sampled_versions) or "none"
        click.echo(
            f"[device {device_index}/{device_total}] serial={serial} "
            f"remote_host={remote_host} sampled={versions_text}"
        )

    def on_device_stage(
        self,
        *,
        device_index: int,
        device_total: int,
        serial: str,
        stage: str,
        detail: str | None = None,
    ) -> None:
        key = (device_index, serial)
        prefix = f"[device {device_index}/{device_total}] {serial}"
        if self._last_device_stage.get(key) != stage:
            click.echo(f"{prefix} {stage}")
            self._last_device_stage[key] = stage
        if detail is not None and (self._verbose or detail.startswith("selected `")):
            click.echo(f"{prefix} {stage}: {detail}")

    def on_version_start(
        self,
        *,
        device_index: int,
        device_total: int,
        version_index: int,
        version_total: int,
        serial: str,
        version: str,
    ) -> None:
        key = (device_index, version_index, serial, version)
        self._last_version_stage.pop(key, None)
        click.echo(f"[device {device_index}/{device_total}] [version {version_index}/{version_total}] {serial} {version} start")

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
    ) -> None:
        key = (device_index, version_index, serial, version)
        prefix = f"[device {device_index}/{device_total}] [version {version_index}/{version_total}] {serial} {version}"
        if self._last_version_stage.get(key) != stage:
            click.echo(f"{prefix} {stage}")
            self._last_version_stage[key] = stage
        if detail is not None and self._verbose:
            click.echo(f"{prefix} {stage}: {detail}")

    def on_version_result(
        self,
        *,
        device_index: int,
        device_total: int,
        version_index: int,
        version_total: int,
        serial: str,
        version: str,
        result,
    ) -> None:
        probe = f" [{result.probe_kind}]" if getattr(result, "probe_kind", None) else ""
        suffix = f" app={result.app}" if result.app else ""
        stage = f" stage={result.stage}" if result.stage else ""
        click.echo(
            f"[device {device_index}/{device_total}] [version {version_index}/{version_total}] "
            f"{serial} {version}{probe} {result.status}{stage}{suffix} ({result.elapsed_seconds:.2f}s) {result.detail}"
        )


def _run_default_doctor(config_path: str) -> None:
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


@click.group(invoke_without_command=True)
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_verbose_option()
@click.pass_context
def doctor(ctx: click.Context, config_path: str, verbose: bool) -> None:
    ctx.obj = {
        "config_path": config_path,
        "verbose": verbose,
    }
    cli_common._configure_verbose(verbose)
    if ctx.invoked_subcommand is not None:
        return
    _run_default_doctor(config_path)


@doctor.command("device-compat")
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_verbose_option()
@click.option("--serial", "serials", multiple=True)
@click.option("--all-devices", is_flag=True, help="Run the compatibility probe on every connected adb device.")
@click.option("--iterations", default=3, show_default=True, type=int)
@click.option("--versions", default=None, help="Comma-separated Frida versions to sample.")
@click.option(
    "--install-missing-env",
    is_flag=True,
    help="Automatically create missing repo-local managed envs for explicitly requested --versions before scanning.",
)
@click.option("--app", "app_id", default=None, help="Explicit Android package to use for compatibility probing.")
@click.option(
    "--probe",
    "probe_kinds",
    multiple=True,
    type=click.Choice(("spawn", "attach")),
    help="Compatibility probe kind. Repeat to select multiple; defaults to testing both spawn and attach.",
)
@click.pass_context
def doctor_device_compat(
    ctx: click.Context,
    config_path: str,
    verbose: bool,
    serials: tuple[str, ...],
    all_devices: bool,
    iterations: int,
    versions: str | None,
    install_missing_env: bool,
    app_id: str | None,
    probe_kinds: tuple[str, ...],
) -> None:
    parent_options = ctx.parent.obj if ctx.parent is not None and isinstance(ctx.parent.obj, dict) else {}
    if config_path == "config.yml" and isinstance(parent_options.get("config_path"), str):
        config_path = parent_options["config_path"]
    verbose = verbose or bool(parent_options.get("verbose"))
    cli_common._configure_verbose(verbose)
    repo_root = Path(__file__).resolve().parents[4]
    src_root = repo_root / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{src_root}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(src_root)
    env["PYTHONUNBUFFERED"] = "1"

    loaded = cli_common._load_optional_config(config_path)
    config = loaded or build_device_doctor_config(repo_root, app=None)

    try:
        target_serials = resolve_device_compat_serials(
            explicit_serials=serials,
            all_devices=all_devices,
            config_serial=loaded.server.device if loaded is not None else None,
            env_serial=os.environ.get("ANDROID_SERIAL"),
            env=env,
            cwd=repo_root,
        )
    except DeviceSelectionError as exc:
        raise click.ClickException(str(exc)) from exc

    requested_versions = tuple(item.strip() for item in versions.split(",") if item.strip()) if versions else ()
    reporter = ClickDeviceCompatProgressReporter(verbose=verbose)
    summaries = run_device_compat_scan(
        repo_root,
        env=env,
        config=config,
        serials=target_serials,
        requested_versions=requested_versions,
        iterations=iterations,
        app=app_id,
        probe_kinds=probe_kinds,
        install_missing_env=install_missing_env,
        reporter=reporter,
    )
    failed = False
    for index, summary in enumerate(summaries):
        if index:
            click.echo("")
        click.echo(format_device_compat_summary(summary))
        if any(result.status != "success" for result in summary.results):
            failed = True
    if failed:
        raise click.ClickException("device compatibility scan reported failures or unavailable versions")
