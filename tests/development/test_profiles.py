from __future__ import annotations

import textwrap
from pathlib import Path

from frida_analykit.development import load_profiles


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_load_profiles_reads_compat_data(tmp_path: Path) -> None:
    _write_file(
        tmp_path / "src/frida_analykit/resources/compat_profiles.json",
        """
        {
          "profiles": [
            {"name": "legacy-16", "series": "16.x", "tested_version": "16.5.9", "min_inclusive": "16.5.0", "max_exclusive": "17.0.0"},
            {"name": "current-17", "series": "17.x", "tested_version": "17.8.2", "min_inclusive": "17.0.0", "max_exclusive": "18.0.0"}
          ]
        }
        """,
    )

    profiles = load_profiles(tmp_path)

    assert profiles["legacy-16"].tested_version == "16.5.9"
    assert profiles["current-17"].tested_version == "17.8.2"
