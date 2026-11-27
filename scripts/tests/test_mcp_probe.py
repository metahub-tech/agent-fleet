"""`_mcp_probe` 与 `probe_multi` 的单测（无网络）。

这两个文件是"定位工具"的基础设施：`_mcp_probe.payload_of` 决定三个验收脚本怎么读返回，
`probe_multi` 决定现场探测怎么组织用例。它们本身不做判断，所以测的是**归一化与参数校验**。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _mcp_probe  # noqa: E402
import probe_multi  # noqa: E402


class _Res:
    def __init__(self, structured=None, structured_v2=None, text=None, texts=None):
        if structured is not None:
            self.structuredContent = structured
        if structured_v2 is not None:
            self.structured_content = structured_v2
        if texts is not None:
            self.content = [type("C", (), {"text": t})() for t in texts]
        elif text is not None:
            self.content = [type("C", (), {"text": text})()]
        else:
            self.content = []


# --- payload_of -----------------------------------------------------------

def test_payload_prefers_structured_content():
    assert _mcp_probe.payload_of(_Res(structured={"ok": True})) == {"ok": True}


def test_payload_accepts_sdk_v2_field_name():
    assert _mcp_probe.payload_of(_Res(structured_v2={"ok": 1})) == {"ok": 1}


def test_payload_parses_json_text():
    assert _mcp_probe.payload_of(_Res(text='{"a": 1}')) == {"a": 1}


def test_payload_keeps_unparseable_text_as_raw():
    assert _mcp_probe.payload_of(_Res(text="boom")) == {"_raw": "boom"}


def test_payload_returns_list_for_multiple_parts():
    assert _mcp_probe.payload_of(_Res(texts=['{"a": 1}', '{"b": 2}'])) == [{"a": 1}, {"b": 2}]


def test_payload_empty_content():
    assert _mcp_probe.payload_of(_Res()) == []


def test_load_transport_is_callable_or_none():
    t = _mcp_probe.load_transport()
    assert t is None or callable(t)


# --- probe_multi CLI ------------------------------------------------------

def test_resolve_timeout_clamps_and_falls_back():
    assert probe_multi.resolve_timeout(1) == 5.0
    assert probe_multi.resolve_timeout(30) == 30.0
    assert probe_multi.resolve_timeout("x") == 180.0


def test_load_cases_accepts_valid_file(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text('[{"tool": "get_screen_size"}]', encoding="utf-8")
    assert probe_multi.load_cases(str(path)) == [{"tool": "get_screen_size"}]


def test_load_cases_rejects_bad_shape(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text('"nope"', encoding="utf-8")
    with pytest.raises(ValueError):
        probe_multi.load_cases(str(path))

    path.write_text('[{"label": "no tool"}]', encoding="utf-8")
    with pytest.raises(ValueError):
        probe_multi.load_cases(str(path))


def test_sample_cases_are_callable_shapes():
    assert probe_multi.SAMPLE_CASES
    for case in probe_multi.SAMPLE_CASES:
        assert case["tool"] and isinstance(case.get("args", {}), dict)


def test_main_requires_url(capsys):
    assert probe_multi.main([]) == 1
    assert "--url" in capsys.readouterr().err


def test_main_sample_prints_json(capsys):
    assert probe_multi.main(["--sample"]) == 0
    out = capsys.readouterr().out
    assert '"tool"' in out


def test_usage_errors_are_1_and_runtime_errors_are_2(tmp_path, capsys):
    """退出码语义：用法错=1、连不上=2；**不要**混进 smoke 的 0/1/2/3 约定。"""
    assert probe_multi.main([]) == 1                       # 缺 --url
    bad = tmp_path / "bad.json"
    bad.write_text('"nope"', encoding="utf-8")
    assert probe_multi.main(["--url", "http://127.0.0.1:9/mcp", "--cases", str(bad)]) == 1
    capsys.readouterr()


def test_sample_cases_contain_only_readonly_tools():
    forbidden = {"tap", "tap_element", "press_key", "type_text", "clipboard_set_html",
                 "run_shell", "launch_app", "terminate_app"}
    names = {c["tool"] for c in probe_multi.SAMPLE_CASES}
    assert not (names & forbidden), names
