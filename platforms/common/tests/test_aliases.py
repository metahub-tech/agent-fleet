"""Tests for _aliases module (T1 of v0.7.0 multi-device support)."""
import json
import sys
from pathlib import Path

import pytest

# Ensure the server directory is on path so _aliases can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

from _aliases import (
    DeviceInfo,
    assign_aliases,
    derive_alias,
    load_aliases,
    resolve_aliases,
    save_aliases,
)


# ---------------------------------------------------------------------------
# derive_alias
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("brand,model,expected", [
    ("google", "Pixel_7", "google-pixel-7"),
    ("samsung", "SM_S908U", "samsung-sm-s908u"),
    ("xiaomi", "Redmi Note 12", "xiaomi-redmi-note-12"),
    ("Xiaomi", "Redmi__Note  12", "xiaomi-redmi-note-12"),
    ("", "Pixel_7", None),
    ("google", None, None),
    (None, "Pixel_7", None),
    (None, None, None),
    ("google", "", None),
    # iOS ProductType commas — extended rule [_\s,.] unifies both platforms
    ("apple", "iPhone11,8", "apple-iphone11-8"),
    ("apple", "iPad13,16", "apple-ipad13-16"),
])
def test_derive_alias_slug_examples(brand, model, expected):
    assert derive_alias(brand, model) == expected


def test_derive_alias_leading_trailing_dash_stripped():
    # model starting/ending with underscore
    result = derive_alias("brand", "_Model_")
    assert not result.startswith("-")
    assert not result.endswith("-")


def test_derive_alias_collapsed_dashes():
    # multiple underscores and spaces should not produce double dashes
    result = derive_alias("brand", "A__B  C")
    assert "--" not in result


# ---------------------------------------------------------------------------
# assign_aliases
# ---------------------------------------------------------------------------

def test_assign_aliases_empty():
    assert assign_aliases([]) == {}


def test_assign_aliases_single_device_with_brand_model():
    devices = [DeviceInfo(serial="serial1", brand="google", model="Pixel_7")]
    result = assign_aliases(devices)
    assert result == {"serial1": "google-pixel-7"}


def test_assign_aliases_multiple_distinct_devices():
    devices = [
        DeviceInfo(serial="aaa", brand="google", model="Pixel_7"),
        DeviceInfo(serial="bbb", brand="samsung", model="SM_S908U"),
    ]
    result = assign_aliases(devices)
    assert result == {
        "aaa": "google-pixel-7",
        "bbb": "samsung-sm-s908u",
    }


def test_assign_aliases_same_base_dedup_three_devices():
    devices = [
        DeviceInfo(serial="C", brand="google", model="Pixel_7"),
        DeviceInfo(serial="A", brand="google", model="Pixel_7"),
        DeviceInfo(serial="B", brand="google", model="Pixel_7"),
    ]
    result = assign_aliases(devices)
    # Ascending serial order: A→1, B→2, C→3
    assert result == {
        "A": "google-pixel-7-1",
        "B": "google-pixel-7-2",
        "C": "google-pixel-7-3",
    }


def test_assign_aliases_all_fallback():
    devices = [
        DeviceInfo(serial="B", brand=None, model=None),
        DeviceInfo(serial="A", brand=None, model=None),
    ]
    result = assign_aliases(devices)
    # Ascending serial: A→phone-1, B→phone-2
    assert result == {"A": "phone-1", "B": "phone-2"}


def test_assign_aliases_mixed_real_and_fallback():
    devices = [
        DeviceInfo(serial="A", brand="google", model="Pixel_7"),
        DeviceInfo(serial="B", brand="google", model="Pixel_7"),
        DeviceInfo(serial="C", brand="samsung", model="SM_S22"),
        DeviceInfo(serial="D", brand=None, model=None),
    ]
    result = assign_aliases(devices)
    assert result == {
        "A": "google-pixel-7-1",
        "B": "google-pixel-7-2",
        "C": "samsung-sm-s22",
        "D": "phone-1",
    }


def test_assign_aliases_input_order_does_not_affect_output():
    devices_v1 = [
        DeviceInfo(serial="C", brand="google", model="Pixel_7"),
        DeviceInfo(serial="A", brand="google", model="Pixel_7"),
        DeviceInfo(serial="B", brand="google", model="Pixel_7"),
    ]
    devices_v2 = [
        DeviceInfo(serial="B", brand="google", model="Pixel_7"),
        DeviceInfo(serial="C", brand="google", model="Pixel_7"),
        DeviceInfo(serial="A", brand="google", model="Pixel_7"),
    ]
    assert assign_aliases(devices_v1) == assign_aliases(devices_v2)


def test_assign_aliases_singleton_no_suffix():
    devices = [DeviceInfo(serial="serial1", brand="google", model="Pixel_7")]
    result = assign_aliases(devices)
    assert result["serial1"] == "google-pixel-7"


