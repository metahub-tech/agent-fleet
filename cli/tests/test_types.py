from fleet.types import OSInfo, ServerRole, VerifyResult, InstallContext, InstallEvent, GuidanceStep, GuidanceVariant


def test_os_info_basic():
    o = OSInfo(system="Darwin", version="12.7.6", arch="x86_64", is_apple_silicon=False)
    assert o.kind == "macos"


def test_os_info_kind_windows():
    o = OSInfo(system="Windows", version="11", arch="AMD64", is_apple_silicon=False)
    assert o.kind == "windows"


def test_os_info_kind_linux():
    o = OSInfo(system="Linux", version="6.5", arch="x86_64", is_apple_silicon=False)
    assert o.kind == "linux"


def test_server_role_url():
    r = ServerRole(role_id="mac-device", display_name="macOS desktop", hostname="mac-test", port=8767)
    assert r.url == "http://mac-test:8767/mcp"


def test_verify_result_default():
    v = VerifyResult(ok=True, tool_count=31)
    assert v.ok and v.tool_count == 31
    assert v.error is None


def test_guidance_step_default_only():
    s = GuidanceStep(title="Open dev options", default_description="long-press version 7×")
    assert s.title == "Open dev options"
    assert s.variants == {}
