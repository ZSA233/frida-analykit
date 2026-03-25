from frida_analykit.compat import FridaCompat


class _FakeDeviceManager:
    def __init__(self) -> None:
        self.remote_hosts = []

    def add_remote_device(self, host: str):
        self.remote_hosts.append(host)
        return ("remote", host)


class _FakeFrida:
    __version__ = "17.8.2"

    def __init__(self) -> None:
        self.device_manager = _FakeDeviceManager()

    def get_device_manager(self):
        return self.device_manager

    def get_local_device(self):
        return ("local", None)

    def get_usb_device(self):
        return ("usb", None)


def test_doctor_matches_current_profile() -> None:
    compat = FridaCompat(_FakeFrida())

    report = compat.doctor_report()

    assert report["supported"] is True
    assert report["matched_profile"] == "current-17"


def test_device_resolution_supports_special_hosts() -> None:
    compat = FridaCompat(_FakeFrida())

    assert compat.get_device("local")[0] == "local"
    assert compat.get_device("usb")[0] == "usb"
    assert compat.get_device("127.0.0.1:27042") == ("remote", "127.0.0.1:27042")
