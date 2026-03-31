from __future__ import annotations

from .profiles import CompatProfile, load_profiles

__all__ = [
    "CompatProfile",
    "DeviceCompatProbeError",
    "DeviceCompatReporter",
    "DeviceCompatResult",
    "DeviceCompatSummary",
    "DeviceTestContext",
    "ManagedFridaEnvRef",
    "build_device_doctor_config",
    "estimate_compat_boundary",
    "format_device_compat_summary",
    "list_managed_frida_envs",
    "load_profiles",
    "resolve_device_compat_serials",
    "resolve_managed_python",
    "run_device_compat_scan",
    "sample_frida_versions",
]


def __getattr__(name: str):
    if name == "DeviceTestContext":
        from .device_testing import DeviceTestContext

        return DeviceTestContext

    if name in {
        "ManagedFridaEnvRef",
        "list_managed_frida_envs",
        "resolve_managed_python",
        "sample_frida_versions",
    }:
        from . import managed_envs as _managed_envs

        return getattr(_managed_envs, name)

    if name in {
        "DeviceCompatProbeError",
        "DeviceCompatReporter",
        "DeviceCompatResult",
        "DeviceCompatSummary",
        "build_device_doctor_config",
        "estimate_compat_boundary",
        "format_device_compat_summary",
        "resolve_device_compat_serials",
        "run_device_compat_scan",
    }:
        from . import device_compat as _device_compat

        return getattr(_device_compat, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
