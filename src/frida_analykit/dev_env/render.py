from __future__ import annotations

from pathlib import Path

from .models import ManagedEnv
from .paths import _activate_path, _binary_path


def render_env_summary(env: ManagedEnv, *, action: str = "ready") -> str:
    lines = [
        f"{action} managed env `{env.name}`",
        f"path: {env.env_dir}",
        f"python: {env.python_path}",
        f"activate: {env.activate_path}",
        f"frida: {env.frida_version}",
        f"frida-analykit version: {env.frida_analykit_version}",
        f"source: {env.source_label}",
    ]
    if env.frida_cli_path.exists():
        lines.append(f"frida-cli: {env.frida_cli_path}")
    if env.frida_analykit_path.exists():
        lines.append(f"frida-analykit: {env.frida_analykit_path}")
    return "\n".join(lines)


def render_install_summary(*, python_path: Path, env_dir: Path, frida_version: str) -> str:
    lines = [
        f"updated Frida runtime in `{env_dir.name}`",
        f"path: {env_dir}",
        f"python: {python_path}",
        f"activate: {_activate_path(env_dir)}",
        f"frida: {frida_version}",
    ]
    frida_cli = _binary_path(env_dir, "frida")
    if frida_cli.exists():
        lines.append(f"frida-cli: {frida_cli}")
    return "\n".join(lines)


def render_remove_summary(env: ManagedEnv) -> str:
    return "\n".join(
        [
            f"removed managed env `{env.name}`",
            f"path: {env.env_dir}",
            f"frida: {env.frida_version}",
            f"frida-analykit version: {env.frida_analykit_version}",
            f"source: {env.source_label}",
        ]
    )
