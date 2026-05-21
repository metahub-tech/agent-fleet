from fleet.wizard import build_install_context, render_install_summary
from fleet.types import OSInfo, ServerRole


def test_build_install_context_macos():
    osi = OSInfo(system="Darwin", version="22", arch="x86_64", is_apple_silicon=False)
    ctx = build_install_context(repo_root="/tmp/repo", os_info=osi, dry_run=False,
                                 network="tailscale", tailscale_hostname="mac-test")
    assert ctx.repo_root == "/tmp/repo"
    assert ctx.tailscale_hostname == "mac-test"
    assert ctx.dry_run is False
    assert ctx.platform_options == {}


def test_build_install_context_platform_options():
    osi = OSInfo(system="Linux", version="6.1", arch="x86_64", is_apple_silicon=False)
    ctx = build_install_context(repo_root="/tmp/repo", os_info=osi, dry_run=False,
                                 network="lan", tailscale_hostname=None,
                                 platform_options={"ATB_ANDROID_MODE": "wireless"})
    assert ctx.platform_options == {"ATB_ANDROID_MODE": "wireless"}


def test_render_install_summary():
    roles = [
        ServerRole(role_id="mac-device", display_name="macOS desktop", hostname="mac-test", port=8767),
        ServerRole(role_id="android-device", display_name="Android bridge", hostname="mac-test", port=8768),
    ]
    out = render_install_summary(tailscale_hostname="mac-test", deployed_roles=roles)
    assert "mac-test" in out
    assert "http://mac-test:8767/mcp" in out
    assert "http://mac-test:8768/mcp" in out
