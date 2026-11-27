"""Win32 剪贴板「HTML Format」写入 / 读回 —— 策略层与 ctypes 后端分离。

为什么要拆开：这段代码真正会出事的地方不是 API 名字，而是**句柄所有权**与**失败路径**：

* ``SetClipboardData`` **成功后**内存已交给系统，再 ``GlobalFree`` 会破坏剪贴板
  （甚至崩别的进程）；**失败时**所有权没转移，必须自己 ``GlobalFree``，否则每次
  ``clipboard_busy`` 漏一块；
* ``CloseClipboard`` 只能在 ``OpenClipboard`` **成功**后调用，否则会把别人窗口上的
  剪贴板所有权关掉；
* 重试必须是**整轮重来**（重新 Open / Alloc / 写），不能拿上一轮失败留下的句柄再 Set。

把"什么时候 free / 什么时候 close / 重试几轮"做成可注入的纯策略
（``set_clipboard_html(payload, api=FakeApi())``），就能在 Linux 上把上面三条全部断言出来；
真正碰 Win32 的只有 :class:`ClipboardApi`。
"""
from __future__ import annotations

import ctypes
import sys
import time
from typing import Any, Optional

from _cf_html import CLIPBOARD_FORMAT

GMEM_MOVEABLE = 0x0002
_CF_UNICODETEXT = 13
_CF_TEXT = 1
_CF_HDROP = 15

# 这些是 Windows 内置格式（EnumClipboardFormats 返回数字 id 而不是名字）。
_BUILTIN_FORMATS = {
    _CF_TEXT: "CF_TEXT",
    _CF_UNICODETEXT: "CF_UNICODETEXT",
    _CF_HDROP: "CF_HDROP",
}


class ClipboardApi:
    """薄薄一层 ctypes。只在 Windows 上可实例化；测试用假实现替换。"""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Win32 clipboard is only available on Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)   # type: ignore[attr-defined]
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        u, k = self.user32, self.kernel32
        u.OpenClipboard.argtypes = [ctypes.c_void_p]
        u.OpenClipboard.restype = ctypes.c_bool
        u.EmptyClipboard.restype = ctypes.c_bool
        u.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
        u.RegisterClipboardFormatW.restype = ctypes.c_uint
        u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        u.SetClipboardData.restype = ctypes.c_void_p
        u.GetClipboardData.argtypes = [ctypes.c_uint]
        u.GetClipboardData.restype = ctypes.c_void_p
        u.CloseClipboard.restype = ctypes.c_bool
        u.EnumClipboardFormats.argtypes = [ctypes.c_uint]
        u.EnumClipboardFormats.restype = ctypes.c_uint
        u.GetClipboardFormatNameW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_int]
        u.GetClipboardFormatNameW.restype = ctypes.c_int
        k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        k.GlobalAlloc.restype = ctypes.c_void_p
        k.GlobalLock.argtypes = [ctypes.c_void_p]
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        k.GlobalUnlock.restype = ctypes.c_bool
        k.GlobalFree.argtypes = [ctypes.c_void_p]
        k.GlobalFree.restype = ctypes.c_void_p
        k.GlobalSize.argtypes = [ctypes.c_void_p]
        k.GlobalSize.restype = ctypes.c_size_t

    # -- lifecycle ---------------------------------------------------------
    def open_clipboard(self) -> bool:
        return bool(self.user32.OpenClipboard(None))

    def close_clipboard(self) -> None:
        self.user32.CloseClipboard()

    def empty_clipboard(self) -> bool:
        return bool(self.user32.EmptyClipboard())

    def last_error(self) -> int:
        # 必须 use_last_error=True + 立刻读：任何后续调用都会覆盖 GetLastError
        return int(ctypes.get_last_error())

    # -- registered format -------------------------------------------------
    def register_format(self, name: str) -> int:
        return int(self.user32.RegisterClipboardFormatW(name))

    def format_names(self) -> list[str]:
        names: list[str] = []
        fmt = 0
        while True:
            fmt = int(self.user32.EnumClipboardFormats(fmt))
            if fmt == 0:
                break
            if fmt in _BUILTIN_FORMATS:
                names.append(_BUILTIN_FORMATS[fmt])
                continue
            buf = ctypes.create_unicode_buffer(256)
            n = int(self.user32.GetClipboardFormatNameW(fmt, buf, 256))
            names.append(buf.value if n > 0 else f"#{fmt}")
        return names

    # -- memory ------------------------------------------------------------
    def global_alloc(self, size: int) -> int:
        return int(self.kernel32.GlobalAlloc(GMEM_MOVEABLE, size) or 0)

    def global_lock(self, handle: int) -> int:
        return int(self.kernel32.GlobalLock(handle) or 0)

    def global_unlock(self, handle: int) -> None:
        self.kernel32.GlobalUnlock(handle)

    def global_free(self, handle: int) -> None:
        self.kernel32.GlobalFree(handle)

    def global_size(self, handle: int) -> int:
        return int(self.kernel32.GlobalSize(handle))

    def write_memory(self, ptr: int, data: bytes) -> None:
        ctypes.memmove(ptr, data, len(data))

    def read_memory(self, ptr: int, size: int) -> bytes:
        return ctypes.string_at(ptr, size)

    def set_clipboard_data(self, fmt: int, handle: int) -> bool:
        return bool(self.user32.SetClipboardData(fmt, handle))

    def get_clipboard_data(self, fmt: int) -> int:
        return int(self.user32.GetClipboardData(fmt) or 0)


