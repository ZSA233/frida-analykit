from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from importlib.resources import files
import re
from typing import Any

import frida

PACKAGE_NAME = "frida-analykit"


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


def _profile_support_range(profiles: list[CompatibilityProfile]) -> SupportRange:
    min_inclusive = min(profile.min_inclusive for profile in profiles)
    max_exclusive = max(profile.max_exclusive for profile in profiles)
    return SupportRange(min_inclusive=min_inclusive, max_exclusive=max_exclusive)


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


def _parse_supported_range(raw_requirement: str) -> SupportRange | None:
    requirement = raw_requirement.split(";", 1)[0].strip()
    match = re.fullmatch(r"frida(?P<specifiers>.*)", requirement)
    if match is None:
        return None

    lower_bound: Version | None = None
    upper_bound: Version | None = None
    specifiers = [item.strip() for item in match.group("specifiers").split(",") if item.strip()]
    for specifier in specifiers:
        if specifier.startswith(">="):
            lower_bound = Version.parse(specifier[2:])
            continue
        if specifier.startswith("<"):
            upper_bound = Version.parse(specifier[1:])
            continue
        return None

    if lower_bound is None or upper_bound is None:
        return None
    return SupportRange(min_inclusive=lower_bound, max_exclusive=upper_bound)


def _load_declared_support_range(profiles: list[CompatibilityProfile]) -> SupportRange:
    try:
        requirements = importlib_metadata.requires(PACKAGE_NAME) or []
    except importlib_metadata.PackageNotFoundError:
        requirements = []

    for raw_requirement in requirements:
        parsed = _parse_supported_range(raw_requirement)
        if parsed is not None:
            return parsed
    return _profile_support_range(profiles)


class FridaCompat:
    def __init__(
        self,
        frida_module: Any = frida,
        *,
        profiles: list[CompatibilityProfile] | None = None,
        support_range: SupportRange | None = None,
    ) -> None:
        self._frida = frida_module
        self._profiles = list(profiles) if profiles is not None else _load_profiles()
        self._support_range = support_range or _load_declared_support_range(self._profiles)

    @property
    def profiles(self) -> list[CompatibilityProfile]:
        return list(self._profiles)

    @property
    def support_range(self) -> SupportRange:
        return self._support_range

    @property
    def installed_version(self) -> Version:
        return Version.parse(self._frida.__version__)

    def matched_profile(self, version: Version | None = None) -> CompatibilityProfile | None:
        candidate = version or self.installed_version
        for profile in self._profiles:
            if profile.contains(candidate):
                return profile
        return None

    def get_device(self, host: str, *, device_id: str | None = None):
        manager = self._frida.get_device_manager()
        if host in {"local", "local://"}:
            return self._frida.get_local_device()
        if host in {"usb", "usb://"}:
            if device_id:
                return manager.get_device(device_id, timeout=5000)
            return self._frida.get_usb_device()
        return manager.add_remote_device(host)

    def enumerate_applications(self, device, *, scope: str = "minimal"):
        try:
            return device.enumerate_applications(scope=scope)
        except TypeError:
            return device.enumerate_applications()

    def support_status(self, version: Version | None = None) -> str:
        candidate = version or self.installed_version
        for profile in self._profiles:
            if candidate == profile.tested_version:
                return "tested"
        if self._support_range.contains(candidate):
            return "supported but untested"
        return "unsupported"

    def doctor_report(self) -> dict[str, Any]:
        version = self.installed_version
        profile = self.matched_profile(version)
        support_status = self.support_status(version)
        return {
            "installed_version": str(version),
            "support_status": support_status,
            "support_range": str(self._support_range),
            "matched_profile": profile.name if profile else None,
            "tested_version": str(profile.tested_version) if profile else None,
            "supported": support_status != "unsupported",
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
