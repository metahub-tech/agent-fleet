from fleet.installers import INSTALLER_REGISTRY, filter_for_os
from fleet.types import OSInfo


def test_registry_has_all_installers():
    role_ids = {(i.__class__.__name__, i.role_id) for i in INSTALLER_REGISTRY}
    expected = {
        ("MacosDesktop", "macbox-gui"),
        ("MacosAndroidBridge", "android-gui"),
        ("WindowsTestPC", "winpc-gui"),
        ("WindowsAndroidBridge", "android-gui"),
        ("LinuxAndroidBridge", "android-gui"),
    }
    assert expected.issubset(role_ids)


def test_filter_for_macos():
    macs = filter_for_os(OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False))
    role_ids = {i.role_id for i in macs}
    assert "macbox-gui" in role_ids
    assert "android-gui" in role_ids
    assert "winpc-gui" not in role_ids


def test_filter_for_windows():
    wins = filter_for_os(OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False))
    role_ids = {i.role_id for i in wins}
    assert "winpc-gui" in role_ids
    assert "android-gui" in role_ids
    assert "macbox-gui" not in role_ids


def test_filter_for_linux():
    lins = filter_for_os(OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False))
    role_ids = {i.role_id for i in lins}
    assert role_ids == {"android-gui"}
