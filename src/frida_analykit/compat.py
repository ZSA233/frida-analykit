from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import frida


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> "Version":
        core = raw.split("-", 1)[0]
        parts = core.split(".")
        if len(parts) < 3:
            parts.extend(["0"] * (3 - len(parts)))
        return cls(*(int(part) for part in parts[:3]))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class CompatibilityProfile:
    name: str
    series: str
    tested_version: Version
    min_inclusive: Version
    max_exclusive: Version

    def contains(self, version: Version) -> bool:
        return self.min_inclusive <= version < self.max_exclusive


def _load_profiles() -> list[CompatibilityProfile]:
    raw = json.loads(
        files("frida_analykit.resources")
        .joinpath("compat_profiles.json")
        .read_text(encoding="utf-8")
    )
    profiles = []
    for item in raw["profiles"]:
        profiles.append(
            CompatibilityProfile(
                name=item["name"],
                series=item["series"],
                tested_version=Version.parse(item["tested_version"]),
                min_inclusive=Version.parse(item["min_inclusive"]),
                max_exclusive=Version.parse(item["max_exclusive"]),
            )
        )
    return profiles


class FridaCompat:
    def __init__(self, frida_module: Any = frida) -> None:
        self._frida = frida_module
        self._profiles = _load_profiles()

    @property
    def profiles(self) -> list[CompatibilityProfile]:
        return list(self._profiles)

    @property
    def installed_version(self) -> Version:
        return Version.parse(self._frida.__version__)

    def matched_profile(self, version: Version | None = None) -> CompatibilityProfile | None:
        candidate = version or self.installed_version
        for profile in self._profiles:
            if profile.contains(candidate):
                return profile
        return None

    def get_device(self, host: str):
        if host in {"local", "local://"}:
            return self._frida.get_local_device()
        if host in {"usb", "usb://"}:
            return self._frida.get_usb_device()
        return self._frida.get_device_manager().add_remote_device(host)

    def enumerate_applications(self, device, *, scope: str = "minimal"):
        try:
            return device.enumerate_applications(scope=scope)
        except TypeError:
            return device.enumerate_applications()

    def doctor_report(self) -> dict[str, Any]:
        version = self.installed_version
        profile = self.matched_profile(version)
        return {
            "installed_version": str(version),
            "matched_profile": profile.name if profile else None,
            "supported": profile is not None,
            "profiles": [
                {
                    "name": item.name,
                    "series": item.series,
                    "tested_version": str(item.tested_version),
                    "range": f">={item.min_inclusive}, <{item.max_exclusive}",
                }
                for item in self._profiles
            ],
        }
