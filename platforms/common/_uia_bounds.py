"""UIA 遍历的「不卡死 + 中文可读」纯逻辑（零第三方依赖，任何平台可单测）。

两个真机痛点（2026-11-27，device-operator 反馈 + 代码复核）：

1. **卡死**：UIA 遍历/属性读在某些窗口（Electron/Chromium、控制台、UI 线程繁忙）
   会阻塞到超时甚至永久挂住，把 MCP 请求线程拖死 —— 工具调用永不返回，
   上层只能靠客户端超时放弃，且服务端还留着一个卡住的线程。
2. **中文被拆成「一字一节点」**：Electron 类应用把一段文本报成每个 CJK 字符一个
   Text/Word 叶子。按 ``name`` 子串匹配「订阅」时，单个节点里只有「订」或「阅」，
   于是永远 ``not_found``；``dump_ui`` 的树也会被这些碎片撑爆。

本模块只放**纯函数**（不 import pywinauto/comtypes），Windows server 调用它们，
其余平台也能直接单测。真正的 UIA 调用留在各平台 server 里。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Iterable, Optional, Sequence

# UIA 里承载文本的 control_type（pywinauto 的 element_info.control_type 口径）。
# 大小写不敏感比较；只在这些类型上做「一字一节点」合并，避免把按钮/输入框拼在一起。
TEXT_LIKE_CONTROL_TYPES = frozenset({"text", "word", "static", "hyperlink"})

# 判定相邻的两个文本节点属于「同一行、同一段」的阈值。
DEFAULT_Y_OVERLAP = 0.6      # 垂直重叠 / 较矮者高度
DEFAULT_MAX_GAP_RATIO = 0.6  # 水平间隙 / 较矮者高度
DEFAULT_MAX_RUN_CHARS = 120  # 单个 run 合并后的字符上限，防止把整段吞成一个节点

# CJK 判定区间（含中文标点与全角字符），用于决定拼接时要不要补空格。
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x2E80, 0x2EFF),    # CJK Radicals Supplement
    (0x3000, 0x303F),    # CJK Symbols and Punctuation
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0xFE30, 0xFE4F),    # CJK Compatibility Forms
    (0xFF00, 0xFFEF),    # Halfwidth and Fullwidth Forms
    (0x20000, 0x2FA1F),  # CJK Extension B-F
)


class UiaTimeout(TimeoutError):
    """一次 UIA 调用超出了调用方给的预算。"""


def run_with_timeout(fn: Callable[[], Any], timeout_s: float, description: str = "uia") -> Any:
    """在 daemon 线程里跑 ``fn``，最多等 ``timeout_s`` 秒，超时抛 :class:`UiaTimeout`。

    为什么不用 ``ThreadPoolExecutor``：它的 ``shutdown(wait=True)`` 会等在卡住的
    工作线程上，把超时又变回阻塞。这里用一次性 daemon 线程 + Event，超时即刻返回；
    卡住的线程不会被杀（Python 没法杀），但它不会再拖住 MCP 请求线程，进程退出时
    也不会被它拦住。

    ``fn`` 自己抛的异常原样向上抛（保持调用方 try/except 语义）。
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def _target() -> None:
        try:
            box["value"] = fn()
            box["ok"] = True
        except BaseException as exc:  # noqa: BLE001 - 原样转交给调用线程
            box["error"] = exc
            box["ok"] = False
        finally:
            done.set()

    thread = threading.Thread(target=_target, name=f"uia-{description}", daemon=True)
    thread.start()
    if not done.wait(timeout_s):
        raise UiaTimeout(f"{description} did not return within {timeout_s:g}s")
    if not box.get("ok"):
        raise box.get("error") or RuntimeError(f"{description} failed")
    return box.get("value")


def is_cjk_char(ch: str) -> bool:
    """单个字符是否属于 CJK / 全角区（用码点判断，不依赖 locale）。"""
    if not ch:
        return False
    code = ord(ch[0])
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def has_cjk(text: str) -> bool:
    return any(is_cjk_char(ch) for ch in (text or ""))


def is_text_like(control_type: Optional[str]) -> bool:
    return (control_type or "").strip().lower() in TEXT_LIKE_CONTROL_TYPES


def as_rect(value: Any) -> Optional[tuple[int, int, int, int]]:
    """把 ``[l, t, r, b]`` / ``(l, t, r, b)`` 归一成 int 四元组；形状不对返回 None。"""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        left, top, right, bottom = (int(v) for v in value)
    except (TypeError, ValueError):
        return None
    if right < left or bottom < top:
        return None
    return left, top, right, bottom


def _height(rect: tuple[int, int, int, int]) -> int:
    return max(0, rect[3] - rect[1])


def _vertical_overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """两者垂直重叠长度 / 较矮者高度。不同高（字体大小不同）也能合理比较。"""
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    thinner = min(_height(a), _height(b))
    if thinner <= 0:
        return 1.0 if overlap >= 0 else 0.0
    return max(0.0, overlap / thinner)


