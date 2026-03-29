from __future__ import annotations

import re

_ANDROID_ABI_TO_ASSET = {
    "arm64-v8a": "android-arm64",
    "armeabi-v7a": "android-arm",
    "armeabi": "android-arm",
    "x86_64": "android-x86_64",
    "x86": "android-x86",
}

_UNAME_TO_ASSET = {
    "aarch64": ("arm64-v8a", "android-arm64"),
    "armv8l": ("arm64-v8a", "android-arm64"),
    "armv7l": ("armeabi-v7a", "android-arm"),
    "armv7": ("armeabi-v7a", "android-arm"),
    "arm": ("armeabi-v7a", "android-arm"),
    "i686": ("x86", "android-x86"),
    "i386": ("x86", "android-x86"),
    "x86_64": ("x86_64", "android-x86_64"),
}

_ASSET_TO_DISPLAY_ABI = {
    "android-arm64": "arm64-v8a",
    "android-arm": "armeabi-v7a",
    "android-x86_64": "x86_64",
    "android-x86": "x86",
}

_ABI_PROPERTY_PREFIXES = (
    "ro.product.cpu",
    "ro.odm.product.cpu",
    "ro.vendor.product.cpu",
    "ro.system.product.cpu",
)

_ABI_PROPERTY_SUFFIXES = (
    "abilist64",
    "abilist",
    "abilist32",
    "abi",
    "abi2",
)

_VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z._-]+)?")
_ABI_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(arm64-v8a|armeabi-v7a|armeabi|x86_64|x86|aarch64|armv8l|armv7l|armv7|i686|i386)(?![A-Za-z0-9_])",
    flags=re.IGNORECASE,
)

_ROOT_FAILURE_MARKERS = (
    "permission denied",
    "operation not permitted",
    "read-only file system",
)

_SU_FAILURE_MARKERS = (
    "invalid uid/gid",
    "not found",
    "unknown id",
    "usage:",
    "permission denied",
)
