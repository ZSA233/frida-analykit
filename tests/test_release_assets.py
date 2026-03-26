from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import textwrap
import urllib.error
import zipfile
from pathlib import Path

import pytest
from packaging.version import Version


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
          "/release",
          "/README.md",
          "/pyproject.toml",
        ]
        """,
    )
    _write_file(repo_root / "README.md", "# demo\n")
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
    _write_file(repo_root / "src/demo_tool/_version.py", '__version__ = "0.5.0"\n')
    _write_file(
        repo_root / "release/frida-builds.toml",
        """
        min_inclusive = "16.5.9"
        max_exclusive = "18.0.0"
        include_prerelease = false
        exclude = ["17.1.1"]
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


def test_filter_supported_frida_versions_respects_range_prerelease_and_exclude() -> None:
    config = release_assets.ReleaseBuildConfig(
        min_inclusive=Version("16.5.9"),
        max_exclusive=Version("18.0.0"),
        include_prerelease=False,
        exclude=(Version("17.1.1"),),
    )

    supported = release_assets.filter_supported_frida_versions(
        [
            Version("16.5.8"),
            Version("16.5.9"),
            Version("17.0.0rc1"),
            Version("17.0.0"),
            Version("17.1.1"),
            Version("17.8.2"),
            Version("18.0.0"),
        ],
        config,
    )

    assert supported == [Version("16.5.9"), Version("17.0.0"), Version("17.8.2")]


