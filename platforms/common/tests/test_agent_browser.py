"""Tests for agent_browser method-A helpers (_resolve_profile, _make_wrapper).

Dependency-free: profile normalization is pure path logic; wrapper schema is
checked via inspect.signature (no fastmcp needed; handler is never called here).
Route + lease + real client behavior are validated on a live device server."""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capabilities.browser._agent_browser import _make_wrapper, _resolve_profile  # noqa: E402


def test_resolve_isolated():
    udd, pdir, key = _resolve_profile("isolated")
    assert udd.endswith("agent-browser-profile")
    assert pdir is None
    assert key == udd


def test_resolve_blank_defaults_isolated():
    assert _resolve_profile("")[0].endswith("agent-browser-profile")
    assert _resolve_profile("  ")[0].endswith("agent-browser-profile")


def test_resolve_path():
    udd, pdir, key = _resolve_profile("/tmp/myprof")
    assert pdir is None
    assert key == udd
    assert Path(udd).is_absolute()


def test_resolve_dir_at_profile_name():
    udd, pdir, key = _resolve_profile("/tmp/ud@Profile 1")
    assert pdir == "Profile 1"
    assert key == udd + "::Profile 1"
    assert udd.endswith("ud") or udd.endswith("ud/") or "ud" in udd


def test_make_wrapper_injects_profile_holder_and_keeps_params():
    w = _make_wrapper("browser_navigate", "Navigate", {"url": {"type": "string"}}, ["url"])
    sig = inspect.signature(w)
    assert list(sig.parameters) == ["profile", "holder", "url"]
    assert sig.parameters["profile"].default == "isolated"
    assert sig.parameters["holder"].default == "agent"
    assert sig.parameters["url"].default is inspect.Parameter.empty  # required stays required
    assert w.__name__ == "browser_navigate"


def test_make_wrapper_optional_param_gets_default():
    w = _make_wrapper("browser_type",
                      "Type", {"ref": {"type": "string"}, "text": {"type": "string"},
                               "submit": {"type": "boolean"}}, ["ref", "text"])
    sig = inspect.signature(w)
    assert sig.parameters["ref"].default is inspect.Parameter.empty
    assert sig.parameters["text"].default is inspect.Parameter.empty
    assert sig.parameters["submit"].default is None  # optional


def test_make_wrapper_annotations_present():
    w = _make_wrapper("browser_navigate", "Navigate", {"url": {"type": "string"}}, ["url"])
    assert w.__annotations__["profile"] is str
    assert w.__annotations__["holder"] is str
    assert "url" in w.__annotations__
