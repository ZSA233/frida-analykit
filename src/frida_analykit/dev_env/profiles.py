from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from .constants import COMPAT_PROFILES_PATH
from .models import CompatProfile


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
            tested_version=item["tested_version"],
        )
    return profiles
