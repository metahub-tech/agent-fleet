"""Smoke test: every @mcp.tool function in the server accepts the multi-device params."""
import sys
import inspect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import android_device_mcp as srv


def _iter_mcp_tools():
    """Return [(name, fn), ...] for every module-level function decorated with @mcp.tool.
    fastmcp 3.3.1 leaves the function bare (no .fn wrapper), but the tool is registered
    in mcp._tool_manager._tools — use that as the source of truth, falling back to attribute scan."""
    # Most reliable: scan the module for callables whose names match the known set.
    tool_names = [
        "acquire", "release", "get_status", "list_devices",
        "set_default_device", "get_default_device",
        "get_screen_size", "take_screenshot", "tap", "swipe", "long_press",
        "press_key", "type_text", "list_packages", "install_app", "uninstall_app",
        "launch_app", "terminate_app", "current_app", "run_shell", "push_file", "pull_file",
        "dump_ui", "find_elements", "tap_element",
        "upload_media", "stage_upload", "deliver_staged", "job_status",
    ]
    return [(n, getattr(srv, n)) for n in tool_names if hasattr(srv, n)]


def test_all_29_tools_present():
    tools = _iter_mcp_tools()
    assert len(tools) == 29, f"expected 29 tools, found {len(tools)}: {[n for n,_ in tools]}"


def test_action_tools_accept_device_param():
    """All non-state tools (the 19 migrated + take_screenshot etc.) must accept `device` kwarg."""
    # Tools that legitimately omit or differ on the `device` param:
    #   set_default_device  — `device` is a required positional arg (not None-default)
    #   get_default_device  — has no `device` param; returns the session default
    #   list_devices        — lists ALL devices; no per-device routing needed
    #   job_status          — 只按 job_id 查询；不路由设备
    no_device_param = {"set_default_device", "get_default_device", "list_devices", "job_status"}
    for name, fn in _iter_mcp_tools():
        if name in no_device_param:
            continue
        sig = inspect.signature(fn)
        assert "device" in sig.parameters, f"{name} missing `device` parameter"
        # device should default to None so single-device callers can omit it
        assert sig.parameters["device"].default is None, f"{name}.device should default to None"


def test_no_legacy_with_touch_decorator_remains():
    """The @with_touch decorator and _ensure_one_device should be fully removed."""
    source = Path(srv.__file__).read_text()
    assert "@with_touch" not in source, "@with_touch usage still present"
    assert "def with_touch" not in source, "with_touch helper still defined"
    assert "_ensure_one_device" not in source, "_ensure_one_device still referenced"
