"""`_uia_bounds` 纯函数单测（无 pywinauto 依赖，任何平台可跑）。

覆盖两类真机痛点：
1. Electron/Chromium 把中文拆成「一字一节点」→ 合并后能按词匹配、按词点击；
2. UIA 调用卡死 → `run_with_timeout` 让调用方按时返回，不拖死 MCP 请求线程。
"""
import threading
import time

import pytest

from _uia_bounds import (
    UiaTimeout,
    as_rect,
    find_span,
    has_cjk,
    is_cjk_char,
    is_text_like,
    merge_text_runs,
    rank_key,
    run_with_timeout,
    text_run_span_rect,
)


def _glyph(name, left, top=0, width=20, height=24, **extra):
    """构造一个「一字一节点」的文本叶子（Electron 典型形态）。"""
    element = {
        "name": name,
        "control_type": "Text",
        "class_name": "TextBlock",
        "automation_id": "",
        "rect": [left, top, left + width, top + height],
    }
    element.update(extra)
    return element


# --- 基础判定 ---------------------------------------------------------------

def test_cjk_detection():
    assert is_cjk_char("订") is True
    assert is_cjk_char("，") is True
    assert is_cjk_char("a") is False
    assert is_cjk_char("") is False
    assert has_cjk("公众号") is True
    assert has_cjk("wechat") is False


def test_text_like_and_rect_normalisation():
    assert is_text_like("Text") and is_text_like("word") and is_text_like("STATIC")
    assert not is_text_like("Button")
    assert not is_text_like(None)
    assert as_rect([1, 2, 3, 4]) == (1, 2, 3, 4)
    assert as_rect((1, 2, 3, 4)) == (1, 2, 3, 4)
    assert as_rect([1, 2, 3]) is None
    assert as_rect(["a", 2, 3, 4]) is None
    assert as_rect([10, 2, 5, 4]) is None  # right < left


# --- 合并：一字一节点 -------------------------------------------------------

def test_merges_adjacent_cjk_glyphs_into_one_run():
    elements = [_glyph("订", 100), _glyph("阅", 120), _glyph("已", 140), _glyph("关", 160), _glyph("注", 180)]
    merged = merge_text_runs(elements)
    assert len(merged) == 1
    run = merged[0]
    assert run["name"] == "订阅已关注"
    assert run["merged"] is True and run["merged_from"] == 5
    assert run["rect"] == [100, 0, 200, 24]
    assert run["center"] == [150, 12]
    # 每个原始片段都留了偏移，供按查询词切片点击
    assert [p["start"] for p in run["parts"]] == [0, 1, 2, 3, 4]


def test_two_char_labels_are_not_merged_by_default():
    # 默认只合并「一字一节点」；两个正常的两字标签不该被拼在一起
    elements = [_glyph("姓名", 100), _glyph("电话", 120)]
    merged = merge_text_runs(elements)
    assert len(merged) == 2
    assert all(not e.get("merged") for e in merged)


def test_two_char_labels_can_merge_when_configured():
    elements = [_glyph("姓", 100), _glyph("名", 120)]
    merged = merge_text_runs(elements, max_run_chars=2)
    assert len(merged) == 1 and merged[0]["name"] == "姓名"


def test_different_lines_do_not_merge():
    elements = [_glyph("订", 100, top=0), _glyph("阅", 120, top=60)]
    merged = merge_text_runs(elements)
    assert len(merged) == 2


def test_far_apart_nodes_do_not_merge():
    # 同一行但中间隔着 200px（明显不是一个词）
    elements = [_glyph("订", 100), _glyph("阅", 320)]
    merged = merge_text_runs(elements)
    assert len(merged) == 2


def test_non_text_control_types_are_not_merged():
    elements = [
        _glyph("订", 100, control_type="Button"),
        _glyph("阅", 120, control_type="Button"),
    ]
    merged = merge_text_runs(elements)
    assert len(merged) == 2


def test_different_containers_do_not_merge():
    elements = [
        _glyph("订", 100, class_name="TextBlockA"),
        _glyph("阅", 120, class_name="TextBlockB"),
    ]
    merged = merge_text_runs(elements)
    assert len(merged) == 2