def test_assign_aliases_multiple_fallback_ascending_serial():
    devices = [
        DeviceInfo(serial="ZZZ", brand=None, model=None),
        DeviceInfo(serial="AAA", brand=None, model=None),
    ]
    result = assign_aliases(devices)
    assert result == {"AAA": "phone-1", "ZZZ": "phone-2"}


# ---------------------------------------------------------------------------
# load_aliases
# ---------------------------------------------------------------------------

def test_load_aliases_missing_file(tmp_path):
    result = load_aliases(tmp_path / "nonexistent.json")
    assert result == {}


def test_load_aliases_empty_file(tmp_path):
    p = tmp_path / "aliases.json"
    p.write_text("")
    result = load_aliases(p)
    assert result == {}


def test_load_aliases_valid_json(tmp_path):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps({"serial1": "myphone", "serial2": "tablet"}))
    result = load_aliases(p)
    assert result == {"serial1": "myphone", "serial2": "tablet"}


def test_load_aliases_malformed_json_raises_value_error(tmp_path):
    p = tmp_path / "aliases.json"
    p.write_text("{not valid json")
    with pytest.raises(ValueError, match=str(p)):
        load_aliases(p)


def test_load_aliases_top_level_array_raises_value_error(tmp_path):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps(["a", "b"]))
    with pytest.raises(ValueError):
        load_aliases(p)


def test_load_aliases_non_string_value_raises_value_error(tmp_path):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps({"serial1": 123}))
    with pytest.raises(ValueError):
        load_aliases(p)


# ---------------------------------------------------------------------------
# save_aliases
# ---------------------------------------------------------------------------

def test_save_aliases_roundtrip(tmp_path):
    p = tmp_path / "aliases.json"
    data = {"serial1": "myphone", "serial2": "tablet"}
    save_aliases(p, data)
    loaded = load_aliases(p)
    assert loaded == data


def test_save_aliases_creates_parent_dirs(tmp_path):
    p = tmp_path / "deep" / "nested" / "aliases.json"
    save_aliases(p, {"s": "alias"})
    assert p.exists()


def test_save_aliases_no_tmp_file_left_behind(tmp_path):
    p = tmp_path / "aliases.json"
    save_aliases(p, {"s": "alias"})
    leftovers = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
    assert leftovers == []


def test_load_aliases_path_is_directory_returns_empty(tmp_path):
    # tmp_path is itself a directory; load_aliases should treat non-file paths as missing.
    assert load_aliases(tmp_path) == {}


def test_load_aliases_broken_symlink_returns_empty(tmp_path):
    target = tmp_path / "missing.json"
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    assert load_aliases(link) == {}


def test_save_aliases_pretty_printed(tmp_path):
    p = tmp_path / "aliases.json"
    save_aliases(p, {"b": "two", "a": "one"})
    content = p.read_text()
    # Should have indent (newlines + spaces)
    assert "\n" in content
    # Should have trailing newline
    assert content.endswith("\n")
    # Sorted keys: "a" before "b"
    assert content.index('"a"') < content.index('"b"')


# ---------------------------------------------------------------------------
# resolve_aliases
# ---------------------------------------------------------------------------

def test_resolve_aliases_override_wins():
    devices = [DeviceInfo(serial="serial1", brand="google", model="Pixel_7")]
    overrides = {"serial1": "myphone"}
    result = resolve_aliases(devices, overrides)
    assert result == {"serial1": "myphone"}


def test_resolve_aliases_renumbering_after_partial_override():
    # Worked example from spec:
    # devices = [A:google/Pixel_7, B:google/Pixel_7, C:google/Pixel_7]
    # overrides = {A: "myphone"}
    # → assign_aliases on [B, C] gives google-pixel-7-1, google-pixel-7-2
    # → final: {A: "myphone", B: "google-pixel-7-1", C: "google-pixel-7-2"}
    devices = [
        DeviceInfo(serial="A", brand="google", model="Pixel_7"),
        DeviceInfo(serial="B", brand="google", model="Pixel_7"),
        DeviceInfo(serial="C", brand="google", model="Pixel_7"),
    ]
    overrides = {"A": "myphone"}
    result = resolve_aliases(devices, overrides)
    assert result == {
        "A": "myphone",
        "B": "google-pixel-7-1",
        "C": "google-pixel-7-2",
    }


def test_resolve_aliases_unknown_serial_override_ignored():
    devices = [DeviceInfo(serial="serial1", brand="google", model="Pixel_7")]
    overrides = {"unknown_serial": "somephone"}
    result = resolve_aliases(devices, overrides)
    assert "unknown_serial" not in result
    assert result == {"serial1": "google-pixel-7"}


def test_resolve_aliases_empty_override_equals_assign_aliases():
    devices = [
        DeviceInfo(serial="A", brand="google", model="Pixel_7"),
        DeviceInfo(serial="B", brand="samsung", model="SM_S22"),
    ]
    result = resolve_aliases(devices, {})
    expected = assign_aliases(devices)
    assert result == expected


def test_resolve_aliases_empty_devices():
    result = resolve_aliases([], {"serial1": "myphone"})
    assert result == {}
