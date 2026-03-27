from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from string import Template

from ._version import __version__
from .release_version import agent_package_spec_for_python_release


AGENT_PACKAGE_NAME = "@zsa233/frida-analykit-agent"


def default_agent_package_spec(version: str = __version__) -> str:
    return agent_package_spec_for_python_release(version)


def _template_dir():
    return files("frida_analykit.resources").joinpath("templates").joinpath("dev")


def _render_template(name: str, variables: dict[str, str]) -> str:
    template = _template_dir().joinpath(name).read_text(encoding="utf-8")
    return Template(template).safe_substitute(variables)


def generate_dev_workspace(
    work_dir: str | Path,
    *,
    force: bool = False,
    agent_package_spec: str | None = None,
) -> list[Path]:
    target = Path(work_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    package_spec = agent_package_spec or default_agent_package_spec()
    variables = {
        "agent_package_name": AGENT_PACKAGE_NAME,
        "agent_package_spec": package_spec,
        "version": __version__,
    }

    created: list[Path] = []
    for name in ("config.yml", "index.ts", "package.json", "tsconfig.json", "README.md"):
        destination = target / name
        if destination.exists() and not force:
            continue
        destination.write_text(_render_template(name, variables), encoding="utf-8")
        created.append(destination)
    return created


def scaffold_summary(paths: list[Path]) -> str:
    if not paths:
        return "no files created; use --force to overwrite existing scaffold files"
    return "\n".join(str(path) for path in paths)
