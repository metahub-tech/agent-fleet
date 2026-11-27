"""CF_HTML（Windows "HTML Format" 剪贴板）载荷的构造与解析 —— **纯逻辑，零依赖**。

为什么单独抽出来：把 HTML 粘进公众号编辑器（富文本）时，只有 `HTML Format` 这一种
剪贴板格式能保住标题样式与段落间距；纯文本粘贴会把 `border-left`、段间距一起丢掉。
而 CF_HTML 最容易错的地方不是 ctypes，而是**偏移量**：

* 头里的 `StartHTML` / `EndHTML` / `StartFragment` / `EndFragment` 全部是
  **UTF-8 字节偏移**，不是字符数 —— 中文稿子按 ``len(str)`` 算必错；
* 头本身用固定宽度的数字占位，长度必须与最终头完全一致，否则所有偏移一起错位；
* 片段标记（`<!--StartFragment-->`）的位置决定读侧能不能切出内容。

所以把"算字节"这部分做成纯函数，任何平台都能单测；Windows 侧的 ctypes 写入/读回
（句柄生命周期、重试、READBACK）留在 server 里，只负责搬运这里算好的字节。
"""
from __future__ import annotations

import re
from typing import Optional

#: 剪贴板注册格式名（Windows `RegisterClipboardFormatW("HTML Format")`）。
CLIPBOARD_FORMAT = "HTML Format"

VERSION_LINE = "Version:0.9"
START_MARKER = "<!--StartFragment-->"
END_MARKER = "<!--EndFragment-->"

_HEADER_FIELDS = ("Version", "StartHTML", "EndHTML", "StartFragment", "EndFragment", "SourceURL")
_OFFSET_FIELDS = ("StartHTML", "EndHTML", "StartFragment", "EndFragment")


def _render_header(start_html: int, end_html: int, start_frag: int, end_frag: int,
                   source_url: str = "") -> str:
    """固定宽度（10 位补零）的头，保证占位头与实际头**字节数完全一致**。

    SourceURL 只在不为空时出现：它会改变头长度，而偏移量是相对整个头之后算的，
    所以必须"先把头定下来，再算偏移"（:func:`build_cf_html` 里就是这么做的）。
    """
    lines = [
        VERSION_LINE,
        f"StartHTML:{start_html:010d}",
        f"EndHTML:{end_html:010d}",
        f"StartFragment:{start_frag:010d}",
        f"EndFragment:{end_frag:010d}",
    ]
    if source_url:
        lines.append(f"SourceURL:{source_url}")
    return "\r\n".join(lines) + "\r\n"


def header_length(source_url: str = "") -> int:
    """占位头（全 0）的字节长度 —— 也就是 `StartHTML` 的固定值。

    不带 SourceURL 时是 **105**（13 + 22 + 20 + 26 + 24）；带 SourceURL 会变长，
    因此调用方不要硬编码 105，用本函数的返回值。
    """
    return len(_render_header(0, 0, 0, 0, source_url).encode("utf-8"))


def build_cf_html(fragment: str, source_url: str = "") -> bytes:
    """把一段 HTML 片段包成 CF_HTML 字节流（可直接塞进 `HTML Format` 剪贴板）。

    * `StartFragment` 指向 **`<!--StartFragment-->` 标记本身**（与 device-operator
      真机基线一致；Chromium 自己写的时候指向标记之后，读侧两种都能处理，
      这里不要"按 Chromium 源码修正"，否则两边来回改）；
    * `EndFragment` 指向 `<!--EndFragment-->` 标记起点，即"片段内容结束处"；
    * 所有偏移均为 UTF-8 **字节**偏移。
    """
    body = f"<html><body>{START_MARKER}{fragment}{END_MARKER}</body></html>"
    body_bytes = body.encode("utf-8")

    skeleton = _render_header(0, 0, 0, 0, source_url)
    start_html = len(skeleton.encode("utf-8"))

    start_index = body_bytes.find(START_MARKER.encode("utf-8"))
    end_index = body_bytes.find(END_MARKER.encode("utf-8"))
    if start_index < 0 or end_index < 0 or end_index < start_index:  # pragma: no cover - 构造保证
        raise ValueError("CF_HTML markers missing from generated body")

    header = _render_header(
        start_html=start_html,
        end_html=start_html + len(body_bytes),
        start_frag=start_html + start_index,
        end_frag=start_html + end_index,
        source_url=source_url,
    )
    header_bytes = header.encode("utf-8")
    # 头长度必须与占位头一致，否则偏移全错 —— 这是这类 bug 最常见的形态。
    assert len(header_bytes) == start_html, "CF_HTML header length changed after filling offsets"
    return header_bytes + body_bytes


def parse_header(data: bytes) -> dict:
    """解析 CF_HTML 的头（只认前 32 KiB，避免把正文当头扫）。"""
    head = data[:32768].decode("utf-8", "replace")
    out: dict[str, object] = {}
    for line in head.split("\r\n"):
        if not line:
            break
        match = re.match(r"^([A-Za-z]+):(.*)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if key not in _HEADER_FIELDS:
            continue
        if key in _OFFSET_FIELDS:
            try:
                out[key] = int(value)
            except ValueError:
                continue
        else:
            out[key] = value
    return out


def header_bytes(data: bytes) -> int:
    """头的实际字节长度（= StartHTML；缺失时退回占位长度）。"""
    parsed = parse_header(data)
    if isinstance(parsed.get("StartHTML"), int):
        return int(parsed["StartHTML"])
    return header_length(str(parsed.get("SourceURL") or ""))


def extract_fragment(data: bytes) -> Optional[str]:
    """从 CF_HTML 字节流里切出片段内容（标记之间），供 READBACK 用。

    这是**片段级**比较：入参是 `header + html` 的字节流，读回是解码后的字符串，
    直接比整份必然假红（长度天然不同）。切片段再比才是有意义的等价判断。
    """
    text = data.decode("utf-8", "replace")
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        return None
    return text[start + len(START_MARKER):end]


def readback_ok(written: bytes, read_back: bytes) -> tuple[bool, str]:
    """READBACK 判据：先精确（字节相等），再退化到片段相等，最后是不变量。

    绝不拿"整份入参 vs 解码后的字符串"做等值比较 —— 那是 100% 假红，然后被人把阈值
    调松，比不校验更坏。
    """
    if written == read_back:
        return True, "bytes_equal"
    written_fragment = extract_fragment(written)
    read_fragment = extract_fragment(read_back)
    if written_fragment is not None and read_fragment is not None:
        if written_fragment == read_fragment:
            return True, "fragment_equal"
    # 不变量兜底：两条流都带标记；写入含 CJK 时读回也含 CJK；无替换字符。
    if START_MARKER.encode() in read_back and END_MARKER.encode() in read_back:
        if written_fragment and any(ord(ch) > 0x2E7F for ch in written_fragment):
            if not any(ord(ch) > 0x2E7F for ch in (read_fragment or "")):
                return False, "cjk_lost"
        if "\ufffd" in (read_fragment or "") and "\ufffd" not in (written_fragment or ""):
            return False, "replacement_char"
        return True, "invariants_only"
    return False, "markers_missing"


def payload_size(data: bytes) -> int:
    """CF_HTML 载荷的字节数（超出剪贴板/调用方上限时用于报错，不做截断）。"""
    return len(data)
