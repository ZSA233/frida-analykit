from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import click

from ...compat import FridaCompat
from ...config import AppConfig, DEFAULT_CONFIG_FILENAME
from ...development import (
    build_device_doctor_config,
    estimate_compat_boundary,
    resolve_device_compat_serials,
    run_device_compat_scan,
)
from ...device import DeviceSelectionError
from ...server import FridaServerManager, RemoteServerStatus, ServerManagerError
from .. import common as cli_common
from ..common import _verbose_option

DoctorLevel = Literal["ok", "info", "warn", "error"]

_DOCTOR_LEVEL_LABELS: dict[DoctorLevel, str] = {
    "ok": "OK",
    "info": "INFO",
    "warn": "WARN",
    "error": "ERROR",
}
_DOCTOR_LEVEL_COLORS: dict[DoctorLevel, str] = {
    "ok": "green",
    "info": "cyan",
    "warn": "yellow",
    "error": "red",
}


@dataclass(frozen=True, slots=True)
class DoctorFinding:
    level: DoctorLevel
    message: str
    code: str | None = None
    fixable: bool = False


@dataclass(frozen=True, slots=True)
class DoctorReport:
    compat_report: dict[str, object]
    config_path: Path
    config: AppConfig | None
    remote_status: RemoteServerStatus | None
    remote_error: str | None
    findings: tuple[DoctorFinding, ...]
    hints: tuple[str, ...]

    @property
    def has_errors(self) -> bool:
        return any(item.level == "error" for item in self.findings)

    @property
    def fixable_findings(self) -> tuple[DoctorFinding, ...]:
        return tuple(item for item in self.findings if item.fixable)


