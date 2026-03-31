from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

COMPAT_PROFILES_PATH = Path("src/frida_analykit/resources/compat_profiles.json")


@dataclass(frozen=True, slots=True)
class CompatProfile:
    name: str
    series: str
    tested_version: str
    min_inclusive: str
    max_exclusive: str


def load_profiles(repo_root: Path | None = None) -> dict[str, CompatProfile]:
    if repo_root is None or not (repo_root / COMPAT_PROFILES_PATH).exists():
        payload = json.loads(
            files("frida_analykit.resources")
            .joinpath("compat_profiles.json")
            .read_text(encoding="utf-8")
        )
    else:
        payload = json.loads((repo_root / COMPAT_PROFILES_PATH).read_text(encoding="utf-8"))

    profiles: dict[str, CompatProfile] = {}
    for item in payload["profiles"]:
        profiles[item["name"]] = CompatProfile(
            name=item["name"],
            series=item["series"],
            tested_version=item["tested_version"],
            min_inclusive=item["min_inclusive"],
            max_exclusive=item["max_exclusive"],
        )
    return profiles
