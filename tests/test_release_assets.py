from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "release_assets.py"
SPEC = importlib.util.spec_from_file_location("release_assets", MODULE_PATH)
release_assets = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = release_assets
SPEC.loader.exec_module(release_assets)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _make_release_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    _write_file(
        repo_root / "pyproject.toml",
        """
        [build-system]
        requires = ["hatchling>=1.27.0"]
        build-backend = "hatchling.build"

        [project]
        name = "demo-tool"
        dynamic = ["version"]
        description = "demo"
        readme = "README.md"
        requires-python = ">=3.11"
        license = { text = "MIT" }
        authors = [{ name = "zsa233" }]
        dependencies = [
          "frida>=16.5.9,<18",
          "frida-tools>=1.0.0,<2",
        ]

        [tool.hatch.version]
        path = "src/demo_tool/_version.py"

        [tool.hatch.build.targets.wheel]
        packages = ["src/demo_tool"]

        [tool.hatch.build.targets.sdist]
        include = [
          "/src",
          "/scripts",
          "/README.md",
          "/pyproject.toml",
        ]
        """,
    )
    _write_file(repo_root / "README.md", "# demo\n")
    _write_file(
        repo_root / "release-version.toml",
        """
        base_version = "0.5.0"
        channel = "stable"
        """,
    )
    _write_file(
        repo_root / "package.json",
        """
        {
          "name": "demo-monorepo",
          "version": "0.5.0",
          "private": true,
          "workspaces": ["packages/*"],
          "dependencies": {
            "@zsa233/frida-analykit-agent": "^0.5.0"
          }
        }
        """,
    )
    _write_file(
        repo_root / "package-lock.json",
        """
        {
          "name": "demo-monorepo",
          "version": "0.5.0",
          "lockfileVersion": 3,
          "packages": {
            "": {
              "name": "demo-monorepo",
              "version": "0.5.0",
              "dependencies": {
                "@zsa233/frida-analykit-agent": "^0.5.0"
              }
            },
            "packages/frida-analykit-agent": {
              "name": "@zsa233/frida-analykit-agent",
              "version": "0.5.0"
            }
          }
        }
        """,
    )
    _write_file(
        repo_root / "packages/frida-analykit-agent/package.json",
        """
        {
          "name": "@zsa233/frida-analykit-agent",
          "version": "0.5.0"
        }
        """,
    )
    _write_file(repo_root / "src/demo_tool/__init__.py", "")
    _write_file(repo_root / "src/demo_tool/__main__.py", "print('doctor ok')\n")
    _write_file(repo_root / "src/demo_tool/_version.py", '__version__ = "0.5.0"\n')
    _write_file(
        repo_root / "src/frida_analykit/resources/compat_profiles.json",
        """
        {
          "profiles": [
            {
              "name": "legacy-16",
              "series": "16.x",
              "tested_version": "16.5.9",
              "min_inclusive": "16.5.9",
              "max_exclusive": "17.0.0"
            },
            {
              "name": "current-17",
              "series": "17.x",
              "tested_version": "17.8.2",
              "min_inclusive": "17.0.0",
              "max_exclusive": "18.0.0"
            }
          ]
        }
        """,
    )
    return repo_root


def _git_init(repo_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "zsa233@example.com"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "zsa233"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "tag", "v0.5.0"], cwd=repo_root, check=True, capture_output=True, text=True)


def test_validate_release_contract_reports_support_range_and_profiles(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)

    payload = release_assets.validate_release_contract(repo_root)

    assert payload["name"] == "demo-tool"
    assert payload["base_version"] == "0.5.0"
    assert payload["support_range"] == ">=16.5.9, <18"
    assert payload["tested_profiles"] == ["legacy-16", "current-17"]


