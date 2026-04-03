#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from frida_analykit.release_version import (
    ReleaseVersionError,
    parse_npm_release_version,
    parse_python_release_version,
    parse_release_tag,
)


PYPROJECT_PATH = Path("pyproject.toml")
COMPAT_PROFILES_PATH = Path("src/frida_analykit/resources/compat_profiles.json")
ROOT_PACKAGE_JSON_PATH = Path("package.json")
AGENT_PACKAGE_JSON_PATH = Path("packages/frida-analykit-agent/package.json")
PACKAGE_LOCK_PATH = Path("package-lock.json")
RELEASE_VERSION_PATH = Path("release-version.toml")
DEVICE_TEST_RELEASE_APK_PREFIX = "frida-analykit-device-test-app"
PROMOTION_ALLOWED_DIFFS = {
    PACKAGE_LOCK_PATH.as_posix(),
    ROOT_PACKAGE_JSON_PATH.as_posix(),
    AGENT_PACKAGE_JSON_PATH.as_posix(),
    RELEASE_VERSION_PATH.as_posix(),
}
ROOT_README_PATHS = (Path("README.md"), Path("README_EN.md"))
PACKAGE_README_LINKS = {
    Path("packages/frida-analykit-agent/README.md"): (
        "https://github.com/ZSA233/frida-analykit/blob/stable/packages/frida-analykit-agent/README_EN.md"
    ),
    Path("packages/frida-analykit-agent/README_EN.md"): (
        "https://github.com/ZSA233/frida-analykit/blob/stable/packages/frida-analykit-agent/README.md"
    ),
}
STABLE_INSTALL_SPEC = "git+https://github.com/ZSA233/frida-analykit@stable"
PINNED_RELEASE_INSTALL_RE = re.compile(
    r"git\+https://github\.com/ZSA233/frida-analykit@v\d+\.\d+\.\d+(?:-rc\.\d+)?"
)
PACKAGE_REPOSITORY_URL = "https://github.com/ZSA233/frida-analykit"
PACKAGE_MAIN_BLOB_PREFIX = "https://github.com/ZSA233/frida-analykit/blob/main/"


class ReleaseConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class SupportRange:
    min_inclusive: Version
    max_exclusive: Version

    def contains(self, version: Version) -> bool:
        return self.min_inclusive <= version < self.max_exclusive

    def __str__(self) -> str:
        return f">={self.min_inclusive}, <{self.max_exclusive}"


@dataclass(frozen=True)
class CompatibilityProfile:
    name: str
    series: str
    tested_version: Version
    min_inclusive: Version
    max_exclusive: Version

    def contains(self, version: Version) -> bool:
        return self.min_inclusive <= version < self.max_exclusive


@dataclass(frozen=True)
class PackageMetadata:
    name: str
    normalized_name: str
    base_version: Version
    version_file: Path
    frida_requirement_raw: str
    frida_requirement: Requirement


def _git_show(repo_root: Path, ref: str, relative_path: Path) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path.as_posix()}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FileNotFoundError(f"{relative_path} is not available at ref {ref}")
    return result.stdout


def read_repo_text(repo_root: Path, relative_path: Path, *, ref: str | None = None) -> str:
    if ref is None:
        return (repo_root / relative_path).read_text(encoding="utf-8")
    return _git_show(repo_root, ref, relative_path)


def load_pyproject(repo_root: Path, *, ref: str | None = None) -> dict[str, Any]:
    return tomllib.loads(read_repo_text(repo_root, PYPROJECT_PATH, ref=ref))


