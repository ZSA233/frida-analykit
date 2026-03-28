from __future__ import annotations

import re
from dataclasses import dataclass


_STABLE_VERSION_RE = re.compile(r"^(?P<base>\d+\.\d+\.\d+)$")
_PYTHON_RC_VERSION_RE = re.compile(r"^(?P<base>\d+\.\d+\.\d+)rc(?P<rc>[1-9]\d*)$")
_NPM_RC_VERSION_RE = re.compile(r"^(?P<base>\d+\.\d+\.\d+)-rc\.(?P<rc>[1-9]\d*)$")
_STABLE_TAG_RE = re.compile(r"^v(?P<base>\d+\.\d+\.\d+)$")
_RC_TAG_RE = re.compile(r"^v(?P<base>\d+\.\d+\.\d+)-rc\.(?P<rc>[1-9]\d*)$")


class ReleaseVersionError(ValueError):
    pass


@dataclass(frozen=True)
class ReleaseVersion:
    base_version: str
    rc_number: int | None = None

    @property
    def kind(self) -> str:
        return "rc" if self.rc_number is not None else "stable"

    @property
    def is_rc(self) -> bool:
        return self.rc_number is not None

    @property
    def python_version(self) -> str:
        if self.rc_number is None:
            return self.base_version
        return f"{self.base_version}rc{self.rc_number}"

    @property
    def npm_version(self) -> str:
        if self.rc_number is None:
            return self.base_version
        return f"{self.base_version}-rc.{self.rc_number}"

    @property
    def tag(self) -> str:
        if self.rc_number is None:
            return f"v{self.base_version}"
        return f"v{self.base_version}-rc.{self.rc_number}"

    @property
    def agent_package_spec(self) -> str:
        return self.npm_version


def _parse_release_parts(raw: str) -> tuple[str, int | None]:
    stable_match = _STABLE_VERSION_RE.fullmatch(raw)
    if stable_match:
        return stable_match.group("base"), None

    python_rc_match = _PYTHON_RC_VERSION_RE.fullmatch(raw)
    if python_rc_match:
        return python_rc_match.group("base"), int(python_rc_match.group("rc"))

    npm_rc_match = _NPM_RC_VERSION_RE.fullmatch(raw)
    if npm_rc_match:
        return npm_rc_match.group("base"), int(npm_rc_match.group("rc"))

    raise ReleaseVersionError(f"Unsupported release version: {raw}")


def parse_python_release_version(raw: str) -> ReleaseVersion:
    base_version, rc_number = _parse_release_parts(raw)
    return ReleaseVersion(base_version=base_version, rc_number=rc_number)


def parse_npm_release_version(raw: str) -> ReleaseVersion:
    base_version, rc_number = _parse_release_parts(raw)
    return ReleaseVersion(base_version=base_version, rc_number=rc_number)


def parse_release_tag(raw: str) -> ReleaseVersion:
    stable_match = _STABLE_TAG_RE.fullmatch(raw)
    if stable_match:
        return ReleaseVersion(base_version=stable_match.group("base"))

    rc_match = _RC_TAG_RE.fullmatch(raw)
    if rc_match:
        return ReleaseVersion(
            base_version=rc_match.group("base"),
            rc_number=int(rc_match.group("rc")),
        )

    raise ReleaseVersionError(f"Unsupported release tag: {raw}")


def npm_version_for_python_release(raw: str) -> str:
    return parse_python_release_version(raw).npm_version


def agent_package_spec_for_python_release(raw: str) -> str:
    return parse_python_release_version(raw).agent_package_spec
