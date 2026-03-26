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
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

from frida_analykit.release_version import (
    ReleaseVersionError,
    parse_npm_release_version,
    parse_python_release_version,
    parse_release_tag,
)


PYPROJECT_PATH = Path("pyproject.toml")
RELEASE_CONFIG_PATH = Path("release/frida-builds.toml")
ROOT_PACKAGE_JSON_PATH = Path("package.json")
AGENT_PACKAGE_JSON_PATH = Path("packages/frida-analykit-agent/package.json")
PACKAGE_LOCK_PATH = Path("package-lock.json")
NETWORK_TIMEOUT_SECONDS = 15
NETWORK_RETRIES = 3
RETRYABLE_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
BUILD_IGNORE_PATTERNS = shutil.ignore_patterns(
    ".git",
    ".venv",
    "dist",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
)
SAFE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
PROMOTION_ALLOWED_DIFFS = {
    PACKAGE_LOCK_PATH.as_posix(),
    ROOT_PACKAGE_JSON_PATH.as_posix(),
    AGENT_PACKAGE_JSON_PATH.as_posix(),
}


class ReleaseConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseBuildConfig:
    min_inclusive: Version
    max_exclusive: Version
    include_prerelease: bool
    exclude: tuple[Version, ...]


@dataclass(frozen=True)
class PackageMetadata:
    name: str
    normalized_name: str
    base_version: Version
    version_file: Path
    frida_dependency_index: int
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


def _load_frida_dependency(
    dependencies: list[str],
) -> tuple[int, str, Requirement]:
    matches: list[tuple[int, str, Requirement]] = []
    for index, raw_dependency in enumerate(dependencies):
        try:
            requirement = Requirement(raw_dependency)
        except Exception as exc:
            raise ReleaseConfigError(
                f"Invalid dependency entry in pyproject.toml: {raw_dependency!r}"
            ) from exc
        if requirement.name == "frida":
            matches.append((index, raw_dependency, requirement))

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

    frida_index, frida_raw, frida_requirement = _load_frida_dependency(dependencies)
    package_name = pyproject["project"]["name"]
    return PackageMetadata(
        name=package_name,
        normalized_name=canonicalize_name(package_name),
        base_version=Version(raw_version),
        version_file=version_file,
        frida_dependency_index=frida_index,
        frida_requirement_raw=frida_raw,
        frida_requirement=frida_requirement,
    )


def load_release_config(repo_root: Path, *, ref: str | None = None) -> ReleaseBuildConfig:
    raw = tomllib.loads(read_repo_text(repo_root, RELEASE_CONFIG_PATH, ref=ref))
    return ReleaseBuildConfig(
        min_inclusive=Version(raw["min_inclusive"]),
        max_exclusive=Version(raw["max_exclusive"]),
        include_prerelease=bool(raw.get("include_prerelease", False)),
        exclude=tuple(Version(item) for item in raw.get("exclude", [])),
    )


def distribution_filename(name: str) -> str:
    return re.sub(r"[^\w\d.]+", "_", name, flags=re.UNICODE)


def build_variant_version(base_version: Version | str, frida_version: Version | str) -> str:
    return str(Version(f"{base_version}+frida{frida_version}"))


def expected_sdist_name(package_name: str, package_version: str) -> str:
    return f"{distribution_filename(package_name)}-{package_version}.tar.gz"


def _validate_frida_requirement_shape(
    requirement: Requirement,
    config: ReleaseBuildConfig,
) -> None:
    errors: list[str] = []

    if requirement.extras:
        errors.append("frida dependency must not use extras")
    if requirement.marker is not None:
        errors.append("frida dependency must not use environment markers")
    if requirement.url is not None:
        errors.append("frida dependency must not use direct URLs")

    expected_bounds = {
        (">=", config.min_inclusive),
        ("<", config.max_exclusive),
    }
    actual_bounds = {
        (specifier.operator, Version(specifier.version))
        for specifier in requirement.specifier
    }
    if actual_bounds != expected_bounds:
        actual_text = ", ".join(
            f"{operator}{version}" for operator, version in sorted(actual_bounds)
        ) or "<none>"
        expected_text = ", ".join(
            f"{operator}{version}" for operator, version in sorted(expected_bounds)
        )
        errors.append(
            "frida dependency must use only the configured bounds "
            f"({expected_text}); found {actual_text}"
        )

    if errors:
        raise ReleaseConfigError("; ".join(errors))