def _same_container(a: dict, b: dict) -> bool:
    """粗粒度同容器判定：class_name / automation_id 都有值时必须一致。

    没有父节点信息可用（``element_info`` 不带 parent），这两个字段是最便宜且
    足够有效的替代：不同容器（如两个 Pane）的文本不应被拼成一段。
    """
    for key in ("class_name", "automation_id"):
        va = (a.get(key) or "").strip()
        vb = (b.get(key) or "").strip()
        if va and vb and va != vb:
            return False
    return True


def _join_separator(prev_name: str, next_name: str, gap: int, ref_height: int) -> str:
    """两个文本片段拼接时的分隔符。

    CJK 相邻直接相连（中文字间本无空格）；拉丁字母之间按「间隙是否明显大于
    字宽」决定补不补空格 —— 同一单词被拆开时 gap 接近 0，不该补。
    """
    if not prev_name or not next_name:
        return ""
    if is_cjk_char(prev_name[-1]) or is_cjk_char(next_name[0]):
        return ""
    if ref_height > 0 and gap > 0.25 * ref_height:
        return " "
    return ""


_AMBIGUOUS_NAME_HINTS = ("ambiguous",)
_AMBIGUOUS_MESSAGE_HINTS = ("match the criteria", "more than one")


def is_ambiguous_error(exc: BaseException) -> bool:
    """pywinauto 在"多个窗口同时匹配"时抛的异常，文案/类型都不同版本各异。

    真机实测（StarBeam 有两个窗口）：`find_elements(window_title="StarBeam")` 抛出裸异常
    ``There are 2 elements that match the criteria {...}``，调用方只能看到未结构化错误。
    这里只做**识别**，判定依据是类型名或文案里的稳定片段。
    """
    name = type(exc).__name__.lower()
    if any(hint in name for hint in _AMBIGUOUS_NAME_HINTS):
        return True
    message = str(exc).lower()
    return any(hint in message for hint in _AMBIGUOUS_MESSAGE_HINTS)


def ambiguous_window_payload(window_title: str, candidates: list[dict] | None = None) -> dict:
    """生成"窗口匹配不唯一"的结构化返回（reason 固定为 ``ambiguous_window``）。"""
    return {
        "ok": False,
        "reason": "ambiguous_window",
        "error": f"multiple windows match {window_title!r}",
        "hint": "pass a longer / more specific window_title to disambiguate",
        "candidates": list(candidates or [])[:10],
    }


def merge_text_runs(
    elements: Sequence[dict],
    *,
    max_run_chars: int = 1,
    y_overlap: float = DEFAULT_Y_OVERLAP,
    max_gap_ratio: float = DEFAULT_MAX_GAP_RATIO,
    max_merged_chars: int = DEFAULT_MAX_RUN_CHARS,
) -> list[dict]:
    """把「一字一节点」的文本叶子合并成可读、可点的文本 run。

    只合并同时满足以下条件的**短文本**节点（默认 ``len(name.strip()) <= 1``，
    即真正的逐字拆分，不误伤正常的两三字标签）：

    * ``control_type`` 属 :data:`TEXT_LIKE_CONTROL_TYPES`；
    * 同一行：垂直重叠比 >= ``y_overlap``；
    * 水平相邻：``next.left - prev.right <= max(2, max_gap_ratio * 高度)``；
    * 阅读顺序（``next.left >= prev.left``）且粗粒度同容器；
    * 合并后不超过 ``max_merged_chars``。

    返回**新列表**（不修改入参）。被合并的项带 ``merged=True`` / ``merged_from`` /
    ``parts``（每个原始片段的名字与矩形、以及在合并串里的字符偏移），
    供 :func:`text_run_span_rect` 精确算出「查询词落在这一段的哪一截」。
    """
    items = [dict(el) for el in elements]
    candidates: list[tuple[int, dict, tuple[int, int, int, int]]] = []
    for idx, el in enumerate(items):
        name = (el.get("name") or "").strip()
        rect = as_rect(el.get("rect"))
        if not name or rect is None:
            continue
        if len(name) > max_run_chars or not is_text_like(el.get("control_type")):
            continue
        candidates.append((idx, el, rect))

    if len(candidates) < 2:
        return items

    # 阅读顺序：先按上沿、再按左沿。允许同段落里轻微的高度差。
    candidates.sort(key=lambda c: (c[2][1], c[2][0]))

    consumed: set[int] = set()
    groups: dict[int, list[tuple[int, dict, tuple[int, int, int, int]]]] = {}
    current: list[tuple[int, dict, tuple[int, int, int, int]]] = []

    def _flush() -> None:
        if len(current) >= 2:
            groups[current[0][0]] = list(current)
            consumed.update(item[0] for item in current)
        current.clear()

    for cand in candidates:
        if not current:
            current.append(cand)
            continue
        _, last_el, last_rect = current[-1]
        _, cur_el, cur_rect = cand
        gap = cur_rect[0] - last_rect[2]
        tolerance = max(2, int(max_gap_ratio * min(_height(last_rect), _height(cur_rect)) or 0))
        ok = (
            _vertical_overlap_ratio(last_rect, cur_rect) >= y_overlap
            and gap <= tolerance
            and cur_rect[0] >= last_rect[0]
            and _same_container(last_el, cur_el)
            and sum(len((c[1].get("name") or "").strip()) for c in current)
            + len((cur_el.get("name") or "").strip()) <= max_merged_chars
        )
        if ok:
            current.append(cand)
        else:
            _flush()
            current.append(cand)
    _flush()

    if not groups:
        return items

    merged_output: list[dict] = []
    for idx, el in enumerate(items):
        if idx not in consumed:
            merged_output.append(el)
            continue
        if idx not in groups:
            continue  # 同组内非首项，由首项吐出
        group = groups[idx]
        merged_output.append(_build_run(group))
    # 合并后的中心/顺序按原列表位置不可靠，按 rect 重新做一次稳定的阅读序。
    merged_output.sort(key=_reading_order_key)
    return merged_output


