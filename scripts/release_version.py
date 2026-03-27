#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from frida_analykit.release_version import (
    ReleaseVersion,
    ReleaseVersionError,
    parse_npm_release_version,
    parse_python_release_version,
    parse_release_tag,
)


RELEASE_VERSION_PATH = Path("release-version.toml")
VERSION_FILE_PATH = Path("src/frida_analykit/_version.py")
ROOT_PACKAGE_JSON_PATH = Path("package.json")
AGENT_PACKAGE_JSON_PATH = Path("packages/frida-analykit-agent/package.json")
PACKAGE_LOCK_PATH = Path("package-lock.json")
AGENT_PACKAGE_NAME = "@zsa233/frida-analykit-agent"
VERSION_ASSIGNMENT_RE = re.compile(r'^(__version__\s*=\s*")([^"]+)("\s*)$', re.MULTILINE)
MANAGED_VERSION_PATHS = (
    RELEASE_VERSION_PATH,
    VERSION_FILE_PATH,
    ROOT_PACKAGE_JSON_PATH,
    AGENT_PACKAGE_JSON_PATH,
    PACKAGE_LOCK_PATH,
)


class ReleaseVersionToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseVersionConfig:
    base_version: str
    channel: str
    rc_number: int | None = None

    @property
    def release(self) -> ReleaseVersion:
        if self.channel == "stable":
            return ReleaseVersion(base_version=self.base_version)
        return ReleaseVersion(base_version=self.base_version, rc_number=self.rc_number)


@dataclass(frozen=True)
class RepositoryVersionState:
    python_version: str
    root_npm_version: str
    agent_npm_version: str
    root_agent_dependency: str
    lock_root_version: str | None
    lock_root_agent_dependency: str | None
    lock_agent_version: str | None


def _read_text(repo_root: Path, relative_path: Path) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def _write_text(repo_root: Path, relative_path: Path, content: str) -> None:
    (repo_root / relative_path).write_text(content, encoding="utf-8")