class ClickDeviceCompatProgressReporter:
    def __init__(self, *, verbose: bool) -> None:
        self._verbose = verbose
        self._last_device_stage: dict[tuple[int, str], str] = {}
        self._last_version_stage: dict[tuple[int, int, str, str], str] = {}

    def on_scan_start(self, *, serials: tuple[str, ...] | list[str] | object) -> None:
        values = tuple(str(item) for item in serials)
        _echo_doctor_line("info", f"Target devices: {', '.join(values) or 'none'}")

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
        _echo_doctor_line(
            "info",
            f"[device {device_index}/{device_total}] serial={serial} "
            f"remote_host={remote_host} sampled={versions_text}",
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
            _echo_doctor_line("info", f"{prefix} {stage}")
            self._last_device_stage[key] = stage
        if detail is not None and (self._verbose or detail.startswith("selected `")):
            _echo_doctor_line("info", f"{prefix} {stage}: {detail}")

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
        _echo_doctor_line(
            "info",
            f"[device {device_index}/{device_total}] [version {version_index}/{version_total}] {serial} {version} start",
        )

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
            _echo_doctor_line("info", f"{prefix} {stage}")
            self._last_version_stage[key] = stage
        if detail is not None and self._verbose:
            _echo_doctor_line("info", f"{prefix} {stage}: {detail}")

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
        _echo_doctor_line(
            _compat_result_level(result.status),
            f"[device {device_index}/{device_total}] [version {version_index}/{version_total}] "
            f"{serial} {version}{probe} {result.status}{stage}{suffix} ({result.elapsed_seconds:.2f}s) {result.detail}",
        )


def _doctor_command(config_path: Path, *parts: str) -> str:
    base = ["frida-analykit", "doctor", *parts, "--config", str(config_path)]
    return " ".join(shlex.quote(item) for item in base)


def _server_command(config_path: Path, *parts: str) -> str:
    base = ["frida-analykit", "server", *parts, "--config", str(config_path)]
    return " ".join(shlex.quote(item) for item in base)


def _echo_doctor_line(level: DoctorLevel, message: str) -> None:
    label = _DOCTOR_LEVEL_LABELS[level]
    click.secho(
        f"[{label}] {message}",
        fg=_DOCTOR_LEVEL_COLORS[level],
        bold=level in {"ok", "warn", "error"},
    )


def _compat_result_level(status: str) -> DoctorLevel:
    if status == "success":
        return "ok"
    if status in {"fail", "unavailable"}:
        return "error"
    return "warn"


def _format_source(source: str | None) -> str | None:
    if source is None:
        return None
    if source == "single connected adb device":
        return "auto-selected single device"
    return f"from {source}"


def _resolved_device(status: RemoteServerStatus, config: AppConfig) -> tuple[str | None, str | None]:
    device = getattr(status, "resolved_device", None) or getattr(status, "adb_target", None) or config.server.device
    source = getattr(status, "resolved_device_source", None)
    if source is None and config.server.device:
        source = "config.server.device"
    return device, source


def _selected_version(status: RemoteServerStatus, config: AppConfig) -> tuple[str, str]:
    version = getattr(status, "selected_version", None) or (config.server.version or "unknown")
    source = getattr(status, "selected_version_source", None)
    if source is None:
        source = "config.server.version" if config.server.version else "installed Frida"
    return version, source


def _build_local_frida_finding(report: dict[str, object]) -> DoctorFinding:
    installed = str(report["installed_version"])
    support_status = str(report["support_status"])
    matched_profile = report.get("matched_profile")
    if support_status == "tested":
        return DoctorFinding(
            "ok",
            f"Local Frida: {installed} ({support_status}, profile {matched_profile or 'none'})",
            code="local-frida",
        )
    if bool(report.get("supported")):
        return DoctorFinding(
            "warn",
            f"Local Frida: {installed} ({support_status}, supported range {report['support_range']})",
            code="local-frida",
        )
    return DoctorFinding(
        "error",
        f"Local Frida: {installed} is unsupported (supported range {report['support_range']})",
        code="local-frida",
    )


def _build_remote_findings(config: AppConfig, status: RemoteServerStatus) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    target_device, device_source = _resolved_device(status, config)
    target_version, version_source = _selected_version(status, config)
    formatted_device_source = _format_source(device_source)
    formatted_version_source = _format_source(version_source)
    device_suffix = f" ({formatted_device_source})" if formatted_device_source else ""
    version_suffix = f" ({formatted_version_source})" if formatted_version_source else ""

    findings.append(
        DoctorFinding(
            "info",
            f"Target device: {target_device or 'unknown'}{device_suffix}",
            code="target-device",
        )
    )
    findings.append(
        DoctorFinding(
            "info",
            f"Target server version: {target_version}{version_suffix}",
            code="target-version",
        )
    )

    if status.exists and status.installed_version:
        findings.append(
            DoctorFinding(
                "info",
                f"Remote server version: {status.installed_version} at {status.server_path}",
                code="remote-version",
            )
        )
    elif status.exists:
        findings.append(
            DoctorFinding(
                "info",
                f"Remote server binary exists at {status.server_path}",
                code="remote-binary",
            )
        )

    if not status.exists:
        findings.append(
            DoctorFinding(
                "error",
                f"Remote server binary is missing at {status.server_path}",
                code="missing-binary",
                fixable=True,
            )
        )
    elif not status.executable:
        findings.append(
            DoctorFinding(
                "error",
                f"Remote server binary exists at {status.server_path} but is not executable or its version probe failed",
                code="not-executable",
                fixable=True,
            )
        )

    if status.installed_version is not None:
        if status.version_matches_target is True:
            findings.append(
                DoctorFinding(
                    "ok",
                    f"Remote server version matches target {target_version}",
                    code="version-match",
                )
            )
        elif status.version_matches_target is False:
            findings.append(
                DoctorFinding(
                    "error",
                    f"Remote server version mismatch: target {target_version}, device has {status.installed_version}",
                    code="version-mismatch",
                    fixable=True,
                )
            )

    if status.host_reachable is True:
        findings.append(
            DoctorFinding(
                "ok",
                f"Remote host reachable: yes ({config.server.host})",
                code="host-reachable",
            )
        )
    elif status.host_reachable is False:
        suffix = f" ({status.host_error})" if status.host_error else ""
        findings.append(
            DoctorFinding(
                "error",
                f"Remote host reachable: no{suffix}",
                code="host-unreachable",
            )
        )

    if status.protocol_compatible is True:
        findings.append(
            DoctorFinding(
                "ok",
                "Remote protocol compatible: yes",
                code="protocol-compatible",
            )
        )
    elif status.protocol_compatible is False:
        suffix = f" ({status.protocol_error})" if status.protocol_error else ""
        findings.append(
            DoctorFinding(
                "error",
                f"Remote protocol compatible: no{suffix}",
                code="protocol-incompatible",
            )
        )

    return findings


def _build_doctor_hints(report: DoctorReport) -> tuple[str, ...]:
    hints: list[str] = []
    if report.fixable_findings:
        hints.append(
            f"Run `{_doctor_command(report.config_path, 'fix')}` to repair remote frida-server install/version issues."
        )
    if any(item.code in {"host-unreachable", "protocol-incompatible"} for item in report.findings):
        hints.append(
            f"Run `{_server_command(report.config_path, 'boot')}` after install/version issues are resolved."
        )
    return tuple(dict.fromkeys(hints))


def _build_doctor_report(
    config_path: str,
    *,
    compat: FridaCompat | None = None,
    manager: FridaServerManager | None = None,
) -> DoctorReport:
    compat = compat or FridaCompat()
    compat_report = compat.doctor_report()
    resolved_path = Path(config_path).expanduser()
    config = cli_common._load_optional_config(config_path)
    remote_status: RemoteServerStatus | None = None
    remote_error: str | None = None

    if config is not None and config.server.is_remote:
        manager = manager or FridaServerManager(compat=compat)
        try:
            remote_status = manager.inspect_remote_server(config, probe_host=True)
        except ServerManagerError as exc:
            remote_error = str(exc)

    findings: list[DoctorFinding] = [_build_local_frida_finding(compat_report)]
    if config is None:
        findings.append(
            DoctorFinding(
                "warn",
                f"Config not found: {resolved_path}; remote server checks skipped",
                code="config-missing",
            )
        )
    elif not config.server.is_remote:
        findings.append(
            DoctorFinding(
                "info",
                "Remote server checks skipped because server.host uses local or usb mode",
                code="remote-skipped",
            )
        )
    elif remote_error is not None:
        findings.append(
            DoctorFinding(
                "error",
                f"Remote server checks failed: {remote_error}",
                code="remote-check-error",
            )
        )
    elif remote_status is not None:
        findings.extend(_build_remote_findings(config, remote_status))

    report = DoctorReport(
        compat_report=compat_report,
        config_path=config.source_path if config is not None and config.source_path is not None else resolved_path,
        config=config,
        remote_status=remote_status,
        remote_error=remote_error,
        findings=tuple(findings),
        hints=(),
    )
    return DoctorReport(
        compat_report=report.compat_report,
        config_path=report.config_path,
        config=report.config,
        remote_status=report.remote_status,
        remote_error=report.remote_error,
        findings=report.findings,
        hints=_build_doctor_hints(report),
    )


def _emit_doctor_verbose(report: DoctorReport) -> None:
    click.echo("")
    _echo_doctor_line("info", "Verbose details:")
    click.echo(f"  Config: {report.config_path}")
    click.echo(f"  Support status: {report.compat_report['support_status']}")
    click.echo(f"  Supported range: {report.compat_report['support_range']}")
    click.echo(f"  Matched profile: {report.compat_report['matched_profile'] or 'none'}")
    click.echo(f"  Tested version in profile: {report.compat_report['tested_version'] or 'none'}")
    click.echo("  Tested compatibility profiles:")
    for profile in report.compat_report["profiles"]:
        click.echo(
            "  - "
            f"{profile['name']}: {profile['series']} "
            f"(tested {profile['tested_version']}, range {profile['range']})"
        )
    if report.config is None:
        return
    click.echo(f"  Configured server host: {report.config.server.host}")
    click.echo(f"  Configured server path: {report.config.server.path}")
    click.echo(f"  Configured server device: {report.config.server.device or 'none'}")
    click.echo(f"  Configured server version: {report.config.server.version or 'none'}")
    if report.remote_status is None:
        if report.remote_error:
            click.echo(f"  Remote server checks error: {report.remote_error}")
        return
    status = report.remote_status
    click.echo(f"  ADB target device: {status.adb_target or 'unknown'}")
    if status.device_abi and status.asset_arch:
        click.echo(f"  Device ABI: {status.device_abi} ({status.asset_arch})")
    elif status.error:
        click.echo(f"  Device ABI: unknown ({status.error})")
    click.echo(f"  Remote server exists: {'yes' if status.exists else 'no'}")
    click.echo(f"  Remote server executable: {'yes' if status.executable else 'no'}")
    if status.installed_version:
        click.echo(f"  Remote server supported: {'yes' if status.supported else 'no'}")
        click.echo(f"  Remote server profile: {status.matched_profile or 'none'}")


def _emit_doctor_report(report: DoctorReport, *, verbose: bool) -> None:
    for item in report.findings:
        _echo_doctor_line(item.level, item.message)
    if report.hints:
        click.echo("")
        for hint in report.hints:
            _echo_doctor_line("info", hint)
    if verbose:
        _emit_doctor_verbose(report)


def _doctor_fix_failure_message(report: DoctorReport) -> str:
    if any(item.code in {"host-unreachable", "protocol-incompatible"} for item in report.findings):
        return (
            f"doctor fix left unresolved runtime issues; run `{_server_command(report.config_path, 'boot')}` "
            "to restart the remote frida-server"
        )
    return "doctor fix left unresolved issues"


def _run_default_doctor(config_path: str, *, verbose: bool) -> DoctorReport:
    report = _build_doctor_report(config_path)
    _emit_doctor_report(report, verbose=verbose)
    return report


def _emit_device_compat_summary(summary) -> None:
    _echo_doctor_line("info", f"Device: {summary.serial}")
    _echo_doctor_line("info", f"Remote host: {summary.remote_host}")
    _echo_doctor_line("info", f"Sampled versions: {', '.join(summary.sampled_versions) or 'none'}")
    probe_kinds: list[str] = []
    seen_probes: set[str] = set()
    for result in summary.results:
        if result.probe_kind in seen_probes:
            continue
        seen_probes.add(result.probe_kind)
        probe_kinds.append(result.probe_kind)
    for probe_kind in probe_kinds:
        probe_results = tuple(result for result in summary.results if result.probe_kind == probe_kind)
        _echo_doctor_line("info", f"Probe: {probe_kind}")
        for result in probe_results:
            suffix = f" app={result.app}" if result.app else ""
            stage = f" stage={result.stage}" if result.stage else ""
            _echo_doctor_line(
                _compat_result_level(result.status),
                f"- {result.version}: {result.status}{stage}{suffix} "
                f"({result.elapsed_seconds:.2f}s) {result.detail}",
            )
        _echo_doctor_line("info", f"Estimated boundary: {estimate_compat_boundary(probe_results)}")


@click.group(invoke_without_command=True)
@click.option("-c", "--config", "config_path", default=DEFAULT_CONFIG_FILENAME, show_default=True)
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
    _run_default_doctor(config_path, verbose=verbose)


@doctor.command("fix")
@click.option("-c", "--config", "config_path", default=DEFAULT_CONFIG_FILENAME, show_default=True)
@_verbose_option()
@click.pass_context
def doctor_fix(ctx: click.Context, config_path: str, verbose: bool) -> None:
    parent_options = ctx.parent.obj if ctx.parent is not None and isinstance(ctx.parent.obj, dict) else {}
    if config_path == DEFAULT_CONFIG_FILENAME and isinstance(parent_options.get("config_path"), str):
        config_path = parent_options["config_path"]
    verbose = verbose or bool(parent_options.get("verbose"))
    cli_common._configure_verbose(verbose)

    compat = FridaCompat()
    manager = FridaServerManager(compat=compat)
    report = _build_doctor_report(config_path, compat=compat, manager=manager)
    _emit_doctor_report(report, verbose=verbose)

    if report.config is None:
        raise click.ClickException("doctor fix requires an existing config file")
    if not report.config.server.is_remote:
        if report.has_errors:
            raise click.ClickException("doctor fix found issues outside remote frida-server install/version management")
        _echo_doctor_line("ok", "No fixable remote frida-server issues found for this config.")
        return
    if not report.fixable_findings:
        if report.has_errors:
            raise click.ClickException("doctor fix found no install/version issues it can repair automatically")
        _echo_doctor_line("ok", "No fixable remote frida-server issues found.")
        return

    click.echo("")
    target_version, target_source = _selected_version(
        report.remote_status if report.remote_status is not None else RemoteServerStatus(
            selected_version=report.config.server.version or str(compat.installed_version),
            selected_version_source="config.server.version" if report.config.server.version else "installed Frida",
            configured_version=report.config.server.version,
            server_path=report.config.server.path,
            adb_target=report.config.server.device,
            resolved_device=report.config.server.device,
            resolved_device_source="config.server.device" if report.config.server.device else None,
            exists=False,
            executable=False,
            installed_version=None,
            version_matches_target=None,
            supported=None,
            matched_profile=None,
            device_abi=None,
            asset_arch=None,
        ),
        report.config,
    )
    target_source_text = _format_source(target_source)
    target_suffix = f" ({target_source_text})" if target_source_text else ""
    _echo_doctor_line(
        "info",
        f"Applying doctor fix: reinstall remote frida-server {target_version}{target_suffix}",
    )
    try:
        manager.install_remote_server(report.config)
    except ServerManagerError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("")
    rerun_report = _build_doctor_report(config_path, compat=compat, manager=manager)
    _emit_doctor_report(rerun_report, verbose=verbose)
    if rerun_report.has_errors:
        raise click.ClickException(_doctor_fix_failure_message(rerun_report))


@doctor.command("device-compat")
@click.option("-c", "--config", "config_path", default=DEFAULT_CONFIG_FILENAME, show_default=True)
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
    if config_path == DEFAULT_CONFIG_FILENAME and isinstance(parent_options.get("config_path"), str):
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
        _emit_device_compat_summary(summary)
        if any(result.status != "success" for result in summary.results):
            failed = True
    if failed:
        raise click.ClickException("device compatibility scan reported failures or unavailable versions")