def _reading_order_key(element: dict) -> tuple[int, int]:
    rect = as_rect(element.get("rect")) or (0, 0, 0, 0)
    return rect[1], rect[0]


def _build_run(group: list[tuple[int, dict, tuple[int, int, int, int]]]) -> dict:
    parts: list[dict] = []
    text = ""
    for _idx, el, rect in group:
        name = (el.get("name") or "").strip()
        if parts:
            prev_rect = parts[-1]["rect"]
            gap = rect[0] - prev_rect[2]
            ref_h = min(_height(as_rect(prev_rect) or (0, 0, 0, 0)), _height(rect))
            text += _join_separator(parts[-1]["name"], name, gap, ref_h)
        start = len(text)
        text += name
        parts.append({"name": name, "rect": list(rect), "start": start, "end": len(text)})

    left = min(p["rect"][0] for p in parts)
    top = min(p["rect"][1] for p in parts)
    right = max(p["rect"][2] for p in parts)
    bottom = max(p["rect"][3] for p in parts)
    merged = dict(group[0][1])
    merged.update(
        {
            "name": text,
            "rect": [left, top, right, bottom],
            "center": [(left + right) // 2, (top + bottom) // 2],
            "merged": True,
            "merged_from": len(parts),
            "parts": parts,
        }
    )
    return merged


def text_run_span_rect(element: dict, start: int, end: int) -> Optional[tuple[int, int, int, int]]:
    """合并 run 里字符区间 ``[start, end)`` 对应的矩形（按字符宽度比例切分边界片段）。

    用途：查询词只命中 run 的一部分时，点它**自己那一截**的中心，而不是整段的中心
    —— 否则「订阅」在「订阅已关注」里会被点到后半截。
    """
    parts = element.get("parts") or []
    if not parts or end <= start:
        return None
    boxes: list[tuple[int, int, int, int]] = []
    for part in parts:
        p_start = int(part.get("start") or 0)
        p_end = int(part.get("end") or 0)
        rect = as_rect(part.get("rect"))
        if rect is None or p_end <= p_start:
            continue
        lo, hi = max(start, p_start), min(end, p_end)
        if lo >= hi:
            continue
        char_count = p_end - p_start
        width = rect[2] - rect[0]
        x0 = rect[0] + int(round(width * (lo - p_start) / char_count))
        x1 = rect[0] + int(round(width * (hi - p_start) / char_count))
        boxes.append((x0, rect[1], max(x1, x0 + 1), rect[3]))
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def find_span(element: dict, query: str) -> Optional[tuple[int, int]]:
    """在合并 run 的名字里定位 ``query``（大小写不敏感），返回字符区间。"""
    text = element.get("name") or ""
    q = (query or "").strip()
    if not text or not q or not element.get("merged"):
        return None
    start = text.lower().find(q.lower())
    if start < 0:
        return None
    return start, start + len(q)


def rank_key(element: dict, field_order: Iterable[str] = ()) -> tuple:
    """候选排序键：**先排非合并项**，再 on_screen / exact / 字段优先级。

    合并项排后面是安全阀：同一句里两个不同标签被误拼时，直接命中的真实节点
    仍然优先被选中。
    """
    order = list(field_order) if field_order else []
    field = element.get("match_field") or ""
    try:
        field_rank = order.index(field)
    except ValueError:
        field_rank = len(order)
    return (
        1 if element.get("merged") else 0,
        0 if element.get("on_screen", True) else 1,
        0 if element.get("exact") else 1,
        field_rank,
    )


def center_of(rect_like: Any) -> Optional[list[int]]:
    rect = as_rect(rect_like)
    if rect is None:
        return None
    return [(rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2]
