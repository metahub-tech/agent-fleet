from fleet.installers.windows import WindowsTestPC, WindowsAndroidBridge
from fleet.types import OSInfo, InstallContext


def test_windows_metadata():
    assert WindowsTestPC().role_id == "win-device"
    assert WindowsTestPC().port == 8766
    assert WindowsAndroidBridge().role_id == "android-device"
    assert WindowsAndroidBridge().port == 8768


def test_windows_supported_only_on_windows():
    osw = OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False)
    osm = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
    assert WindowsTestPC().is_supported_on(osw)
    assert not WindowsTestPC().is_supported_on(osm)
    assert WindowsAndroidBridge().is_supported_on(osw)


def test_dry_run_skips_subprocess():
    osw = OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False)
    ctx = InstallContext(repo_root="C:\\repo", os_info=osw, dry_run=True)
    events = list(WindowsTestPC().install(ctx))
    assert any("DRY RUN" in e.message for e in events)


def test_windows_desktop_role_id_is_win_device():
    from fleet.installers.windows import WindowsDesktop
    assert WindowsDesktop.role_id == "win-device"


def test_windows_android_bridge_role_id_is_android_device():
    from fleet.installers.windows import WindowsAndroidBridge
    assert WindowsAndroidBridge.role_id == "android-device"
