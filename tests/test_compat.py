from frida_analykit.compat import FridaCompat, SupportRange, Version


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
    compat = FridaCompat(
        _FakeFrida(),
        support_range=SupportRange(
            min_inclusive=Version.parse("16.5.9"),
            max_exclusive=Version.parse("18.0.0"),
        ),
    )

    report = compat.doctor_report()

    assert report["supported"] is True
    assert report["support_status"] == "tested"
    assert report["support_range"] == ">=16.5.9, <18.0.0"
    assert report["matched_profile"] == "current-17"
    assert report["tested_version"] == "17.8.2"


def test_doctor_marks_supported_but_untested_versions() -> None:
    class _UntestedFrida(_FakeFrida):
        __version__ = "17.8.1"

    compat = FridaCompat(
        _UntestedFrida(),
        support_range=SupportRange(
            min_inclusive=Version.parse("16.5.9"),
            max_exclusive=Version.parse("18.0.0"),
        ),
    )

    report = compat.doctor_report()

    assert report["supported"] is True
    assert report["support_status"] == "supported but untested"
    assert report["matched_profile"] == "current-17"
    assert report["tested_version"] == "17.8.2"


def test_doctor_marks_unsupported_versions() -> None:
    class _UnsupportedFrida(_FakeFrida):
        __version__ = "18.0.0"

    compat = FridaCompat(
        _UnsupportedFrida(),
        support_range=SupportRange(
            min_inclusive=Version.parse("16.5.9"),
            max_exclusive=Version.parse("18.0.0"),
        ),
    )

    report = compat.doctor_report()

    assert report["supported"] is False
    assert report["support_status"] == "unsupported"
    assert report["matched_profile"] is None
    assert report["tested_version"] is None


def test_device_resolution_supports_special_hosts() -> None:
    compat = FridaCompat(
        _FakeFrida(),
        support_range=SupportRange(
            min_inclusive=Version.parse("16.5.9"),
            max_exclusive=Version.parse("18.0.0"),
        ),
    )

    assert compat.get_device("local")[0] == "local"
    assert compat.get_device("usb")[0] == "usb"
    assert compat.get_device("127.0.0.1:27042") == ("remote", "127.0.0.1:27042")
