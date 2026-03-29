from __future__ import annotations

from pathlib import Path

import click

from ...scaffold import generate_dev_workspace, scaffold_summary
from .. import common as cli_common
from ..common import _verbose_option


@click.group("gen")
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
    cli_common._configure_verbose(verbose)
    created = generate_dev_workspace(
        work_dir,
        force=force,
        agent_package_spec=agent_package_spec,
    )
    click.echo(scaffold_summary(created))
