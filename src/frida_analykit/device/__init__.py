from .constants import DEFAULT_DEVICE_TEST_APP_ID
from .defaults import (
    DEFAULT_AGENT_SOURCE,
    DEFAULT_DEVICE_FRIDA_VERSION,
    DEFAULT_REMOTE_HOST,
    DEFAULT_REMOTE_SERVERNAME,
)
from .helpers import DeviceHelpers
from .models import (
    ConnectedAndroidDevice,
    DeviceAppResolutionError,
    DeviceSelectionError,
    DeviceWorkspace,
)
from .runtime import DeviceServerRuntime, is_transient_device_failure, should_retry_device_operation
from .selection import (
    DeviceTestLock,
    derive_remote_host,
    list_connected_android_devices,
    resolve_device_serial,
    resolve_device_serials,
    safe_device_serial_token,
)

_TEST_APP_EXPORTS = {
    "build_device_test_app",
    "get_device_test_app_apk_path",
    "get_device_test_app_gradlew_path",
    "get_device_test_app_project_dir",
    "install_device_test_app_all",
    "install_device_test_app_only",
    "install_device_test_app",
    "resolve_test_app_install_serials",
}

__all__ = [
    "ConnectedAndroidDevice",
    "DEFAULT_AGENT_SOURCE",
    "DEFAULT_DEVICE_FRIDA_VERSION",
    "DEFAULT_DEVICE_TEST_APP_ID",
    "DEFAULT_REMOTE_HOST",
    "DEFAULT_REMOTE_SERVERNAME",
    "DeviceAppResolutionError",
    "DeviceHelpers",
    "DeviceSelectionError",
    "DeviceServerRuntime",
    "DeviceTestLock",
    "DeviceWorkspace",
    "build_device_test_app",
    "derive_remote_host",
    "get_device_test_app_apk_path",
    "get_device_test_app_gradlew_path",
    "get_device_test_app_project_dir",
    "install_device_test_app_all",
    "install_device_test_app_only",
    "install_device_test_app",
    "is_transient_device_failure",
    "list_connected_android_devices",
    "resolve_test_app_install_serials",
    "resolve_device_serial",
    "resolve_device_serials",
    "safe_device_serial_token",
    "should_retry_device_operation",
]


def __getattr__(name: str):
    if name in _TEST_APP_EXPORTS:
        from . import test_app as _test_app

        return getattr(_test_app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
