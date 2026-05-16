from __future__ import annotations

import re
from pathlib import Path

from tests.support.paths import REPO_ROOT


PUBLIC_DOC_NAMES = ("mcp.md", "elf-fixups.md", "device-regression.md")


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _heading_levels(text: str) -> list[int]:
    levels: list[int] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+", line)
        if match:
            levels.append(len(match.group(1)))
    return levels


def _code_fence_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith("```"))


def _table_shapes(text: str) -> list[tuple[int, int]]:
    shapes: list[tuple[int, int]] = []
    current_rows: list[str] = []

    def flush() -> None:
        if not current_rows:
            return
        column_counts = [row.count("|") - 1 for row in current_rows]
        shapes.append((len(current_rows), max(column_counts)))
        current_rows.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            current_rows.append(stripped)
        else:
            flush()
    flush()
    return shapes


def _assert_mirror_shape(left_path: str, right_path: str) -> None:
    left = _read(left_path)
    right = _read(right_path)

    assert _heading_levels(left) == _heading_levels(right)
    assert _code_fence_count(left) == _code_fence_count(right)
    assert _table_shapes(left) == _table_shapes(right)


def test_readme_pairs_keep_mirror_structure() -> None:
    _assert_mirror_shape("README.md", "README_EN.md")
    _assert_mirror_shape(
        "packages/frida-analykit-agent/README.md",
        "packages/frida-analykit-agent/README_EN.md",
    )
    _assert_mirror_shape(
        "src/frida_analykit/resources/scaffold/README.md",
        "src/frida_analykit/resources/scaffold/README_EN.md",
    )


def test_public_docs_keep_zh_en_mirror_structure() -> None:
    for name in PUBLIC_DOC_NAMES:
        zh_path = REPO_ROOT / "docs" / "zh" / name
        en_path = REPO_ROOT / "docs" / "en" / name
        assert zh_path.exists()
        assert en_path.exists()
        _assert_mirror_shape(f"docs/zh/{name}", f"docs/en/{name}")


def test_readmes_link_to_public_docs_not_internal_runbooks() -> None:
    root_readme = _read("README.md")
    root_readme_en = _read("README_EN.md")
    package_readme = _read("packages/frida-analykit-agent/README.md")
    package_readme_en = _read("packages/frida-analykit-agent/README_EN.md")

    combined_root = root_readme + root_readme_en
    assert "src/frida_analykit/mcp/README.MD" not in combined_root
    assert "docs/release-process.md" not in combined_root
    assert "docs/zh/mcp.md" in root_readme
    assert "docs/en/mcp.md" in root_readme_en
    assert "docs/zh/elf-fixups.md" in root_readme
    assert "docs/en/elf-fixups.md" in root_readme_en
    assert "docs/zh/device-regression.md" in root_readme
    assert "docs/en/device-regression.md" in root_readme_en

    assert "blob/stable/docs/zh/elf-fixups.md" in package_readme
    assert "blob/stable/docs/en/elf-fixups.md" in package_readme_en


def test_old_public_doc_paths_are_compatibility_stubs() -> None:
    assert not (REPO_ROOT / "src/frida_analykit/mcp/README.MD").exists()

    for relative_path, zh_target, en_target in (
        ("docs/elf-fixups.md", "docs/zh/elf-fixups.md", "docs/en/elf-fixups.md"),
        (
            "docs/device-regression.md",
            "docs/zh/device-regression.md",
            "docs/en/device-regression.md",
        ),
    ):
        text = _read(relative_path)
        assert zh_target in text
        assert en_target in text
        assert len(text.splitlines()) <= 8

