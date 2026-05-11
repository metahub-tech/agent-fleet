from fleet.installers.linux import LinuxAndroidBridge
from fleet.types import OSInfo, InstallContext


def test_linux_android_metadata():
    m = LinuxAndroidBridge()
    assert m.role_id == "android-gui"
    assert m.port == 8768


def test_linux_supported_only_on_linux():
    m = LinuxAndroidBridge()
    osl = OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False)
    osm = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
    assert m.is_supported_on(osl)
    assert not m.is_supported_on(osm)


def test_dry_run_skips_subprocess():
    osl = OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False)
    ctx = InstallContext(repo_root="/tmp/repo", os_info=osl, dry_run=True)
    events = list(LinuxAndroidBridge().install(ctx))
    assert any("DRY RUN" in e.message for e in events)