def validate_release_contract(
    repo_root: Path,
    *,
    ref: str | None = None,
) -> dict[str, str]:
    metadata = load_package_metadata(repo_root, ref=ref)
    config = load_release_config(repo_root, ref=ref)
    _validate_frida_requirement_shape(metadata.frida_requirement, config)
    return {
        "name": metadata.name,
        "base_version": str(metadata.base_version),
        "min_inclusive": str(config.min_inclusive),
        "max_exclusive": str(config.max_exclusive),
        "dependency_contract": "single direct frida dependency without extras or markers",
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


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    return body


def _fetch_json(
    url: str,
    *,
    headers: dict[str, str],
    context: str,
    not_found_message: str | None = None,
) -> Any:
    last_error: ReleaseConfigError | None = None

    for attempt in range(1, NETWORK_RETRIES + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
                try:
                    return json.load(response)
                except json.JSONDecodeError as exc:
                    raise ReleaseConfigError(
                        f"{context} returned invalid JSON: {exc}"
                    ) from exc
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and not_found_message is not None:
                raise ReleaseConfigError(not_found_message) from exc

            detail = _http_error_detail(exc)
            message = f"{context} failed with HTTP {exc.code}"
            if detail:
                message = f"{message}: {detail}"
            last_error = ReleaseConfigError(message)
            if exc.code in RETRYABLE_HTTP_STATUS and attempt < NETWORK_RETRIES:
                time.sleep(attempt)
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            message = f"{context} failed: {exc.reason}"
            last_error = ReleaseConfigError(message)
            if attempt < NETWORK_RETRIES:
                time.sleep(attempt)
                continue
            raise last_error from exc

    if last_error is None:
        raise ReleaseConfigError(f"{context} failed")
    raise last_error


def fetch_frida_versions() -> list[Version]:
    url = os.environ.get("FRIDA_PYPI_JSON_URL", "https://pypi.org/pypi/frida/json")
    payload = _fetch_json(
        url,
        headers={"User-Agent": "frida-analykit-release-assets"},
        context="PyPI frida release discovery",
    )
    releases = payload.get("releases", {})
    versions: list[Version] = []
    for raw_version, files in releases.items():
        if not files or all(file_info.get("yanked", False) for file_info in files):
            continue
        try:
            versions.append(Version(raw_version))
        except InvalidVersion:
            continue
    return sorted(set(versions))


def filter_supported_frida_versions(
    available_versions: list[Version],
    config: ReleaseBuildConfig,
) -> list[Version]:
    supported: list[Version] = []
    excluded = set(config.exclude)
    for version in sorted(set(available_versions)):
        if version in excluded:
            continue
        if version < config.min_inclusive or version >= config.max_exclusive:
            continue
        if not config.include_prerelease and version.is_prerelease:
            continue
        supported.append(version)
    return supported


def _parse_existing_variant_version(
    asset_name: str,
    metadata: PackageMetadata,
) -> Version | None:
    if not asset_name.endswith(".whl"):
        return None

    try:
        distribution, version, _, _ = parse_wheel_filename(asset_name)
    except Exception:
        return None

    if distribution != metadata.normalized_name:
        return None
    if version.public != str(metadata.base_version):
        return None
    if version.local is None:
        return None

    local_segment = str(version.local)
    if not local_segment.startswith("frida"):
        return None

    try:
        frida_version = Version(local_segment.removeprefix("frida"))
    except InvalidVersion:
        return None

    if str(version) != build_variant_version(metadata.base_version, frida_version):
        return None
    return frida_version


def _existing_variant_assets(
    asset_names: list[str],
    metadata: PackageMetadata,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for asset_name in asset_names:
        frida_version = _parse_existing_variant_version(asset_name, metadata)
        if frida_version is None:
            continue
        result[str(frida_version)] = asset_name
    return result


def build_release_plan(
    repo_root: Path,
    *,
    ref: str | None = None,
    available_versions: list[Version] | None = None,
    existing_assets: list[str] | None = None,
) -> dict[str, Any]:
    metadata = load_package_metadata(repo_root, ref=ref)
    release_version = parse_python_release_version(str(metadata.base_version))
    config = load_release_config(repo_root, ref=ref)
    _validate_frida_requirement_shape(metadata.frida_requirement, config)

    frida_versions = filter_supported_frida_versions(
        available_versions if available_versions is not None else fetch_frida_versions(),
        config,
    )
    variants = [
        {
            "tag_name": release_version.tag,
            "base_version": str(metadata.base_version),
            "frida_version": str(frida_version),
            "package_version": build_variant_version(metadata.base_version, frida_version),
        }
        for frida_version in frida_versions
    ]

    existing_variant_assets = _existing_variant_assets(existing_assets or [], metadata)
    missing_variants = [
        variant
        for variant in variants
        if variant["frida_version"] not in existing_variant_assets
    ]

    return {
        "tag_name": release_version.tag,
        "package_name": metadata.name,
        "base_version": str(metadata.base_version),
        "sdist_name": expected_sdist_name(metadata.name, str(metadata.base_version)),
        "supported_frida_versions": [str(item) for item in frida_versions],
        "variants": variants,
        "missing_variants": missing_variants,
        "existing_variant_assets": existing_variant_assets,
        "total_count": len(variants),
        "missing_count": len(missing_variants),
    }


def _format_toml_key(key: str) -> str:
    if SAFE_TOML_KEY.fullmatch(key):
        return key
    return json.dumps(key)


def _format_toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return f"[{', '.join(_format_toml_value(item) for item in value)}]"
    if isinstance(value, dict):
        items = ", ".join(
            f"{_format_toml_key(key)} = {_format_toml_value(item)}"
            for key, item in value.items()
        )
        return f"{{ {items} }}"
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")


def _write_toml_table(lines: list[str], path: list[str], table: dict[str, Any]) -> None:
    if path:
        lines.append(f"[{'.'.join(_format_toml_key(part) for part in path)}]")

    scalar_items: list[tuple[str, Any]] = []
    nested_tables: list[tuple[str, dict[str, Any]]] = []
    for key, value in table.items():
        if isinstance(value, dict):
            nested_tables.append((key, value))
        else:
            scalar_items.append((key, value))

    for key, value in scalar_items:
        lines.append(f"{_format_toml_key(key)} = {_format_toml_value(value)}")

    if scalar_items and nested_tables:
        lines.append("")

    for index, (key, value) in enumerate(nested_tables):
        _write_toml_table(lines, path + [key], value)
        if index != len(nested_tables) - 1:
            lines.append("")


def _dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    _write_toml_table(lines, [], data)
    return "\n".join(lines).rstrip() + "\n"


def _rewrite_pyproject_for_variant(
    pyproject_text: str,
    metadata: PackageMetadata,
    frida_version: str,
) -> str:
    pyproject = tomllib.loads(pyproject_text)
    dependencies = list(pyproject["project"]["dependencies"])
    dependencies[metadata.frida_dependency_index] = f"frida=={frida_version}"
    pyproject["project"]["dependencies"] = dependencies
    return _dump_toml(pyproject)


def _rewrite_version_file(version_text: str, package_version: str) -> str:
    updated, count = re.subn(
        r'(?m)^__version__\s*=\s*"[^"]+"\s*$',
        f'__version__ = "{package_version}"',
        version_text,
        count=1,
    )
    if count != 1:
        raise ReleaseConfigError("Could not rewrite __version__ in version file")
    return updated


def _copy_repo_for_build(repo_root: Path, temp_root: Path) -> Path:
    build_root = temp_root / "source"
    shutil.copytree(repo_root, build_root, ignore=BUILD_IGNORE_PATTERNS)
    return build_root


def _matching_built_wheels(
    wheel_paths: list[Path],
    metadata: PackageMetadata,
    package_version: str,
) -> list[Path]:
    matches: list[Path] = []
    for wheel_path in wheel_paths:
        try:
            distribution, version, _, _ = parse_wheel_filename(wheel_path.name)
        except Exception:
            continue
        if distribution != metadata.normalized_name:
            continue
        if str(version) != package_version:
            continue
        matches.append(wheel_path)
    return sorted(matches)


def build_variant_wheel(repo_root: Path, *, frida_version: str, out_dir: Path) -> Path:
    validate_release_contract(repo_root)
    metadata = load_package_metadata(repo_root)
    config = load_release_config(repo_root)
    requested_frida_version = Version(frida_version)
    supported_versions = filter_supported_frida_versions([requested_frida_version], config)
    if supported_versions != [requested_frida_version]:
        raise ReleaseConfigError(
            f"Frida {frida_version} is outside the configured release range "
            f"[{config.min_inclusive}, {config.max_exclusive})"
        )

    package_version = build_variant_version(metadata.base_version, frida_version)
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_wheels = set(out_dir.glob("*.whl"))

    with tempfile.TemporaryDirectory(prefix="frida-analykit-release-") as temp_dir:
        build_root = _copy_repo_for_build(repo_root, Path(temp_dir))
        pyproject_path = build_root / PYPROJECT_PATH
        version_path = build_root / metadata.version_file

        pyproject_path.write_text(
            _rewrite_pyproject_for_variant(
                pyproject_path.read_text(encoding="utf-8"),
                metadata,
                frida_version,
            ),
            encoding="utf-8",
        )
        version_path.write_text(
            _rewrite_version_file(version_path.read_text(encoding="utf-8"), package_version),
            encoding="utf-8",
        )

        try:
            subprocess.run(
                ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
                cwd=build_root,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ReleaseConfigError(
                f"uv build failed while building the Frida {frida_version} wheel"
            ) from exc

    built_wheels = set(out_dir.glob("*.whl")) - existing_wheels
    matches = _matching_built_wheels(list(built_wheels), metadata, package_version)
    if not matches:
        matches = _matching_built_wheels(list(out_dir.glob("*.whl")), metadata, package_version)
    if len(matches) != 1:
        raise ReleaseConfigError(
            f"Expected exactly one built wheel for {package_version}, found {len(matches)}"
        )
    return matches[0]


def build_variant_wheels(
    repo_root: Path,
    *,
    out_dir: Path,
    existing_assets: list[str] | None = None,
) -> dict[str, Any]:
    plan = build_release_plan(repo_root, existing_assets=existing_assets)
    built_variants: list[dict[str, str]] = []
    for variant in plan["missing_variants"]:
        wheel_path = build_variant_wheel(
            repo_root,
            frida_version=variant["frida_version"],
            out_dir=out_dir,
        )
        built_variants.append(
            {
                "frida_version": variant["frida_version"],
                "package_version": variant["package_version"],
                "wheel_name": wheel_path.name,
                "wheel_path": str(wheel_path),
            }
        )

    return {
        **plan,
        "built_variants": built_variants,
        "built_count": len(built_variants),
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


def _pick_variant_wheel(dist_dir: Path, metadata: PackageMetadata) -> Path:
    candidates = [
        path
        for path in sorted(dist_dir.glob("*.whl"))
        if _parse_existing_variant_version(path.name, metadata) is not None
    ]
    if not candidates:
        raise ReleaseConfigError("No pinned Frida wheel was found in dist/")
    return candidates[0]


def install_check(
    repo_root: Path,
    *,
    tag: str,
    dist_dir: Path,
    ref: str | None = None,
) -> dict[str, Any]:
    release_info = validate_release_version(repo_root, tag=tag, ref=ref)
    metadata = load_package_metadata(repo_root, ref=ref)
    config = load_release_config(repo_root, ref=ref)
    sdist_path = dist_dir / expected_sdist_name(metadata.name, str(metadata.base_version))
    if not sdist_path.exists():
        raise ReleaseConfigError(f"Missing source distribution: {sdist_path}")

    wheel_path = _pick_variant_wheel(dist_dir, metadata)
    tgz_path = _pick_single_file(
        sorted(repo_root.glob("*.tgz")),
        description="npm package tarball in the repository root",
    )

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
                f"frida=={config.min_inclusive}",
                str(sdist_path),
            ],
            cwd=repo_root,
            error_message="Failed to install the source distribution in a clean environment",
        )
        _run_checked(
            [str(sdist_python), "-m", "frida_analykit", "doctor"],
            cwd=repo_root,
            error_message="Installed source distribution failed the doctor check",
        )
        _run_checked(
            ["uv", "pip", "install", "--python", str(wheel_python), str(wheel_path)],
            cwd=repo_root,
            error_message="Failed to install the pinned wheel in a clean environment",
        )
        _run_checked(
            [str(wheel_python), "-m", "frida_analykit", "doctor"],
            cwd=repo_root,
            error_message="Installed pinned wheel failed the doctor check",
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
    }


def fetch_github_releases(repo: str, token: str, *, tag: str | None = None) -> list[dict[str, Any]]:
    base_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "frida-analykit-release-assets",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if tag is not None:
        encoded_tag = urllib.parse.quote(tag, safe="")
        url = f"{base_url}/repos/{repo}/releases/tags/{encoded_tag}"
        return [
            _fetch_json(
                url,
                headers=headers,
                context=f"GitHub release lookup for {tag}",
                not_found_message=f"GitHub release for tag {tag} was not found",
            )
        ]

    page = 1
    releases: list[dict[str, Any]] = []
    while True:
        url = f"{base_url}/repos/{repo}/releases?per_page=100&page={page}"
        page_items = _fetch_json(
            url,
            headers=headers,
            context=f"GitHub release listing page {page}",
        )
        if not page_items:
            break
        releases.extend(page_items)
        if len(page_items) < 100:
            break
        page += 1
    return releases


def discover_backfill_targets(
    releases: list[dict[str, Any]],
    *,
    tag: str | None = None,
) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    for release in releases:
        if release.get("draft"):
            if tag is not None and release.get("tag_name") == tag:
                raise ReleaseConfigError("Backfill only supports published releases, not drafts")
            continue
        if release.get("prerelease"):
            if tag is not None and release.get("tag_name") == tag:
                raise ReleaseConfigError("Backfill only supports stable releases, not prereleases")
            continue
        tag_name = release["tag_name"]
        if tag is not None and tag_name != tag:
            continue
        existing_assets = [asset["name"] for asset in release.get("assets", [])]
        targets.append(
            {
                "tag_name": tag_name,
                "existing_assets": existing_assets,
                "existing_assets_json": json.dumps(existing_assets, separators=(",", ":")),
            }
        )
    return {"targets": targets, "target_count": len(targets)}


def _dump_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def _collect_existing_assets(args: argparse.Namespace) -> list[str]:
    existing_assets = list(getattr(args, "existing_asset", []))
    existing_assets_json = getattr(args, "existing_assets_json", None)
    if existing_assets_json:
        try:
            parsed = json.loads(existing_assets_json)
        except json.JSONDecodeError as exc:
            raise ReleaseConfigError("--existing-assets-json must be valid JSON") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ReleaseConfigError("--existing-assets-json must be a JSON array of strings")
        existing_assets.extend(parsed)
    return existing_assets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage multi-Frida release assets")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-config")
    validate_parser.add_argument("--ref")
    validate_parser.add_argument("--json", action="store_true")

    version_parser = subparsers.add_parser("validate-release-version")
    version_parser.add_argument("--tag", required=True)
    version_parser.add_argument("--ref")
    version_parser.add_argument("--json", action="store_true")

    promotion_parser = subparsers.add_parser("validate-promotion")
    promotion_parser.add_argument("--tag", required=True)
    promotion_parser.add_argument("--ref")
    promotion_parser.add_argument("--rc-tag")
    promotion_parser.add_argument("--json", action="store_true")

    list_parser = subparsers.add_parser("list-frida-versions")
    list_parser.add_argument("--ref")
    list_parser.add_argument("--json", action="store_true")

    plan_parser = subparsers.add_parser("plan-release")
    plan_parser.add_argument("--ref")
    plan_parser.add_argument("--json", action="store_true")
    plan_parser.add_argument("--existing-assets-json")
    plan_parser.add_argument(
        "--existing-asset",
        action="append",
        default=[],
        help="Existing GitHub release asset name. Can be repeated.",
    )

    build_parser = subparsers.add_parser("build-wheel")
    build_parser.add_argument("--frida-version", required=True)
    build_parser.add_argument("--out-dir", default="dist")
    build_parser.add_argument("--json", action="store_true")

    build_many_parser = subparsers.add_parser("build-wheels")
    build_many_parser.add_argument("--out-dir", default="dist")
    build_many_parser.add_argument("--existing-assets-json")
    build_many_parser.add_argument(
        "--existing-asset",
        action="append",
        default=[],
        help="Existing GitHub release asset name. Can be repeated.",
    )
    build_many_parser.add_argument("--json", action="store_true")

    install_parser = subparsers.add_parser("install-check")
    install_parser.add_argument("--tag", required=True)
    install_parser.add_argument("--ref")
    install_parser.add_argument("--dist-dir", default="dist")
    install_parser.add_argument("--json", action="store_true")

    backfill_parser = subparsers.add_parser("discover-backfill")
    backfill_parser.add_argument("--repo", required=True)
    backfill_parser.add_argument("--tag")
    backfill_parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    backfill_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    repo_root = Path.cwd()

    try:
        if args.command == "validate-config":
            result = validate_release_contract(repo_root, ref=args.ref)
            if args.json:
                _dump_json(result)
            else:
                print(
                    f"{result['name']} {result['base_version']} "
                    f"supports [{result['min_inclusive']}, {result['max_exclusive']})"
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

        if args.command == "list-frida-versions":
            config = load_release_config(repo_root, ref=args.ref)
            versions = [str(item) for item in filter_supported_frida_versions(fetch_frida_versions(), config)]
            payload = {"versions": versions, "total_count": len(versions)}
            if args.json:
                _dump_json(payload)
            else:
                print("\n".join(versions))
            return 0

        if args.command == "plan-release":
            payload = build_release_plan(
                repo_root,
                ref=args.ref,
                existing_assets=_collect_existing_assets(args),
            )
            if args.json:
                _dump_json(payload)
            else:
                print(
                    f"{payload['tag_name']} -> {payload['total_count']} wheel variants, "
                    f"{payload['missing_count']} missing"
                )
            return 0

        if args.command == "build-wheel":
            wheel_path = build_variant_wheel(
                repo_root,
                frida_version=args.frida_version,
                out_dir=Path(args.out_dir),
            )
            if args.json:
                _dump_json(
                    {
                        "frida_version": args.frida_version,
                        "wheel_name": wheel_path.name,
                        "wheel_path": str(wheel_path),
                    }
                )
            else:
                print(wheel_path)
            return 0

        if args.command == "build-wheels":
            payload = build_variant_wheels(
                repo_root,
                out_dir=Path(args.out_dir),
                existing_assets=_collect_existing_assets(args),
            )
            if args.json:
                _dump_json(payload)
            else:
                print(
                    f"built {payload['built_count']} wheel(s); "
                    f"{payload['missing_count']} variant(s) were missing"
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
                    f"verified {payload['sdist_name']}, {payload['wheel_name']}, and {payload['npm_tgz']}"
                )
            return 0

        if args.command == "discover-backfill":
            if not args.github_token:
                raise ReleaseConfigError("--github-token is required")
            releases = fetch_github_releases(args.repo, args.github_token, tag=args.tag)
            payload = discover_backfill_targets(releases, tag=args.tag)
            if args.json:
                _dump_json(payload)
            else:
                print(f"{payload['target_count']} release target(s)")
            return 0
    except ReleaseConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
