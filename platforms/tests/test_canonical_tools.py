import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # platforms/
from common import _canonical_tools as ct


def test_core_has_expected_tools():
    assert set(ct.CORE) == {
        "get_screen_size", "take_screenshot", "tap", "swipe", "type_text",
        "press_key", "dump_ui", "current_app", "terminate_app",
        "list_devices", "set_default_device", "get_default_device",
        "acquire", "release", "get_status",
    }


def test_param_specs_are_lists_of_str():
    for spec in {**ct.CORE, **ct.OPTIONAL}.values():
        assert isinstance(spec, list)
        assert all(isinstance(p, str) for p in spec)


def test_required_params_helper_strips_optional_marker():
    assert ct.required_params(["x", "y", "duration_ms?"]) == {"x", "y"}


def test_allowed_extra_contains_plumbing():
    assert {"device", "ctx"} <= ct.ALLOWED_EXTRA
