"""`_cf_html` 单测：字节偏移、头长度、片段提取与 READBACK 判据（任何平台可跑）。

这些正是手工实现 CF_HTML 最容易错的点：中文按字符算偏移、头长度变化后偏移错位、
用"整份入参 vs 解码字符串"做等值比较（必然假红）。
"""
from _cf_html import (
    END_MARKER,
    START_MARKER,
    build_cf_html,
    extract_fragment,
    header_bytes,
    header_length,
    parse_header,
    payload_size,
    readback_ok,
)


def test_header_length_is_105_without_source_url():
    # 13 + 22 + 20 + 26 + 24 = 105；StartHTML 等于头长度
    assert header_length() == 105
    data = build_cf_html("<p>hi</p>")
    assert parse_header(data)["StartHTML"] == 105
    assert header_bytes(data) == 105


def test_offsets_point_at_the_right_bytes():
    fragment = "<h2>标题</h2><p>正文</p>"
    data = build_cf_html(fragment)
    parsed = parse_header(data)
    assert data[parsed["StartFragment"]:parsed["StartFragment"] + len(START_MARKER.encode())] == START_MARKER.encode()
    assert data[parsed["EndFragment"]:parsed["EndFragment"] + len(END_MARKER.encode())] == END_MARKER.encode()
    assert parsed["EndHTML"] == len(data)
    assert parsed["StartHTML"] < parsed["StartFragment"] < parsed["EndFragment"] < parsed["EndHTML"]


def test_offsets_are_byte_based_not_char_based_for_cjk():
    fragment = "中文标题正文" * 20
    data = build_cf_html(fragment)
    parsed = parse_header(data)
    # 若按字符算，StartFragment 会明显偏小
    assert parsed["StartFragment"] > len(data[:parsed["StartFragment"]].decode("utf-8")) - 1
    extracted = extract_fragment(data)
    assert extracted == fragment


def test_roundtrip_extract():
    fragment = '<h2 style="border-left:4px">买了 AI 工具</h2><p>正文 &amp; 符号</p>'
    assert extract_fragment(build_cf_html(fragment)) == fragment


def test_source_url_changes_header_length_and_offsets_stay_valid():
    data = build_cf_html("<p>x</p>", source_url="https://mp.weixin.qq.com/x")
    parsed = parse_header(data)
    assert parsed["StartHTML"] == header_length("https://mp.weixin.qq.com/x")
    assert parsed["StartHTML"] > 105
    assert data[parsed["StartFragment"]:parsed["StartFragment"] + len(START_MARKER.encode())] == START_MARKER.encode()
    assert extract_fragment(data) == "<p>x</p>"


def test_header_uses_crlf_and_padded_offsets():
    data = build_cf_html("<p>hi</p>")
    head = data[:105].decode("utf-8")
    assert head.startswith("Version:0.9\r\n")
    assert "\r\nStartHTML:0000000105\r\n" in head
    assert head.endswith("\r\n")


def test_payload_size_matches_bytes():
    data = build_cf_html("<p>hi</p>")
    assert payload_size(data) == len(data)


# --- READBACK 判据 ---------------------------------------------------------

def test_readback_exact_bytes():
    data = build_cf_html("<p>hi</p>")
    ok, how = readback_ok(data, data)
    assert ok is True and how == "bytes_equal"


def test_readback_fragment_equal_when_only_decoded(monkeypatch):
    data = build_cf_html("<p>中文</p>")
    # 模拟"读回只拿到解码后的字符串再编码"：头可能被改写，但片段一致
    different_header = data.replace(b"Version:0.9", b"Version:0.9", 1)
    ok, how = readback_ok(data, different_header)
    assert ok is True


def test_readback_detects_lost_cjk():
    written = build_cf_html("<p>中文内容</p>")
    read_back = build_cf_html("<p>??</p>")     # 片段里 CJK 丢了
    ok, how = readback_ok(written, read_back)
    assert ok is False and how == "cjk_lost"


def test_readback_detects_missing_markers():
    ok, how = readback_ok(build_cf_html("<p>hi</p>"), b"plain text only")
    assert ok is False and how == "markers_missing"


def test_readback_invariants_when_only_markers_survive():
    written = build_cf_html("<p>中文</p>")
    # 有标记、CJK 也在，但片段被改过 → 落到不变量兜底（保守通过）
    read_back = build_cf_html("<p>中文</p>").replace(b"\xe4\xb8\xad", b"\xe4\xb8\xad", 1)
    ok, how = readback_ok(written, read_back)
    assert ok is True


def test_empty_fragment_still_parses():
    data = build_cf_html("")
    parsed = parse_header(data)
    # StartFragment 指向标记本身 ⇒ 空片段时两个偏移正好差一个 StartFragment 标记
    assert parsed["EndFragment"] - parsed["StartFragment"] == len(START_MARKER.encode())
    assert extract_fragment(data) == ""