@pytest.mark.parametrize(
    ("dependency", "expected_message"),
    [
        ('"frida>=16.5.9,<18; python_version >= \\"3.11\\""', "must not use environment markers"),
        ('"frida[portal]>=16.5.9,<18"', "must not use extras"),
        ('"frida>=16.5.9,<18,!=17.0.0"', "must only use a >= lower bound and a < upper bound"),
    ],
)
def test_validate_release_contract_rejects_complex_frida_requirements(
    tmp_path: Path,
    dependency: str,
    expected_message: str,
) -> None:
    repo_root = _make_release_repo(tmp_path)
    (repo_root / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""
            [build-system]
            requires = ["hatchling>=1.27.0"]
            build-backend = "hatchling.build"

            [project]
            name = "demo-tool"
            dynamic = ["version"]
            description = "demo"
            readme = "README.md"
            requires-python = ">=3.11"
            dependencies = [
              {dependency},
            ]

            [tool.hatch.version]
            path = "src/demo_tool/_version.py"
            """
        ).lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(release_assets.ReleaseConfigError, match=expected_message):
        release_assets.validate_release_contract(repo_root)


def test_validate_release_contract_rejects_duplicate_frida_dependency(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    (repo_root / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [build-system]
            requires = ["hatchling>=1.27.0"]
            build-backend = "hatchling.build"

            [project]
            name = "demo-tool"
            dynamic = ["version"]
            description = "demo"
            readme = "README.md"
            requires-python = ">=3.11"
            dependencies = [
              "frida>=16.5.9,<18",
              "frida==17.8.2",
            ]

            [tool.hatch.version]
            path = "src/demo_tool/_version.py"
            """
        ).lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(release_assets.ReleaseConfigError, match="exactly one direct frida dependency"):
        release_assets.validate_release_contract(repo_root)


