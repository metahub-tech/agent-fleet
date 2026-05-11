from fleet.installers import INSTALLER_REGISTRY, filter_for_os
from fleet.types import OSInfo


def test_registry_has_all_installers():
    role_ids = {(i.__class__.__name__, i.role_id) for i in INSTALLER_REGISTRY}
    expected = {
        ("MacosDesktop", "mac-device"),
        ("MacosAndroidBridge", "android-device"),
        ("WindowsDesktop", "win-device"),
        ("WindowsAndroidBridge", "android-device"),
        ("LinuxAndroidBridge", "android-device"),
    }
    assert expected.issubset(role_ids)


def test_filter_for_macos():
    macs = filter_for_os(OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False))
    role_ids = {i.role_id for i in macs}
    assert "mac-device" in role_ids
    assert "android-device" in role_ids
    assert "win-device" not in role_ids


def test_filter_for_windows():
    wins = filter_for_os(OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False))
    role_ids = {i.role_id for i in wins}
    assert "win-device" in role_ids
    assert "android-device" in role_ids
    assert "mac-device" not in role_ids


def test_filter_for_linux():
    lins = filter_for_os(OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False))
    role_ids = {i.role_id for i in lins}
    assert role_ids == {"android-device"}
