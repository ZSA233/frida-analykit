from __future__ import annotations

import sys
from pathlib import Path

from .manager import EnvManager
from .models import EnvError
from .render import render_env_summary, render_remove_summary


def repo_cli_main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Manage repository-local Frida environments.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.epilog = (
        "Examples:\n"
        "  make env\n"
        "  make env-list\n"
        "  make env-create FRIDA_VERSION=16.5.9\n"
        "  make env-create FRIDA_VERSION=16.5.9 NO_REPL=1\n"
        "  make env-create FRIDA_VERSION=16.5.9 ENV_NAME=frida-16.5.9\n"
        "  make env-enter ENV_NAME=frida-16.5.9\n"
        "  make env-remove ENV_NAME=frida-16.5.9\n"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("help")
    subparsers.add_parser("list")

    gen_parser = subparsers.add_parser("gen")
    gen_group = gen_parser.add_mutually_exclusive_group(required=True)
    gen_group.add_argument("--profile")
    gen_group.add_argument("--frida-version")
    gen_parser.add_argument("--name")
    gen_parser.add_argument("--no-repl", action="store_true")

    enter_parser = subparsers.add_parser("enter")
    enter_parser.add_argument("--name")

    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("--name", required=True)

    args = parser.parse_args(argv)
    if args.command in {None, "help"}:
        parser.print_help()
        return 0

    manager = EnvManager.for_repo((repo_root or Path.cwd()).resolve())
    try:
        if args.command == "list":
            print(manager.render_list())
            return 0
        if args.command == "gen":
            env = manager.create(
                name=args.name,
                profile=args.profile,
                frida_version=args.frida_version,
                with_repl=not args.no_repl,
            )
            print(render_env_summary(env))
            return 0
        if args.command == "enter":
            manager.enter(args.name)
            return 0
        if args.command == "remove":
            env = manager.remove(args.name)
            print(render_remove_summary(env))
            return 0
    except EnvError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 1
