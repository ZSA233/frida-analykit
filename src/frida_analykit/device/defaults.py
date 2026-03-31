from typing import Final

DEFAULT_REMOTE_HOST: Final[str] = "127.0.0.1:27042"
DEFAULT_REMOTE_SERVERNAME: Final[str] = "/data/local/tmp/frida-server"
DEFAULT_DEVICE_FRIDA_VERSION: Final[str] = "16.6.6"
DEFAULT_AGENT_SOURCE: Final[str] = """
console.log("FRIDA_ANALYKIT_DEVICE_OK");
send({
  type: "PROGRESSING",
  data: {
    tag: "device",
    id: 1,
    step: 0,
    time: Date.now(),
    extra: { intro: "device-ok" },
    error: null
  }
});
"""
REMOTE_HOST_ADDRESS: Final[str] = "127.0.0.1"
REMOTE_PORT_BASE: Final[int] = 31100
REMOTE_PORT_COUNT: Final[int] = 800
DEVICE_RUNTIME_BOOT_MAX_ATTEMPTS: Final[int] = 2
DEVICE_READY_TIMEOUT: Final[int] = 120
DEVICE_READY_POLL_INTERVAL: Final[float] = 2.0
TRANSIENT_DEVICE_FAILURE_MARKERS: Final[tuple[str, ...]] = (
    "servernotrunningerror",
    "transporterror",
    "protocolerror",
    "timedouterror",
    "unable to connect to remote frida-server",
    "remote frida-server did not become ready",
    "server boot exited",
    "connection is closed",
    "connection reset",
    "unexpectedly timed out while waiting for signal",
    "timed out while waiting for the app to launch",
)