def test_validate_release_contract_rejects_profile_outside_declared_range(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    (repo_root / "src/frida_analykit/resources/compat_profiles.json").write_text(
        textwrap.dedent(
            """
            {
              "profiles": [
                {
                  "name": "too-wide",
                  "series": "18.x",
                  "tested_version": "18.0.1",
                  "min_inclusive": "18.0.0",
                  "max_exclusive": "19.0.0"
                }
              ]
            }
            """
        ).lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(release_assets.ReleaseConfigError, match="ends after the declared frida support range"):
        release_assets.validate_release_contract(repo_root)


def test_validate_release_version_accepts_rc_mapping(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    (repo_root / "src/demo_tool/_version.py").write_text('__version__ = "0.5.0rc1"\n', encoding="utf-8")
    (repo_root / "package.json").write_text(
        (repo_root / "package.json")
        .read_text(encoding="utf-8")
        .replace('"version": "0.5.0"', '"version": "0.5.0-rc.1"', 1)
        .replace('"^0.5.0"', '"^0.5.0-rc.1"'),
        encoding="utf-8",
    )
    (repo_root / "packages/frida-analykit-agent/package.json").write_text(
        (repo_root / "packages/frida-analykit-agent/package.json")
        .read_text(encoding="utf-8")
        .replace('"version": "0.5.0"', '"version": "0.5.0-rc.1"'),
        encoding="utf-8",
    )

    payload = release_assets.validate_release_version(repo_root, tag="v0.5.0-rc.1")

    assert payload["kind"] == "rc"
    assert payload["python_version"] == "0.5.0rc1"
    assert payload["npm_version"] == "0.5.0-rc.1"
    assert payload["agent_package_spec"] == "^0.5.0-rc.1"


def test_validate_promotion_allows_only_version_metadata_changes(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    (repo_root / "release-version.toml").write_text(
        'base_version = "0.5.0"\nchannel = "rc"\nrc_number = 1\n',
        encoding="utf-8",
    )
    (repo_root / "src/demo_tool/_version.py").write_text('__version__ = "0.5.0rc1"\n', encoding="utf-8")
    (repo_root / "package.json").write_text(
        (repo_root / "package.json")
        .read_text(encoding="utf-8")
        .replace('"version": "0.5.0"', '"version": "0.5.0-rc.1"', 1)
        .replace('"^0.5.0"', '"^0.5.0-rc.1"'),
        encoding="utf-8",
    )
    (repo_root / "packages/frida-analykit-agent/package.json").write_text(
        (repo_root / "packages/frida-analykit-agent/package.json")
        .read_text(encoding="utf-8")
        .replace('"version": "0.5.0"', '"version": "0.5.0-rc.1"'),
        encoding="utf-8",
    )
    (repo_root / "package-lock.json").write_text(
        (repo_root / "package-lock.json")
        .read_text(encoding="utf-8")
        .replace('"version": "0.5.0"', '"version": "0.5.0-rc.1"', 1)
        .replace('"version": "0.5.0"', '"version": "0.5.0-rc.1"', 1)
        .replace('"^0.5.0"', '"^0.5.0-rc.1"'),
        encoding="utf-8",
    )
    _git_init(repo_root)
    subprocess.run(["git", "tag", "v0.5.0-rc.1"], cwd=repo_root, check=True, capture_output=True, text=True)

    (repo_root / "release-version.toml").write_text(
        'base_version = "0.5.0"\nchannel = "stable"\n',
        encoding="utf-8",
    )
    (repo_root / "src/demo_tool/_version.py").write_text('__version__ = "0.5.0"\n', encoding="utf-8")
    (repo_root / "package.json").write_text(
        (repo_root / "package.json")
        .read_text(encoding="utf-8")
        .replace('"version": "0.5.0-rc.1"', '"version": "0.5.0"', 1)
        .replace('"^0.5.0-rc.1"', '"^0.5.0"'),
        encoding="utf-8",
    )
    (repo_root / "packages/frida-analykit-agent/package.json").write_text(
        (repo_root / "packages/frida-analykit-agent/package.json")
        .read_text(encoding="utf-8")
        .replace('"version": "0.5.0-rc.1"', '"version": "0.5.0"'),
        encoding="utf-8",
    )
    (repo_root / "package-lock.json").write_text(
        (repo_root / "package-lock.json")
        .read_text(encoding="utf-8")
        .replace('"version": "0.5.0-rc.1"', '"version": "0.5.0"', 1)
        .replace('"version": "0.5.0-rc.1"', '"version": "0.5.0"', 1)
        .replace('"^0.5.0-rc.1"', '"^0.5.0"'),
        encoding="utf-8",
    )

    payload = release_assets.validate_promotion(repo_root, tag="v0.5.0")

    assert payload["rc_tag"] == "v0.5.0-rc.1"
    assert sorted(payload["changed_paths"]) == [
        "package-lock.json",
        "package.json",
        "packages/frida-analykit-agent/package.json",
        "release-version.toml",
        "src/demo_tool/_version.py",
    ]


def test_validate_promotion_rejects_functional_changes_after_rc(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    _git_init(repo_root)
    subprocess.run(["git", "tag", "v0.5.0-rc.1"], cwd=repo_root, check=True, capture_output=True, text=True)
    (repo_root / "README.md").write_text("# changed\n", encoding="utf-8")

    with pytest.raises(release_assets.ReleaseConfigError, match="Stable promotion only allows version metadata changes"):
        release_assets.validate_promotion(repo_root, tag="v0.5.0", rc_tag="v0.5.0-rc.1")


def test_install_check_uses_single_release_artifacts_and_minimum_supported_frida(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = _make_release_repo(tmp_path)
    dist_dir = repo_root / "dist"
    dist_dir.mkdir()
    (dist_dir / "demo_tool-0.5.0.tar.gz").write_text("sdist", encoding="utf-8")
    (dist_dir / "demo_tool-0.5.0-py3-none-any.whl").write_text("wheel", encoding="utf-8")
    (repo_root / "zsa233-frida-analykit-agent-0.5.0.tgz").write_text("tgz", encoding="utf-8")

    commands: list[list[str]] = []

    def _fake_run_checked(command: list[str], *, cwd: Path | None = None, error_message: str):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(release_assets, "_run_checked", _fake_run_checked)

    payload = release_assets.install_check(repo_root, tag="v0.5.0", dist_dir=dist_dir)

    assert payload["wheel_name"] == "demo_tool-0.5.0-py3-none-any.whl"
    assert payload["support_range"] == ">=16.5.9, <18"
    assert any(command[-1] == "frida==16.5.9" for command in commands)
    assert any(command[-3:] == ["-m", "frida_analykit", "doctor"] for command in commands)
    assert any("--agent-package-spec" in command for command in commands)


def test_release_build_outputs_single_wheel_with_range_dependency(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    dist_dir = repo_root / "dist"
    env = dict(os.environ)
    # Isolate uv's cache from the user profile so this build test does not
    # depend on host cache permissions or preexisting global state.
    env["UV_CACHE_DIR"] = str(tmp_path / ".uv-cache")

    subprocess.run(
        ["uv", "build", "--sdist", "--wheel", "--out-dir", str(dist_dir)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    metadata = release_assets.load_package_metadata(repo_root)
    wheel_path = release_assets._pick_release_wheel(dist_dir, metadata)
    sdist_path = dist_dir / release_assets.expected_sdist_name("demo-tool", "0.5.0")

    assert wheel_path.name == "demo_tool-0.5.0-py3-none-any.whl"
    assert "+frida" not in wheel_path.name
    assert sdist_path.exists()

    with zipfile.ZipFile(wheel_path) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith("/METADATA"))
        wheel_metadata = archive.read(metadata_name).decode()

    assert "Version: 0.5.0" in wheel_metadata
    assert "Requires-Dist: frida<18,>=16.5.9" in wheel_metadata
    assert "Requires-Dist: frida-tools<2,>=1.0.0" in wheel_metadata