def load_json_file(repo_root: Path, relative_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(_read_text(repo_root, relative_path))
    except json.JSONDecodeError as exc:
        raise ReleaseVersionToolError(f"{relative_path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseVersionToolError(f"{relative_path} must contain a JSON object")
    return payload


def write_json_file(repo_root: Path, relative_path: Path, payload: dict[str, Any]) -> None:
    _write_text(repo_root, relative_path, json.dumps(payload, indent=2) + "\n")


def parse_version_assignment(text: str) -> str:
    match = VERSION_ASSIGNMENT_RE.search(text)
    if not match:
        raise ReleaseVersionToolError("Could not locate __version__ assignment")
    return match.group(2)


def replace_version_assignment(text: str, version: str) -> str:
    updated, count = VERSION_ASSIGNMENT_RE.subn(
        lambda match: f'{match.group(1)}{version}{match.group(3)}',
        text,
        count=1,
    )
    if count != 1:
        raise ReleaseVersionToolError("Could not update __version__ assignment")
    return updated


def parse_release_version_config(payload: dict[str, Any]) -> ReleaseVersionConfig:
    allowed_keys = {"base_version", "channel", "rc_number"}
    unexpected = sorted(set(payload) - allowed_keys)
    if unexpected:
        raise ReleaseVersionToolError(
            "release-version.toml contains unsupported keys: " + ", ".join(unexpected)
        )

    base_version = payload.get("base_version")
    channel = payload.get("channel")
    rc_number = payload.get("rc_number")

    if not isinstance(base_version, str):
        raise ReleaseVersionToolError("release-version.toml base_version must be a string")
    if not isinstance(channel, str):
        raise ReleaseVersionToolError("release-version.toml channel must be a string")

    try:
        parsed_base = parse_python_release_version(base_version)
    except ReleaseVersionError as exc:
        raise ReleaseVersionToolError(
            "release-version.toml base_version must use X.Y.Z format"
        ) from exc
    if parsed_base.is_rc:
        raise ReleaseVersionToolError("release-version.toml base_version must not include an rc suffix")

    if channel not in {"stable", "rc"}:
        raise ReleaseVersionToolError("release-version.toml channel must be 'stable' or 'rc'")

    if channel == "stable":
        if "rc_number" in payload:
            raise ReleaseVersionToolError(
                "release-version.toml rc_number is only allowed when channel = 'rc'"
            )
        return ReleaseVersionConfig(base_version=base_version, channel=channel)

    if "rc_number" not in payload:
        raise ReleaseVersionToolError(
            "release-version.toml rc_number is required when channel = 'rc'"
        )
    if not isinstance(rc_number, int) or isinstance(rc_number, bool) or rc_number <= 0:
        raise ReleaseVersionToolError("release-version.toml rc_number must be a positive integer")
    return ReleaseVersionConfig(base_version=base_version, channel=channel, rc_number=rc_number)


def load_release_version_config(
    repo_root: Path,
    *,
    relative_path: Path = RELEASE_VERSION_PATH,
) -> ReleaseVersionConfig:
    try:
        payload = tomllib.loads(_read_text(repo_root, relative_path))
    except tomllib.TOMLDecodeError as exc:
        raise ReleaseVersionToolError(f"{relative_path} is not valid TOML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseVersionToolError(f"{relative_path} must contain a TOML table")
    return parse_release_version_config(payload)


def render_release_version_config(config: ReleaseVersionConfig) -> str:
    lines = [
        "# Single source of truth for release-critical version metadata.",
        "# Python version: X.Y.Z / X.Y.ZrcN",
        "# npm version: X.Y.Z / X.Y.Z-rc.N",
        "# git tag: vX.Y.Z / vX.Y.Z-rc.N",
        "# This file only drives release-critical files. README/docs install examples",
        "# are intentionally updated separately when user-facing guidance changes.",
        "",
        f'base_version = "{config.base_version}"',
        f'channel = "{config.channel}"',
    ]
    if config.channel == "rc":
        lines.append(f"rc_number = {config.rc_number}")
    return "\n".join(lines) + "\n"


def write_release_version_config(
    repo_root: Path,
    config: ReleaseVersionConfig,
    *,
    relative_path: Path = RELEASE_VERSION_PATH,
) -> None:
    _write_text(repo_root, relative_path, render_release_version_config(config))


def capture_managed_version_files(repo_root: Path) -> dict[Path, str | None]:
    snapshots: dict[Path, str | None] = {}
    for relative_path in MANAGED_VERSION_PATHS:
        path = repo_root / relative_path
        snapshots[relative_path] = (
            path.read_text(encoding="utf-8") if path.exists() else None
        )
    return snapshots


def restore_managed_version_files(
    repo_root: Path,
    snapshots: dict[Path, str | None],
) -> None:
    for relative_path, content in snapshots.items():
        path = repo_root / relative_path
        if content is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def collect_repository_version_state(repo_root: Path) -> RepositoryVersionState:
    root_package = load_json_file(repo_root, ROOT_PACKAGE_JSON_PATH)
    agent_package = load_json_file(repo_root, AGENT_PACKAGE_JSON_PATH)
    package_lock = load_json_file(repo_root, PACKAGE_LOCK_PATH)
    version_text = _read_text(repo_root, VERSION_FILE_PATH)

    dependencies = root_package.get("dependencies")
    if not isinstance(dependencies, dict):
        raise ReleaseVersionToolError("package.json dependencies must be a JSON object")
    root_dependency = dependencies.get(AGENT_PACKAGE_NAME)
    if not isinstance(root_dependency, str):
        raise ReleaseVersionToolError(f"package.json must depend on {AGENT_PACKAGE_NAME}")

    lock_packages = package_lock.get("packages")
    lock_root_version: str | None = None
    lock_root_dependency: str | None = None
    lock_agent_version: str | None = None
    if isinstance(lock_packages, dict):
        root_entry = lock_packages.get("")
        if isinstance(root_entry, dict):
            root_entry_version = root_entry.get("version")
            if isinstance(root_entry_version, str):
                lock_root_version = root_entry_version
            root_entry_dependencies = root_entry.get("dependencies")
            if isinstance(root_entry_dependencies, dict):
                dependency = root_entry_dependencies.get(AGENT_PACKAGE_NAME)
                if isinstance(dependency, str):
                    lock_root_dependency = dependency

        agent_entry = lock_packages.get(AGENT_PACKAGE_JSON_PATH.parent.as_posix())
        if isinstance(agent_entry, dict):
            agent_entry_version = agent_entry.get("version")
            if isinstance(agent_entry_version, str):
                lock_agent_version = agent_entry_version

    return RepositoryVersionState(
        python_version=parse_version_assignment(version_text),
        root_npm_version=str(root_package.get("version", "")),
        agent_npm_version=str(agent_package.get("version", "")),
        root_agent_dependency=root_dependency,
        lock_root_version=lock_root_version,
        lock_root_agent_dependency=lock_root_dependency,
        lock_agent_version=lock_agent_version,
    )


def sync_version_files(repo_root: Path, release: ReleaseVersion) -> None:
    # Only release-critical machine-readable files are synced here. README and
    # docs examples stay manual because they are user-facing guidance, not the
    # canonical release metadata contract.
    version_text = _read_text(repo_root, VERSION_FILE_PATH)
    _write_text(repo_root, VERSION_FILE_PATH, replace_version_assignment(version_text, release.python_version))

    root_package = load_json_file(repo_root, ROOT_PACKAGE_JSON_PATH)
    root_dependencies = root_package.get("dependencies")
    if not isinstance(root_dependencies, dict):
        raise ReleaseVersionToolError("package.json dependencies must be a JSON object")
    root_package["version"] = release.npm_version
    root_dependencies[AGENT_PACKAGE_NAME] = release.agent_package_spec
    write_json_file(repo_root, ROOT_PACKAGE_JSON_PATH, root_package)

    agent_package = load_json_file(repo_root, AGENT_PACKAGE_JSON_PATH)
    agent_package["version"] = release.npm_version
    write_json_file(repo_root, AGENT_PACKAGE_JSON_PATH, agent_package)


def write_release_version_state(repo_root: Path, config: ReleaseVersionConfig) -> None:
    write_release_version_config(repo_root, config)
    sync_version_files(repo_root, config.release)


def run_lockfile_sync(repo_root: Path) -> None:
    # package-lock.json is npm-owned metadata. Regenerate it instead of editing
    # strings directly so workspace dependency bookkeeping stays correct.
    result = subprocess.run(
        ["npm", "install", "--package-lock-only", "--ignore-scripts"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if detail:
            raise ReleaseVersionToolError(f"Failed to regenerate package-lock.json: {detail}")
        raise ReleaseVersionToolError("Failed to regenerate package-lock.json")


def run_release_preflight(
    repo_root: Path,
    *,
    tag: str,
    rc_tag: str | None = None,
) -> None:
    command = ["make", "release-preflight", f"RELEASE_TAG={tag}"]
    if rc_tag is not None:
        command.append(f"RC_TAG={rc_tag}")
    # Stream release-preflight output directly so long-running npm/test steps
    # stay visible to the operator during CHECK=1 flows.
    result = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseVersionToolError(f"Release preflight failed for {tag}")


def sync_release_version(
    repo_root: Path,
    config: ReleaseVersionConfig,
    *,
    check: bool = False,
    rc_tag: str | None = None,
) -> dict[str, str]:
    # Python and npm encode RC releases differently, so keep all formatting in
    # the shared release_version helpers instead of hand-formatting per file.
    snapshots = capture_managed_version_files(repo_root)
    try:
        write_release_version_state(repo_root, config)
        run_lockfile_sync(repo_root)
        if check:
            run_release_preflight(
                repo_root,
                tag=config.release.tag,
                rc_tag=None if config.release.is_rc else rc_tag,
            )
    except BaseException as exc:
        try:
            restore_managed_version_files(repo_root, snapshots)
        except Exception as restore_exc:
            raise ReleaseVersionToolError(f"{exc}; rollback failed: {restore_exc}") from exc
        if isinstance(exc, ReleaseVersionToolError):
            raise
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise ReleaseVersionToolError(str(exc)) from exc
    return release_summary(config)


def release_summary(config: ReleaseVersionConfig) -> dict[str, str]:
    release = config.release
    return {
        "base_version": release.base_version,
        "channel": release.kind,
        "python_version": release.python_version,
        "npm_version": release.npm_version,
        "tag": release.tag,
        "agent_package_spec": release.agent_package_spec,
    }


def check_release_sync(repo_root: Path, *, tag: str) -> dict[str, str]:
    config = load_release_version_config(repo_root)
    expected = config.release
    try:
        parsed_tag = parse_release_tag(tag)
    except ReleaseVersionError as exc:
        raise ReleaseVersionToolError(str(exc)) from exc

    errors: list[str] = []
    if parsed_tag != expected:
        errors.append(
            f"{RELEASE_VERSION_PATH} expects tag {expected.tag}, found {tag}"
        )

    state = collect_repository_version_state(repo_root)

    try:
        python_release = parse_python_release_version(state.python_version)
    except ReleaseVersionError as exc:
        raise ReleaseVersionToolError(
            f"{VERSION_FILE_PATH} does not contain a supported release version"
        ) from exc

    try:
        root_npm_release = parse_npm_release_version(state.root_npm_version)
    except ReleaseVersionError as exc:
        raise ReleaseVersionToolError(
            f"{ROOT_PACKAGE_JSON_PATH} version does not use a supported npm release format"
        ) from exc

    try:
        agent_npm_release = parse_npm_release_version(state.agent_npm_version)
    except ReleaseVersionError as exc:
        raise ReleaseVersionToolError(
            f"{AGENT_PACKAGE_JSON_PATH} version does not use a supported npm release format"
        ) from exc

    if python_release != expected:
        errors.append(
            f"{VERSION_FILE_PATH} must be {expected.python_version}, found {state.python_version}"
        )
    if root_npm_release != expected:
        errors.append(
            f"{ROOT_PACKAGE_JSON_PATH} version must be {expected.npm_version}, found {state.root_npm_version}"
        )
    if agent_npm_release != expected:
        errors.append(
            f"{AGENT_PACKAGE_JSON_PATH} version must be {expected.npm_version}, found {state.agent_npm_version}"
        )
    if state.root_agent_dependency != expected.agent_package_spec:
        errors.append(
            f"{ROOT_PACKAGE_JSON_PATH} dependency {AGENT_PACKAGE_NAME} must be {expected.agent_package_spec}, found {state.root_agent_dependency}"
        )
    if state.lock_root_version != expected.npm_version:
        errors.append(
            f"{PACKAGE_LOCK_PATH} root version must be {expected.npm_version}, found {state.lock_root_version or '<missing>'}"
        )
    if state.lock_root_agent_dependency != expected.agent_package_spec:
        errors.append(
            f"{PACKAGE_LOCK_PATH} root dependency {AGENT_PACKAGE_NAME} must be {expected.agent_package_spec}, found {state.lock_root_agent_dependency or '<missing>'}"
        )
    if state.lock_agent_version != expected.npm_version:
        errors.append(
            f"{PACKAGE_LOCK_PATH} workspace version must be {expected.npm_version}, found {state.lock_agent_version or '<missing>'}"
        )

    if errors:
        raise ReleaseVersionToolError("; ".join(errors))
    return release_summary(config)


def set_rc_release(
    repo_root: Path,
    *,
    base_version: str,
    rc_number: int,
    check: bool = False,
) -> dict[str, str]:
    config = parse_release_version_config(
        {"base_version": base_version, "channel": "rc", "rc_number": rc_number}
    )
    return sync_release_version(repo_root, config, check=check)


def set_stable_release(
    repo_root: Path,
    *,
    base_version: str,
    check: bool = False,
    rc_tag: str | None = None,
) -> dict[str, str]:
    config = parse_release_version_config({"base_version": base_version, "channel": "stable"})
    return sync_release_version(repo_root, config, check=check, rc_tag=rc_tag)


def _print_summary(payload: dict[str, str]) -> None:
    print(
        f"{payload['tag']} -> python {payload['python_version']}, "
        f"npm {payload['npm_version']}, agent {payload['agent_package_spec']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync and validate release version metadata")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("show")
    subparsers.add_parser("sync")

    rc_parser = subparsers.add_parser("set-rc")
    rc_parser.add_argument("--base", required=True)
    rc_parser.add_argument("--rc", required=True, type=int)
    rc_parser.add_argument("--check", action="store_true")

    stable_parser = subparsers.add_parser("set-stable")
    stable_parser.add_argument("--base", required=True)
    stable_parser.add_argument("--check", action="store_true")
    stable_parser.add_argument("--rc-tag")

    check_parser = subparsers.add_parser("check-sync")
    check_parser.add_argument("--tag", required=True)

    args = parser.parse_args(argv)
    repo_root = Path.cwd()

    try:
        if args.command == "show":
            _print_summary(release_summary(load_release_version_config(repo_root)))
            return 0

        if args.command == "sync":
            _print_summary(sync_release_version(repo_root, load_release_version_config(repo_root)))
            return 0

        if args.command == "set-rc":
            _print_summary(
                set_rc_release(
                    repo_root,
                    base_version=args.base,
                    rc_number=args.rc,
                    check=args.check,
                )
            )
            return 0

        if args.command == "set-stable":
            _print_summary(
                set_stable_release(
                    repo_root,
                    base_version=args.base,
                    check=args.check,
                    rc_tag=args.rc_tag,
                )
            )
            return 0

        if args.command == "check-sync":
            _print_summary(check_release_sync(repo_root, tag=args.tag))
            return 0
    except ReleaseVersionToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
