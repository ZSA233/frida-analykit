from __future__ import annotations

import sys
from pathlib import Path

import click

from ...env import EnvError, render_env_summary, render_install_summary, render_remove_summary
from .. import common as cli_common


@click.group("env", invoke_without_command=True)
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
        env = cli_common._global_env_manager().create(
            name=name,
            profile=profile,
            frida_version=frida_version,
            with_repl=not no_repl,
        )
    except EnvError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_env_summary(env, action="created"))


@env_group.command("list")
def env_list() -> None:
    click.echo(cli_common._global_env_manager().render_list())


@env_group.command("shell")
@click.argument("name", required=False)
def env_shell(name: str | None) -> None:
    try:
        cli_common._global_env_manager().enter(name)
    except EnvError as exc:
        raise click.ClickException(str(exc)) from exc


@env_group.command("remove")
@click.argument("name", required=True)
def env_remove(name: str) -> None:
    try:
        env = cli_common._global_env_manager().remove(name)
    except EnvError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(render_remove_summary(env))


@env_group.command("use")
@click.argument("name", required=True)
def env_use(name: str) -> None:
    try:
        env = cli_common._global_env_manager().use(name)
    except EnvError as exc:
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
    manager = cli_common._global_env_manager()
    target_python = python_path or Path(sys.executable)
    try:
        payload = manager.install_frida(target_python, frida_version)
    except EnvError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        render_install_summary(
            python_path=Path(payload["python"]),
            env_dir=Path(payload["env_dir"]),
            frida_version=payload["frida_version"],
        )
    )