def test_latin_words_join_with_space_only_when_gap_is_wide():
    # 同一单词被拆开：gap=0 → 直接拼，不能凭空插空格
    narrow = merge_text_runs([_glyph("Hel", 100), _glyph("lo", 120, width=18)], max_run_chars=3)
    assert len(narrow) == 1 and narrow[0]["name"] == "Hello"
    # 两个单词：gap=10（在容差内但明显大于字宽 1/4）→ 补一个空格
    spaced = merge_text_runs(
        [_glyph("Hello", 100, width=40), _glyph("World", 150, width=40)], max_run_chars=5
    )
    assert len(spaced) == 1 and spaced[0]["name"] == "Hello World"
    # 间隙超过 0.6*高度 → 不该合并
    wide = merge_text_runs([_glyph("Hel", 100), _glyph("lo", 240, width=18)], max_run_chars=3)
    assert len(wide) == 2


def test_merge_does_not_mutate_input():
    elements = [_glyph("订", 100), _glyph("阅", 120)]
    snapshot = [dict(e) for e in elements]
    merge_text_runs(elements)
    assert elements == snapshot


def test_merge_is_stable_reading_order():
    elements = [
        _glyph("注", 180, top=0),   # 故意乱序输入
        _glyph("订", 100, top=0),
        _glyph("阅", 120, top=0),
        _glyph("关", 160, top=0),
        _glyph("已", 140, top=0),
    ]
    merged = merge_text_runs(elements)
    assert [e["name"] for e in merged] == ["订阅已关注"]


# --- 按查询词切片点击 -------------------------------------------------------

def test_span_rect_targets_only_the_matched_chars():
    run = merge_text_runs([_glyph("订", 100), _glyph("阅", 120), _glyph("已", 140), _glyph("关", 160)])[0]
    assert run["name"] == "订阅已关"
    span = find_span(run, "订阅")
    assert span == (0, 2)
    rect = text_run_span_rect(run, *span)
    assert rect == (100, 0, 140, 24)
    # 整段中心是 140，只点「订阅」应该是 120 —— 这正是防误点的关键
    assert (rect[0] + rect[2]) // 2 == 120


def test_span_rect_handles_partial_boundary_part():
    run = merge_text_runs([_glyph("订", 100), _glyph("阅", 120), _glyph("已", 140)])[0]
    rect = text_run_span_rect(run, 1, 3)  # 「阅已」
    assert rect == (120, 0, 160, 24)


def test_find_span_requires_merged_element():
    plain = _glyph("订阅", 100)
    assert find_span(plain, "订阅") is None
    run = merge_text_runs([_glyph("订", 100), _glyph("阅", 120)])[0]
    assert find_span(run, "订阅") == (0, 2)
    assert find_span(run, "无关") is None
    assert find_span(run, "") is None


# --- 排序：合并项排在真实节点之后 -------------------------------------------

def test_rank_key_prefers_real_elements_over_merged_runs():
    field_order = ("name", "automation_id", "control_type", "class_name")
    merged = {"merged": True, "on_screen": True, "exact": True, "match_field": "name"}
    real = {"on_screen": True, "exact": False, "match_field": "name"}
    assert sorted([merged, real], key=lambda e: rank_key(e, field_order))[0] is real


def test_rank_key_orders_on_screen_then_exact_then_field():
    field_order = ("name", "automation_id")
    offscreen = {"on_screen": False, "exact": True, "match_field": "name"}
    inexact = {"on_screen": True, "exact": False, "match_field": "name"}
    exact = {"on_screen": True, "exact": True, "match_field": "automation_id"}
    order = sorted([offscreen, inexact, exact], key=lambda e: rank_key(e, field_order))
    assert order == [exact, inexact, offscreen]


# --- 超时闸门 ---------------------------------------------------------------

def test_run_with_timeout_returns_value():
    assert run_with_timeout(lambda: 42, 1.0) == 42


def test_run_with_timeout_propagates_exception():
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        run_with_timeout(boom, 1.0)


def test_run_with_timeout_raises_on_hang_within_budget():
    started = time.monotonic()
    with pytest.raises(UiaTimeout):
        run_with_timeout(lambda: time.sleep(5), 0.15, description="hang")
    elapsed = time.monotonic() - started
    # 立刻返回，不能等那个卡住的调用自己结束
    assert elapsed < 1.5


def test_run_with_timeout_uses_daemon_thread():
    before = threading.active_count()
    with pytest.raises(UiaTimeout):
        run_with_timeout(lambda: time.sleep(2), 0.05, description="daemon")
    # 超时后线程仍在睡，但必须是 daemon，不能拦住进程退出
    stuck = [t for t in threading.enumerate() if t.name == "uia-daemon"]
    assert stuck and all(t.daemon for t in stuck)
    assert threading.active_count() >= before
