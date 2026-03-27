from __future__ import annotations

import atexit
import os
import sys
import time
from pathlib import Path
from typing import Any

import click
import frida

from .compat import FridaCompat
from .config import AppConfig
from .dev_env import (
    DevEnvError,
    DevEnvManager,
    render_env_summary,
    render_install_summary,
    render_remove_summary,
)
from .diagnostics import set_verbose
from .frontend import FrontendError, WatchProcess, build_agent_bundle, load_frontend_project, start_watch
from .scaffold import generate_dev_workspace, scaffold_summary
from .server import FridaServerManager, ServerManagerError, boot_server, stop_server
from .session import SessionWrapper


def _load_config(path: str) -> AppConfig:
    return AppConfig.from_yaml(path)


def _load_optional_config(path: str) -> AppConfig | None:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return None
    return AppConfig.from_yaml(candidate)


def _frontend_project_option():
    return click.option(
        "--project-dir",
        type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
        default=None,
        help="Override the TypeScript agent workspace root. Defaults to the config directory.",
    )


def _verbose_option():
    return click.option(
        "--verbose",
        is_flag=True,
        help="Print diagnostic command execution details, including subprocess commands and captured output.",
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


def _configure_verbose(verbose: bool) -> None:
    set_verbose(verbose)


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
@_verbose_option()
def gen_dev(work_dir: Path, force: bool, agent_package_spec: str | None, verbose: bool) -> None:
    _configure_verbose(verbose)
    created = generate_dev_workspace(
        work_dir,
        force=force,
        agent_package_spec=agent_package_spec,
    )
    click.echo(scaffold_summary(created))


@cli.group("env", invoke_without_command=True)
@click.pass_context
def env_group(ctx: click.Context) -> None:
    """Manage isolated Frida environments."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@env_group.command("create")
@click.option("--profile", default=None, help="Create the environment from a named compatibility profile.")
@click.option("--frida-version", default=None, help="Create the environment with an explicit Frida version.")
@click.option("--name", default=None, help="Override the managed environment name.")
@click.option("--no-repl", is_flag=True, help="Skip installing the optional REPL dependencies.")
def env_create(profile: str | None, frida_version: str | None, name: str | None, no_repl: bool) -> None:
    try:
        env = _global_env_manager().create(
            name=name,
            profile=profile,
            frida_version=frida_version,
            with_repl=not no_repl,
        )
    except DevEnvError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_env_summary(env, action="created"))


@env_group.command("list")
def env_list() -> None:
    click.echo(_global_env_manager().render_list())


@env_group.command("shell")
@click.argument("name", required=False)
def env_shell(name: str | None) -> None:
    try:
        _global_env_manager().enter(name)
    except DevEnvError as exc:
        raise click.ClickException(str(exc)) from exc


@env_group.command("remove")
@click.argument("name", required=True)
def env_remove(name: str) -> None:
    try:
        env = _global_env_manager().remove(name)
    except DevEnvError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_remove_summary(env))


@env_group.command("use")
@click.argument("name", required=True)
def env_use(name: str) -> None:
    try:
        env = _global_env_manager().use(name)
    except DevEnvError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"current env: {env.name}")
    click.echo("current shell unchanged; run `frida-analykit env shell` to enter it.")


@env_group.command("install-frida")
@click.option("--version", "frida_version", required=True, help="Install an exact Frida version.")
@click.option(
    "--python",
    "python_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Target Python interpreter inside a virtual environment. Defaults to the current interpreter.",
)
def env_install_frida(frida_version: str, python_path: Path | None) -> None:
    manager = _global_env_manager()
    target_python = python_path or Path(sys.executable)
    try:
        payload = manager.install_frida(target_python, frida_version)
    except DevEnvError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        render_install_summary(
            python_path=Path(payload["python"]),
            env_dir=Path(payload["env_dir"]),
            frida_version=payload["frida_version"],
        )
    )


@cli.group("server")
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
    _configure_verbose(verbose)
    try:
        boot_server(_load_config(config_path), force_restart=force_restart)
    except ServerManagerError as exc:
        raise click.ClickException(str(exc)) from exc


@server_group.command("stop")
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_verbose_option()
def server_stop(config_path: str, verbose: bool) -> None:
    _configure_verbose(verbose)
    try:
        pids = stop_server(_load_config(config_path))
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
    _configure_verbose(verbose)
    if local_server is not None and server_version is not None:
        raise click.ClickException("`--local-server` cannot be combined with `--version`")
    if local_server is not None and force_download:
        raise click.ClickException("`--force-download` can only be used together with `--version`")
    if local_server is None and server_version is None and force_download:
        raise click.ClickException("`--force-download` requires an explicit `--version`")

    config = _load_config(config_path)
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
    click.echo(f"installed frida-server {result.installed_version or result.selected_version}")
    click.echo(f"remote path: {result.remote_path}")
    click.echo(f"device abi: {result.device_abi} ({result.asset_arch})")
    if result.local_source is not None:
        click.echo(f"local source: {result.local_source}")
    else:
        click.echo(f"local cache: {result.local_binary}")


@cli.command()
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_frontend_project_option()
@_frontend_install_option()
@_verbose_option()
def build(config_path: str, project_dir: Path | None, install: bool, verbose: bool) -> None:
    _configure_verbose(verbose)
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
@_verbose_option()
def watch(config_path: str, project_dir: Path | None, install: bool, verbose: bool) -> None:
    _configure_verbose(verbose)
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
    _configure_verbose(verbose)
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
    _configure_verbose(verbose)
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
@click.option("-c", "--config", "config_path", default="config.yml", show_default=True)
@_verbose_option()
def doctor(config_path: str, verbose: bool) -> None:
    _configure_verbose(verbose)
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
    config = _load_optional_config(config_path)
    if config is None:
        click.echo(f"Config: {Path(config_path).expanduser()} (not found, skipped remote server checks)")
        return

    click.echo(f"Config: {config.source_path}")
    click.echo(f"Configured server path: {config.server.servername}")
    click.echo(f"Configured server host: {config.server.host}")
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


def main() -> int:
    try:
        cli(standalone_mode=False)
        return 0
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