def test_rewrite_pyproject_for_variant_only_rewrites_direct_frida_dependency(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    metadata = release_assets.load_package_metadata(repo_root)
    rewritten = release_assets._rewrite_pyproject_for_variant(
        (repo_root / "pyproject.toml").read_text(encoding="utf-8"),
        metadata,
        "17.8.2",
    )

    assert 'frida =="' not in rewritten
    assert '"frida==17.8.2"' in rewritten
    assert '"frida-tools>=1.0.0,<2"' in rewritten


@pytest.mark.parametrize(
    ("dependency", "expected_message"),
    [
        ('"frida>=16.5.9,<18; python_version >= \\"3.11\\""', "must not use environment markers"),
        ('"frida[portal]>=16.5.9,<18"', "must not use extras"),
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


def test_build_release_plan_marks_missing_variants_from_actual_wheel_assets(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    plan = release_assets.build_release_plan(
        repo_root,
        available_versions=[
            Version("16.5.9"),
            Version("16.6.7"),
            Version("17.1.1"),
            Version("17.8.2"),
            Version("18.0.0"),
        ],
        existing_assets=[
            "demo_tool-0.5.0+frida16.5.9-py312-none-macosx_11_0_arm64.whl",
            "demo_tool-0.5.0.tar.gz",
        ],
    )

    assert plan["tag_name"] == "v0.5.0"
    assert plan["sdist_name"] == "demo_tool-0.5.0.tar.gz"
    assert plan["supported_frida_versions"] == ["16.5.9", "16.6.7", "17.8.2"]
    assert plan["total_count"] == 3
    assert plan["missing_count"] == 2
    assert [item["frida_version"] for item in plan["missing_variants"]] == ["16.6.7", "17.8.2"]


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


def test_build_release_plan_uses_semver_rc_tag_name(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    (repo_root / "src/demo_tool/_version.py").write_text('__version__ = "0.5.0rc1"\n', encoding="utf-8")

    plan = release_assets.build_release_plan(
        repo_root,
        available_versions=[Version("16.5.9")],
    )

    assert plan["tag_name"] == "v0.5.0-rc.1"
    assert plan["variants"][0]["tag_name"] == "v0.5.0-rc.1"


def test_build_release_plan_can_read_from_tagged_source(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    _git_init(repo_root)

    (repo_root / "src/demo_tool/_version.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (repo_root / "release/frida-builds.toml").write_text(
        textwrap.dedent(
            """
            min_inclusive = "17.0.0"
            max_exclusive = "18.0.0"
            include_prerelease = false
            exclude = []
            """
        ).lstrip(),
        encoding="utf-8",
    )

    plan = release_assets.build_release_plan(
        repo_root,
        ref="v0.5.0",
        available_versions=[Version("16.5.9"), Version("17.8.2")],
    )

    assert plan["tag_name"] == "v0.5.0"
    assert plan["base_version"] == "0.5.0"
    assert plan["supported_frida_versions"] == ["16.5.9", "17.8.2"]


def test_validate_promotion_allows_only_version_metadata_changes(tmp_path: Path) -> None:
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
        "src/demo_tool/_version.py",
    ]


def test_validate_promotion_rejects_functional_changes_after_rc(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    _git_init(repo_root)
    subprocess.run(["git", "tag", "v0.5.0-rc.1"], cwd=repo_root, check=True, capture_output=True, text=True)
    (repo_root / "README.md").write_text("# changed\n", encoding="utf-8")

    with pytest.raises(release_assets.ReleaseConfigError, match="Stable promotion only allows version metadata changes"):
        release_assets.validate_promotion(repo_root, tag="v0.5.0", rc_tag="v0.5.0-rc.1")


def test_discover_backfill_targets_returns_release_assets() -> None:
    payload = release_assets.discover_backfill_targets(
        [
            {
                "tag_name": "v0.5.0",
                "draft": False,
                "assets": [{"name": "a.whl"}, {"name": "b.tar.gz"}],
            },
            {
                "tag_name": "v0.4.0",
                "draft": True,
                "assets": [{"name": "skip.whl"}],
            },
            {
                "tag_name": "v0.5.0-rc.1",
                "draft": False,
                "prerelease": True,
                "assets": [{"name": "rc.whl"}],
            },
        ]
    )

    assert payload == {
        "targets": [
            {
                "tag_name": "v0.5.0",
                "existing_assets": ["a.whl", "b.tar.gz"],
                "existing_assets_json": '["a.whl","b.tar.gz"]',
            }
        ],
        "target_count": 1,
    }


def test_discover_backfill_targets_rejects_explicit_prerelease_tag() -> None:
    with pytest.raises(release_assets.ReleaseConfigError, match="stable releases, not prereleases"):
        release_assets.discover_backfill_targets(
            [
                {
                    "tag_name": "v0.5.0-rc.1",
                    "draft": False,
                    "prerelease": True,
                    "assets": [],
                }
            ],
            tag="v0.5.0-rc.1",
        )


def test_fetch_frida_versions_wraps_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(release_assets.urllib.request, "urlopen", _fail)
    monkeypatch.setattr(release_assets.time, "sleep", lambda _seconds: None)

    with pytest.raises(release_assets.ReleaseConfigError, match="PyPI frida release discovery failed"):
        release_assets.fetch_frida_versions()


def test_fetch_github_releases_wraps_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *_args, **_kwargs):
            return b"{invalid"

    monkeypatch.setattr(release_assets.urllib.request, "urlopen", lambda *args, **kwargs: _FakeResponse())

    with pytest.raises(release_assets.ReleaseConfigError, match="returned invalid JSON"):
        release_assets.fetch_github_releases("ZSA233/frida-analykit", "token", tag="v0.5.0")


def test_fetch_github_releases_wraps_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://api.github.com",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b"missing"),
        )

    monkeypatch.setattr(release_assets.urllib.request, "urlopen", _fail)

    with pytest.raises(release_assets.ReleaseConfigError, match="GitHub release for tag v0.5.0 was not found"):
        release_assets.fetch_github_releases("ZSA233/frida-analykit", "token", tag="v0.5.0")


def test_build_variant_wheel_rewrites_metadata_in_temp_copy(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    out_dir = tmp_path / "dist"

    wheel_path = release_assets.build_variant_wheel(
        repo_root,
        frida_version="17.8.2",
        out_dir=out_dir,
    )

    assert wheel_path.suffix == ".whl"
    assert "0.5.0+frida17.8.2" in wheel_path.name
    assert (repo_root / "src/demo_tool/_version.py").read_text(encoding="utf-8") == '__version__ = "0.5.0"\n'
    assert '"frida>=16.5.9,<18"' in (repo_root / "pyproject.toml").read_text(encoding="utf-8")

    with zipfile.ZipFile(wheel_path) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith("/METADATA"))
        metadata = archive.read(metadata_name).decode()

    assert "Version: 0.5.0+frida17.8.2" in metadata
    assert "Requires-Dist: frida==17.8.2" in metadata
    assert "Requires-Dist: frida-tools<2,>=1.0.0" in metadata


def test_build_variant_wheels_returns_built_variants(tmp_path: Path) -> None:
    repo_root = _make_release_repo(tmp_path)
    (repo_root / "pyproject.toml").write_text(
        (repo_root / "pyproject.toml")
        .read_text(encoding="utf-8")
        .replace('"frida>=16.5.9,<18"', '"frida>=16.5.9,<16.6.0"'),
        encoding="utf-8",
    )
    (repo_root / "release/frida-builds.toml").write_text(
        textwrap.dedent(
            """
            min_inclusive = "16.5.9"
            max_exclusive = "16.6.0"
            include_prerelease = false
            exclude = []
            """
        ).lstrip(),
        encoding="utf-8",
    )

    original_fetch = release_assets.fetch_frida_versions
    release_assets.fetch_frida_versions = lambda: [Version("16.5.9")]
    try:
        payload = release_assets.build_variant_wheels(repo_root, out_dir=tmp_path / "dist")
    finally:
        release_assets.fetch_frida_versions = original_fetch

    assert payload["total_count"] == 1
    assert payload["missing_count"] == 1
    assert payload["built_count"] == 1
    assert payload["built_variants"][0]["frida_version"] == "16.5.9"
    assert payload["built_variants"][0]["wheel_name"].endswith(".whl")
