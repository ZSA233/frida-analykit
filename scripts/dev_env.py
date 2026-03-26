#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


COMPAT_PROFILES_PATH = Path("src/frida_analykit/resources/compat_profiles.json")


class DevEnvError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompatProfile:
    name: str
    tested_version: str


def load_profiles(repo_root: Path) -> dict[str, CompatProfile]:
    payload = json.loads((repo_root / COMPAT_PROFILES_PATH).read_text(encoding="utf-8"))
    profiles: dict[str, CompatProfile] = {}
    for item in payload["profiles"]:
        profiles[item["name"]] = CompatProfile(
            name=item["name"],
            tested_version=item["tested_version"],
        )
    return profiles


def _run_checked(command: list[str], *, cwd: Path, error_message: str) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if detail:
            raise DevEnvError(f"{error_message}: {detail}")
        raise DevEnvError(error_message)


def prepare_environment(
    repo_root: Path,
    *,
    env_name: str,
    frida_version: str,
) -> dict[str, str]:
    env_dir = repo_root / env_name
    if sys.platform == "win32":
        python_path = env_dir / "Scripts" / "python.exe"
    else:
        python_path = env_dir / "bin" / "python"

    _run_checked(
        ["uv", "venv", str(env_dir), "--python", "3.11"],
        cwd=repo_root,
        error_message=f"Failed to create {env_name}",
    )
    _run_checked(
        ["uv", "sync", "--extra", "repl", "--dev", "--python", str(python_path)],
        cwd=repo_root,
        error_message=f"Failed to sync project dependencies into {env_name}",
    )
    _run_checked(
        ["uv", "pip", "install", "--python", str(python_path), f"frida=={frida_version}"],
        cwd=repo_root,
        error_message=f"Failed to install frida=={frida_version} into {env_name}",
    )

    return {
        "env_dir": str(env_dir),
        "python": str(python_path),
        "frida_version": frida_version,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare local Frida development environments")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    group = prepare_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--profile")
    group.add_argument("--frida-version")
    prepare_parser.add_argument("--env-name")
    prepare_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    repo_root = Path.cwd()

    try:
        if args.command == "prepare":
            profiles = load_profiles(repo_root)
            if args.profile:
                if args.profile not in profiles:
                    available = ", ".join(sorted(profiles))
                    raise DevEnvError(f"Unknown profile {args.profile}. Available: {available}")
                frida_version = profiles[args.profile].tested_version
                env_name = args.env_name or f".venv-{args.profile}"
            else:
                frida_version = args.frida_version
                env_name = args.env_name or f".venv-frida-{frida_version}"

            payload = prepare_environment(
                repo_root,
                env_name=env_name,
                frida_version=frida_version,
            )
            if args.json:
                print(json.dumps(payload, separators=(",", ":")))
            else:
                print(f"prepared {payload['env_dir']}")
                print(f"python: {payload['python']}")
                print(f"frida: {payload['frida_version']}")
            return 0
    except DevEnvError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