# ---------------------------------------------------------------------------
# 策略层（可注入 api，Linux 可测）
# ---------------------------------------------------------------------------

def _classify(api: Any, exc_reason: str, kind: str) -> str:
    """内部把"这一步失败"归成调用方能分支的 reason。"""
    if kind == "open":
        return "clipboard_busy"
    if kind == "alloc":
        return "clipboard_alloc_failed"
    if kind == "lock":
        return "clipboard_lock_failed"
    return "clipboard_write_failed"


def set_clipboard_html(
    payload: bytes,
    attempts: int = 1,
    retry_delay_s: float = 0.1,
    api: Optional[Any] = None,
) -> dict:
    """把 CF_HTML 字节写进剪贴板，只注册 ``HTML Format`` 一种格式。

    返回 ``{ok, attempts, value_bytes, formats?}`` 或 ``{ok: False, reason, attempts,
    attempts_detail}``。``reason``：``clipboard_busy``（被别的进程占着）/
    ``clipboard_alloc_failed`` / ``clipboard_lock_failed`` / ``clipboard_write_failed``
    / ``format_not_registered``。
    """
    total = max(1, int(attempts))
    backend = api if api is not None else ClipboardApi()
    fmt = int(backend.register_format(CLIPBOARD_FORMAT))
    if not fmt:
        return {"ok": False, "reason": "format_not_registered", "attempts": 0,
                "attempts_detail": []}

    detail: list[dict] = []
    last_reason = "clipboard_write_failed"
    for attempt in range(1, total + 1):
        started = time.monotonic()
        opened = False
        handle = 0
        transferred = False
        fail_kind = ""
        try:
            if not backend.open_clipboard():
                fail_kind = "open"
                last_reason = _classify(backend, "clipboard_busy", "open")
                detail.append({"n": attempt, "reason": last_reason,
                               "winerror": backend.last_error(),
                               "t_ms": int((time.monotonic() - started) * 1000)})
                continue

            opened = True
            if not backend.empty_clipboard():
                fail_kind = "write"
                last_reason = "clipboard_write_failed"
                detail.append({"n": attempt, "reason": last_reason,
                               "winerror": backend.last_error(),
                               "t_ms": int((time.monotonic() - started) * 1000)})
                continue

            handle = int(backend.global_alloc(len(payload)))
            if not handle:
                fail_kind = "alloc"
                last_reason = _classify(backend, "", "alloc")
                detail.append({"n": attempt, "reason": last_reason,
                               "winerror": backend.last_error(),
                               "t_ms": int((time.monotonic() - started) * 1000)})
                continue

            ptr = int(backend.global_lock(handle))
            if not ptr:
                fail_kind = "lock"
                last_reason = _classify(backend, "", "lock")
                detail.append({"n": attempt, "reason": last_reason,
                               "winerror": backend.last_error(),
                               "t_ms": int((time.monotonic() - started) * 1000)})
                continue

            backend.write_memory(ptr, payload)
            backend.global_unlock(handle)

            if not backend.set_clipboard_data(fmt, handle):
                fail_kind = "write"
                last_reason = "clipboard_write_failed"
                detail.append({"n": attempt, "reason": last_reason,
                               "winerror": backend.last_error(),
                               "t_ms": int((time.monotonic() - started) * 1000)})
                continue

            # 成功：所有权已交给系统，绝不能 free
            transferred = True
            return {"ok": True, "attempts": attempt, "value_bytes": len(payload),
                    "attempts_detail": detail}
        finally:
            # 失败路径：Set 没成功 ⇒ 句柄仍是我们的，必须 free（每次失败一块，高频重试会漏）
            if handle and not transferred:
                backend.global_free(handle)
            # 只有 Open 成功才 Close：否则会关掉别人窗口上的剪贴板所有权
            if opened:
                backend.close_clipboard()
        # 走到这里说明本轮失败；sleep 后整轮重来（不持锁、不复用句柄）
        if attempt < total:
            time.sleep(max(0.0, float(retry_delay_s)))

    return {"ok": False, "reason": last_reason, "attempts": total,
            "attempts_detail": detail}


def read_clipboard_html(api: Optional[Any] = None) -> dict:
    """读回剪贴板里的 HTML Format 字节与当前格式清单。

    返回 ``{ok, data, formats}``；读不到时 ``reason`` ∈ ``clipboard_busy`` /
    ``no_html_format``。**不** ``GlobalFree`` 读到的句柄（那是系统的）。
    """
    backend = api if api is not None else ClipboardApi()
    fmt = int(backend.register_format(CLIPBOARD_FORMAT))
    opened = False
    try:
        if not backend.open_clipboard():
            return {"ok": False, "reason": "clipboard_busy", "formats": []}
        opened = True
        formats = list(backend.format_names())
        handle = int(backend.get_clipboard_data(fmt)) if fmt else 0
        if not handle:
            return {"ok": False, "reason": "no_html_format", "formats": formats}
        size = int(backend.global_size(handle))
        ptr = int(backend.global_lock(handle))
        if not ptr:
            return {"ok": False, "reason": "clipboard_lock_failed", "formats": formats}
        try:
            data = backend.read_memory(ptr, size)
        finally:
            backend.global_unlock(handle)
        return {"ok": True, "data": data, "formats": formats}
    finally:
        if opened:
            backend.close_clipboard()
