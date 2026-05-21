"""Registry tests — all installers are now ManifestInstaller instances."""
from fleet.installers import INSTALLER_REGISTRY, filter_for_os, discover_installers
from fleet.installers._manifest_installer import ManifestInstaller
from fleet.types import OSInfo


def test_registry_has_all_role_os_pairs():
    """discover_installers() must produce exactly these 6 (role_id, host_os) pairs."""
    pairs = {(i.role_id, i._host_os) for i in INSTALLER_REGISTRY}
    expected = {
        ("android-device", "windows"),
        ("android-device", "macos"),
        ("android-device", "linux"),
        ("ios-device", "macos"),
        ("mac-device", "macos"),
        ("win-device", "windows"),
    }
    assert expected == pairs


def test_all_installers_are_manifest_installer():
    """After Task 3, every entry in the registry is a ManifestInstaller."""
    for inst in INSTALLER_REGISTRY:
        assert isinstance(inst, ManifestInstaller), (
            f"Expected ManifestInstaller, got {type(inst).__name__} for {inst.role_id}"
        )


def test_discover_installers_returns_same_set():
    """discover_installers() is idempotent — calling it again gives the same pairs."""
    fresh = discover_installers()
    fresh_pairs = {(i.role_id, i._host_os) for i in fresh}
    registry_pairs = {(i.role_id, i._host_os) for i in INSTALLER_REGISTRY}
    assert fresh_pairs == registry_pairs


def test_filter_for_macos():
    macs = filter_for_os(OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False))
    role_ids = {i.role_id for i in macs}
    assert "mac-device" in role_ids
    assert "android-device" in role_ids
    assert "ios-device" in role_ids
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
