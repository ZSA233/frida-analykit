from __future__ import annotations

import click

from .._version import __version__
from .commands.doctor import doctor
from .commands.env import env_group
from .commands.gen import gen_group
from .commands.runtime import attach, build, spawn, watch
from .commands.server import server_group


@click.group()
@click.version_option(__version__, prog_name="frida-analykit")
def cli() -> None:
    """Frida-Analykit v2 CLI."""


cli.add_command(gen_group)
cli.add_command(env_group)
cli.add_command(server_group)
cli.add_command(build)
cli.add_command(watch)
cli.add_command(spawn)
cli.add_command(attach)
cli.add_command(doctor)


def main() -> int:
    try:
        cli(standalone_mode=False)
        return 0
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code


__all__ = ["cli", "main"]