def load_json_file(
    repo_root: Path,
    relative_path: Path,
    *,
    ref: str | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(read_repo_text(repo_root, relative_path, ref=ref))
    except json.JSONDecodeError as exc:
        raise ReleaseConfigError(f"{relative_path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseConfigError(f"{relative_path} must contain a JSON object")
    return payload


def parse_version_file(text: str) -> str:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"\s*$', text, flags=re.MULTILINE)
    if not match:
        raise ReleaseConfigError("Could not locate __version__ assignment")
    return match.group(1)


def _load_frida_dependency(dependencies: list[str]) -> tuple[str, Requirement]:
    matches: list[tuple[str, Requirement]] = []
    for raw_dependency in dependencies:
        try:
            requirement = Requirement(raw_dependency)
        except Exception as exc:
            raise ReleaseConfigError(
                f"Invalid dependency entry in pyproject.toml: {raw_dependency!r}"
            ) from exc
        if requirement.name == "frida":
            matches.append((raw_dependency, requirement))

    if not matches:
        raise ReleaseConfigError("pyproject.toml is missing a frida dependency")
    if len(matches) != 1:
        raise ReleaseConfigError(
            "pyproject.toml must define exactly one direct frida dependency"
        )
    return matches[0]


def load_package_metadata(repo_root: Path, *, ref: str | None = None) -> PackageMetadata:
    pyproject = load_pyproject(repo_root, ref=ref)
    version_file = Path(pyproject["tool"]["hatch"]["version"]["path"])
    raw_version = parse_version_file(read_repo_text(repo_root, version_file, ref=ref))
    dependencies = pyproject["project"].get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ReleaseConfigError("project.dependencies must be a TOML array")

    frida_raw, frida_requirement = _load_frida_dependency(dependencies)
    package_name = pyproject["project"]["name"]
    return PackageMetadata(
        name=package_name,
        normalized_name=canonicalize_name(package_name),
        base_version=Version(raw_version),
        version_file=version_file,
        frida_requirement_raw=frida_raw,
        frida_requirement=frida_requirement,
    )


def load_compat_profiles(
    repo_root: Path,
    *,
    ref: str | None = None,
) -> list[CompatibilityProfile]:
    payload = load_json_file(repo_root, COMPAT_PROFILES_PATH, ref=ref)
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ReleaseConfigError("compat_profiles.json must define a non-empty profiles array")

    profiles: list[CompatibilityProfile] = []
    for item in raw_profiles:
        if not isinstance(item, dict):
            raise ReleaseConfigError("compat_profiles.json profiles entries must be objects")
        try:
            profiles.append(
                CompatibilityProfile(
                    name=str(item["name"]),
                    series=str(item["series"]),
                    tested_version=Version(str(item["tested_version"])),
                    min_inclusive=Version(str(item["min_inclusive"])),
                    max_exclusive=Version(str(item["max_exclusive"])),
                )
            )
        except KeyError as exc:
            raise ReleaseConfigError(
                f"compat_profiles.json is missing required field {exc.args[0]!r}"
            ) from exc
    return profiles


def distribution_filename(name: str) -> str:
    return re.sub(r"[^\w\d.]+", "_", name, flags=re.UNICODE)


def expected_sdist_name(package_name: str, package_version: str) -> str:
    return f"{distribution_filename(package_name)}-{package_version}.tar.gz"


def expected_npm_tgz_name(package_name: str, package_version: str) -> str:
    return f"{package_name.lstrip('@').replace('/', '-')}-{package_version}.tgz"


def expected_device_test_apk_name(tag: str) -> str:
    try:
        release = parse_release_tag(tag)
    except ReleaseVersionError as exc:
        raise ReleaseConfigError(f"Unsupported release tag for device test APK: {tag}") from exc
    return f"{DEVICE_TEST_RELEASE_APK_PREFIX}-{release.tag}.apk"


def _build_device_test_app(repo_root: Path) -> Path:
    from frida_analykit.device.test_app import build_device_test_app

    return build_device_test_app(repo_root)


def stage_device_test_apk(
    repo_root: Path,
    *,
    tag: str,
    dist_dir: Path,
) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in dist_dir.glob(f"{DEVICE_TEST_RELEASE_APK_PREFIX}-*.apk"):
        stale_path.unlink()

    try:
        source_apk = _build_device_test_app(repo_root)
    except RuntimeError as exc:
        raise ReleaseConfigError(f"Failed to build the device test APK: {exc}") from exc
    target_apk = dist_dir / expected_device_test_apk_name(tag)
    shutil.copy2(source_apk, target_apk)
    return target_apk


def _parse_support_range(requirement: Requirement) -> SupportRange:
    errors: list[str] = []

    if requirement.extras:
        errors.append("frida dependency must not use extras")
    if requirement.marker is not None:
        errors.append("frida dependency must not use environment markers")
    if requirement.url is not None:
        errors.append("frida dependency must not use direct URLs")

    min_inclusive: Version | None = None
    max_exclusive: Version | None = None
    unsupported_specifiers: list[str] = []

    for specifier in requirement.specifier:
        version = Version(specifier.version)
        if specifier.operator == ">=" and min_inclusive is None:
            min_inclusive = version
            continue
        if specifier.operator == "<" and max_exclusive is None:
            max_exclusive = version
            continue
        unsupported_specifiers.append(f"{specifier.operator}{specifier.version}")

    if min_inclusive is None or max_exclusive is None:
        errors.append("frida dependency must define exactly one >= lower bound and one < upper bound")
    if unsupported_specifiers:
        errors.append(
            "frida dependency must only use a >= lower bound and a < upper bound; found "
            + ", ".join(sorted(unsupported_specifiers))
        )
    if min_inclusive is not None and max_exclusive is not None and min_inclusive >= max_exclusive:
        errors.append("frida dependency lower bound must be lower than its upper bound")

    if errors:
        raise ReleaseConfigError("; ".join(errors))
    return SupportRange(min_inclusive=min_inclusive, max_exclusive=max_exclusive)


def validate_release_contract(
    repo_root: Path,
    *,
    ref: str | None = None,
) -> dict[str, Any]:
    metadata = load_package_metadata(repo_root, ref=ref)
    support_range = _parse_support_range(metadata.frida_requirement)
    profiles = load_compat_profiles(repo_root, ref=ref)

    seen_names: set[str] = set()
    for profile in profiles:
        if profile.name in seen_names:
            raise ReleaseConfigError(f"compatibility profile {profile.name!r} is duplicated")
        seen_names.add(profile.name)
        if profile.min_inclusive >= profile.max_exclusive:
            raise ReleaseConfigError(
                f"profile {profile.name} must have min_inclusive < max_exclusive"
            )
        if not profile.contains(profile.tested_version):
            raise ReleaseConfigError(
                f"profile {profile.name} tested_version must be inside its declared range"
            )
        if profile.min_inclusive < support_range.min_inclusive:
            raise ReleaseConfigError(
                f"profile {profile.name} starts before the declared frida support range"
            )
        if profile.max_exclusive > support_range.max_exclusive:
            raise ReleaseConfigError(
                f"profile {profile.name} ends after the declared frida support range"
            )

    return {
        "name": metadata.name,
        "base_version": str(metadata.base_version),
        "support_range": str(support_range),
        "min_inclusive": str(support_range.min_inclusive),
        "max_exclusive": str(support_range.max_exclusive),
        "tested_profiles": [profile.name for profile in profiles],
        "dependency_contract": "single direct frida dependency with >= lower bound and < upper bound",
    }


def validate_stable_entrypoints(
    repo_root: Path,
    *,
    ref: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []

    for relative_path in ROOT_README_PATHS:
        text = read_repo_text(repo_root, relative_path, ref=ref)
        if STABLE_INSTALL_SPEC not in text:
            errors.append(
                f"{relative_path} must use {STABLE_INSTALL_SPEC} as the stable install entry"
            )
        if PINNED_RELEASE_INSTALL_RE.search(text):
            errors.append(
                f"{relative_path} must not pin user-facing installs to a concrete release tag"
            )

    for relative_path, expected_link in PACKAGE_README_LINKS.items():
        text = read_repo_text(repo_root, relative_path, ref=ref)
        if PINNED_RELEASE_INSTALL_RE.search(text):
            errors.append(
                f"{relative_path} must not pin user-facing installs to a concrete release tag"
            )
        if PACKAGE_MAIN_BLOB_PREFIX in text:
            errors.append(f"{relative_path} must not link to blob/main")
        if expected_link not in text:
            errors.append(f"{relative_path} must link to {expected_link}")

    agent_package = load_json_file(repo_root, AGENT_PACKAGE_JSON_PATH, ref=ref)
    homepage = agent_package.get("homepage")
    if homepage != PACKAGE_REPOSITORY_URL:
        errors.append(
            "packages/frida-analykit-agent/package.json homepage must be "
            f"{PACKAGE_REPOSITORY_URL}"
        )

    if errors:
        raise ReleaseConfigError("; ".join(errors))

    return {
        "stable_install_spec": STABLE_INSTALL_SPEC,
        "package_homepage": PACKAGE_REPOSITORY_URL,
        "package_readmes": [path.as_posix() for path in PACKAGE_README_LINKS],
    }


def _run_git(repo_root: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
        raise ReleaseConfigError(message)
    return result.stdout.strip()


def _branch_ref(branch: str) -> str:
    return f"refs/heads/{branch}"


def _resolve_remote_branch_sha(
    repo_root: Path,
    *,
    remote: str,
    branch: str,
) -> str | None:
    branch_ref = _branch_ref(branch)
    output = _run_git(repo_root, ["ls-remote", "--heads", "--refs", remote, branch_ref])
    if not output:
        return None

    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ReleaseConfigError(
            f"Expected at most one remote ref for {remote}/{branch}, found {len(lines)}"
        )

    parts = lines[0].split()
    if len(parts) != 2:
        raise ReleaseConfigError(
            f"Unexpected ls-remote output for {remote}/{branch}: {lines[0]!r}"
        )
    sha, ref = parts
    if ref != branch_ref:
        raise ReleaseConfigError(
            f"Unexpected remote ref for {remote}/{branch}: expected {branch_ref}, found {ref}"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ReleaseConfigError(
            f"Unexpected remote SHA for {remote}/{branch}: {sha}"
        )
    return sha


def _push_branch_ref(
    repo_root: Path,
    *,
    remote: str,
    branch: str,
    target_commit: str,
    expected_remote_sha: str | None,
) -> None:
    destination = f"{target_commit}:{_branch_ref(branch)}"
    if expected_remote_sha is None:
        _run_git(repo_root, ["push", remote, destination])
        return

    lease = f"--force-with-lease={_branch_ref(branch)}:{expected_remote_sha}"
    _run_git(repo_root, ["push", lease, remote, destination])


def sync_stable_ref(
    repo_root: Path,
    *,
    tag: str,
    branch: str = "stable",
) -> dict[str, Any]:
    try:
        release = parse_release_tag(tag)
    except ReleaseVersionError as exc:
        raise ReleaseConfigError(str(exc)) from exc
    if release.is_rc:
        raise ReleaseConfigError("Stable ref sync only applies to stable tags")

    target_commit = _run_git(repo_root, ["rev-list", "-n", "1", tag])
    if not target_commit:
        raise ReleaseConfigError(f"Could not resolve commit for tag {tag}")

    remote_sha = _resolve_remote_branch_sha(repo_root, remote="origin", branch=branch)
    _push_branch_ref(
        repo_root,
        remote="origin",
        branch=branch,
        target_commit=target_commit,
        expected_remote_sha=remote_sha,
    )

    return {
        "tag_name": tag,
        "branch": branch,
        "target_commit": target_commit,
        "created": remote_sha is None,
    }


def _load_root_agent_dependency(repo_root: Path, *, ref: str | None = None) -> str:
    package_json = load_json_file(repo_root, ROOT_PACKAGE_JSON_PATH, ref=ref)
    dependencies = package_json.get("dependencies")
    if not isinstance(dependencies, dict):
        raise ReleaseConfigError("package.json dependencies must be a JSON object")
    dependency = dependencies.get("@zsa233/frida-analykit-agent")
    if not isinstance(dependency, str):
        raise ReleaseConfigError("package.json must depend on @zsa233/frida-analykit-agent")
    return dependency


def validate_release_version(
    repo_root: Path,
    *,
    tag: str,
    ref: str | None = None,
) -> dict[str, Any]:
    try:
        expected = parse_release_tag(tag)
    except ReleaseVersionError as exc:
        raise ReleaseConfigError(str(exc)) from exc

    metadata = load_package_metadata(repo_root, ref=ref)
    root_package = load_json_file(repo_root, ROOT_PACKAGE_JSON_PATH, ref=ref)
    agent_package = load_json_file(repo_root, AGENT_PACKAGE_JSON_PATH, ref=ref)
    python_release = parse_python_release_version(str(metadata.base_version))

    try:
        root_release = parse_npm_release_version(str(root_package["version"]))
    except (KeyError, ReleaseVersionError) as exc:
        raise ReleaseConfigError("package.json version does not match the expected release format") from exc

    try:
        agent_release = parse_npm_release_version(str(agent_package["version"]))
    except (KeyError, ReleaseVersionError) as exc:
        raise ReleaseConfigError(
            "packages/frida-analykit-agent/package.json version does not match the expected release format"
        ) from exc

    root_dependency = _load_root_agent_dependency(repo_root, ref=ref)
    errors: list[str] = []
    if python_release != expected:
        errors.append(
            f"Python version must be {expected.python_version} for tag {tag}, found {python_release.python_version}"
        )
    if root_release != expected:
        errors.append(
            f"package.json version must be {expected.npm_version} for tag {tag}, found {root_release.npm_version}"
        )
    if agent_release != expected:
        errors.append(
            "packages/frida-analykit-agent/package.json version must be "
            f"{expected.npm_version} for tag {tag}, found {agent_release.npm_version}"
        )
    if root_dependency != expected.agent_package_spec:
        errors.append(
            "package.json dependency on @zsa233/frida-analykit-agent must be "
            f"{expected.agent_package_spec}, found {root_dependency}"
        )

    if errors:
        raise ReleaseConfigError("; ".join(errors))

    return {
        "tag_name": expected.tag,
        "kind": expected.kind,
        "base_version": expected.base_version,
        "python_version": expected.python_version,
        "npm_version": expected.npm_version,
        "agent_package_spec": expected.agent_package_spec,
    }


def _find_reachable_rc_tag(
    repo_root: Path,
    *,
    stable_tag: str,
    ref: str | None = None,
) -> str:
    try:
        stable_release = parse_release_tag(stable_tag)
    except ReleaseVersionError as exc:
        raise ReleaseConfigError(str(exc)) from exc
    if stable_release.is_rc:
        raise ReleaseConfigError("Promotion validation only applies to stable tags")

    pattern = f"v{stable_release.base_version}-rc.*"
    output = _run_git(repo_root, ["tag", "--list", pattern])
    candidates = [line for line in output.splitlines() if line.strip()]
    if not candidates:
        raise ReleaseConfigError(f"No RC tag found for stable release {stable_tag}")

    reachable: list[tuple[int, str]] = []
    target_ref = ref or "HEAD"
    for candidate in candidates:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", candidate, target_ref],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue
        parsed = parse_release_tag(candidate)
        if parsed.rc_number is None:
            continue
        reachable.append((parsed.rc_number, candidate))

    if not reachable:
        raise ReleaseConfigError(
            f"No RC tag for {stable_tag} is an ancestor of {target_ref}"
        )
    reachable.sort()
    return reachable[-1][1]


def validate_promotion(
    repo_root: Path,
    *,
    tag: str,
    ref: str | None = None,
    rc_tag: str | None = None,
) -> dict[str, Any]:
    try:
        stable_release = parse_release_tag(tag)
    except ReleaseVersionError as exc:
        raise ReleaseConfigError(str(exc)) from exc
    if stable_release.is_rc:
        raise ReleaseConfigError("Promotion validation only applies to stable tags")

    resolved_rc_tag = rc_tag or _find_reachable_rc_tag(repo_root, stable_tag=tag, ref=ref)
    try:
        rc_release = parse_release_tag(resolved_rc_tag)
    except ReleaseVersionError as exc:
        raise ReleaseConfigError(str(exc)) from exc
    if not rc_release.is_rc:
        raise ReleaseConfigError(f"{resolved_rc_tag} is not an RC tag")
    if rc_release.base_version != stable_release.base_version:
        raise ReleaseConfigError(
            f"{resolved_rc_tag} does not match the stable base version {stable_release.base_version}"
        )

    metadata = load_package_metadata(repo_root, ref=ref)
    allowed_diffs = set(PROMOTION_ALLOWED_DIFFS)
    allowed_diffs.add(metadata.version_file.as_posix())
    changed_paths_set: set[str] = set()

    diff_output = _run_git(
        repo_root,
        ["diff", "--name-only", "--relative", f"{resolved_rc_tag}..{ref or 'HEAD'}"],
    )
    changed_paths_set.update(line for line in diff_output.splitlines() if line.strip())

    if ref is None or ref == "HEAD":
        working_tree_diff = _run_git(repo_root, ["diff", "--name-only", "--relative"])
        changed_paths_set.update(line for line in working_tree_diff.splitlines() if line.strip())

        staged_diff = _run_git(repo_root, ["diff", "--cached", "--name-only", "--relative"])
        changed_paths_set.update(line for line in staged_diff.splitlines() if line.strip())

    changed_paths = sorted(changed_paths_set)
    disallowed = [path for path in changed_paths if path not in allowed_diffs]
    if disallowed:
        raise ReleaseConfigError(
            "Stable promotion only allows version metadata changes after RC: "
            + ", ".join(sorted(disallowed))
        )

    return {
        "tag_name": tag,
        "rc_tag": resolved_rc_tag,
        "changed_paths": changed_paths,
    }


def _venv_python(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def _run_checked(
    command: list[str],
    *,
    cwd: Path | None = None,
    error_message: str,
) -> subprocess.CompletedProcess[str]:
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
            raise ReleaseConfigError(f"{error_message}: {detail}")
        raise ReleaseConfigError(error_message)
    return result


def _pick_single_file(paths: list[Path], *, description: str) -> Path:
    if len(paths) != 1:
        raise ReleaseConfigError(f"Expected exactly one {description}, found {len(paths)}")
    return paths[0]


def _pick_release_wheel(dist_dir: Path, metadata: PackageMetadata) -> Path:
    candidates: list[Path] = []
    for path in sorted(dist_dir.glob("*.whl")):
        try:
            distribution, version, _, _ = parse_wheel_filename(path.name)
        except Exception:
            continue
        if distribution != metadata.normalized_name:
            continue
        if str(version) != str(metadata.base_version):
            continue
        candidates.append(path)
    return _pick_single_file(candidates, description="release wheel in dist/")


def _pick_release_device_test_apk(dist_dir: Path, *, tag: str) -> Path:
    expected_name = expected_device_test_apk_name(tag)
    candidates = sorted(dist_dir.glob(f"{DEVICE_TEST_RELEASE_APK_PREFIX}-*.apk"))
    if not candidates:
        raise ReleaseConfigError(f"Missing device test APK: {dist_dir / expected_name}")
    if len(candidates) != 1:
        raise ReleaseConfigError(
            f"Expected exactly one release device test APK in dist/, found {len(candidates)}"
        )
    candidate = candidates[0]
    if candidate.name != expected_name:
        raise ReleaseConfigError(
            f"Expected device test APK named {expected_name}, found {candidate.name}"
        )
    return candidate


def install_check(
    repo_root: Path,
    *,
    tag: str,
    dist_dir: Path,
    ref: str | None = None,
) -> dict[str, Any]:
    release_info = validate_release_version(repo_root, tag=tag, ref=ref)
    contract = validate_release_contract(repo_root, ref=ref)
    metadata = load_package_metadata(repo_root, ref=ref)
    agent_package = load_json_file(repo_root, AGENT_PACKAGE_JSON_PATH, ref=ref)

    sdist_path = dist_dir / expected_sdist_name(metadata.name, str(metadata.base_version))
    if not sdist_path.exists():
        raise ReleaseConfigError(f"Missing source distribution: {sdist_path}")

    wheel_path = _pick_release_wheel(dist_dir, metadata)
    tgz_path = repo_root / expected_npm_tgz_name(
        str(agent_package["name"]),
        str(agent_package["version"]),
    )
    if not tgz_path.exists():
        raise ReleaseConfigError(f"Missing npm package tarball: {tgz_path}")

    device_test_apk = _pick_release_device_test_apk(dist_dir, tag=tag)

    min_supported_frida = contract["min_inclusive"]

    with tempfile.TemporaryDirectory(prefix="frida-analykit-install-check-") as temp_dir:
        temp_root = Path(temp_dir)
        sdist_env = temp_root / "sdist-env"
        wheel_env = temp_root / "wheel-env"
        sdist_python = _venv_python(sdist_env)
        wheel_python = _venv_python(wheel_env)

        _run_checked(
            ["uv", "venv", str(sdist_env), "--python", sys.executable],
            cwd=repo_root,
            error_message="Failed to create the sdist install-check environment",
        )
        _run_checked(
            ["uv", "venv", str(wheel_env), "--python", sys.executable],
            cwd=repo_root,
            error_message="Failed to create the wheel install-check environment",
        )
        _run_checked(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(sdist_python),
                f"frida=={min_supported_frida}",
            ],
            cwd=repo_root,
            error_message="Failed to install the minimum supported frida in the sdist environment",
        )
        _run_checked(
            ["uv", "pip", "install", "--python", str(sdist_python), str(sdist_path)],
            cwd=repo_root,
            error_message="Failed to install the source distribution in a clean environment",
        )
        _run_checked(
            [str(sdist_python), "-m", "frida_analykit", "doctor"],
            cwd=repo_root,
            error_message="Installed source distribution failed the doctor check",
        )

        _run_checked(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(wheel_python),
                f"frida=={min_supported_frida}",
            ],
            cwd=repo_root,
            error_message="Failed to install the minimum supported frida in the wheel environment",
        )
        _run_checked(
            ["uv", "pip", "install", "--python", str(wheel_python), str(wheel_path)],
            cwd=repo_root,
            error_message="Failed to install the release wheel in a clean environment",
        )
        _run_checked(
            [str(wheel_python), "-m", "frida_analykit", "doctor"],
            cwd=repo_root,
            error_message="Installed release wheel failed the doctor check",
        )

        workspace = temp_root / "agent-workspace"
        _run_checked(
            [
                str(wheel_python),
                "-m",
                "frida_analykit",
                "gen",
                "dev",
                "--work-dir",
                str(workspace),
                "--agent-package-spec",
                f"file:{tgz_path.resolve()}",
            ],
            cwd=repo_root,
            error_message="Failed to scaffold a dev workspace with the local npm tarball",
        )

    return {
        "tag_name": release_info["tag_name"],
        "sdist_name": sdist_path.name,
        "wheel_name": wheel_path.name,
        "npm_tgz": tgz_path.name,
        "device_test_apk": device_test_apk.name,
        "support_range": contract["support_range"],
    }


def _dump_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate release metadata and release artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-config")
    validate_parser.add_argument("--ref")
    validate_parser.add_argument("--json", action="store_true")

    stable_parser = subparsers.add_parser("validate-stable-entrypoints")
    stable_parser.add_argument("--ref")
    stable_parser.add_argument("--json", action="store_true")

    version_parser = subparsers.add_parser("validate-release-version")
    version_parser.add_argument("--tag", required=True)
    version_parser.add_argument("--ref")
    version_parser.add_argument("--json", action="store_true")

    promotion_parser = subparsers.add_parser("validate-promotion")
    promotion_parser.add_argument("--tag", required=True)
    promotion_parser.add_argument("--ref")
    promotion_parser.add_argument("--rc-tag")
    promotion_parser.add_argument("--json", action="store_true")

    install_parser = subparsers.add_parser("install-check")
    install_parser.add_argument("--tag", required=True)
    install_parser.add_argument("--ref")
    install_parser.add_argument("--dist-dir", default="dist")
    install_parser.add_argument("--json", action="store_true")

    stage_apk_parser = subparsers.add_parser("stage-device-test-apk")
    stage_apk_parser.add_argument("--tag", required=True)
    stage_apk_parser.add_argument("--dist-dir", default="dist")
    stage_apk_parser.add_argument("--json", action="store_true")

    sync_stable_parser = subparsers.add_parser("sync-stable-ref")
    sync_stable_parser.add_argument("--tag", required=True)
    sync_stable_parser.add_argument("--branch", default="stable")
    sync_stable_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    repo_root = Path.cwd()

    try:
        if args.command == "validate-config":
            result = validate_release_contract(repo_root, ref=args.ref)
            if args.json:
                _dump_json(result)
            else:
                print(
                    f"{result['name']} {result['base_version']} supports {result['support_range']}"
                )
            return 0

        if args.command == "validate-stable-entrypoints":
            payload = validate_stable_entrypoints(repo_root, ref=args.ref)
            if args.json:
                _dump_json(payload)
            else:
                print(
                    f"stable install entry uses {payload['stable_install_spec']} and package docs use blob/stable"
                )
            return 0

        if args.command == "validate-release-version":
            payload = validate_release_version(repo_root, tag=args.tag, ref=args.ref)
            if args.json:
                _dump_json(payload)
            else:
                print(
                    f"{payload['tag_name']} -> python {payload['python_version']}, "
                    f"npm {payload['npm_version']}"
                )
            return 0

        if args.command == "validate-promotion":
            payload = validate_promotion(
                repo_root,
                tag=args.tag,
                ref=args.ref,
                rc_tag=args.rc_tag,
            )
            if args.json:
                _dump_json(payload)
            else:
                print(
                    f"{payload['tag_name']} can be promoted from {payload['rc_tag']} "
                    f"with {len(payload['changed_paths'])} allowed change(s)"
                )
            return 0

        if args.command == "install-check":
            payload = install_check(
                repo_root,
                tag=args.tag,
                ref=args.ref,
                dist_dir=Path(args.dist_dir),
            )
            if args.json:
                _dump_json(payload)
            else:
                print(
                    "verified "
                    f"{payload['sdist_name']}, {payload['wheel_name']}, "
                    f"{payload['npm_tgz']}, and {payload['device_test_apk']}"
                )
            return 0

        if args.command == "stage-device-test-apk":
            apk_path = stage_device_test_apk(
                repo_root,
                tag=args.tag,
                dist_dir=Path(args.dist_dir),
            )
            payload = {"tag_name": args.tag, "device_test_apk": apk_path.name}
            if args.json:
                _dump_json(payload)
            else:
                print(f"staged {apk_path}")
            return 0

        if args.command == "sync-stable-ref":
            payload = sync_stable_ref(
                repo_root,
                tag=args.tag,
                branch=args.branch,
            )
            if args.json:
                _dump_json(payload)
            else:
                action = "created" if payload["created"] else "updated"
                print(
                    f"{action} {payload['branch']} -> {payload['target_commit']} for {payload['tag_name']}"
                )
            return 0
    except ReleaseConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
