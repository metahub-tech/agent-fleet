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
        """当前剪贴板上的格式名清单。

        `GetClipboardFormatNameW` 只用于"看得懂的名字"，**任何一步失败都不该让整个回读失败**
        —— 否则 `clipboard_set_html` 会一直返回 `readback_unavailable`，把"名字读不出"
        误诊成"剪贴板坏了"。失败时退回 `#<id>` 仍能表达"有哪些格式、是不是只有一个"。
        """
        names: list[str] = []
        fmt = 0
        while True:
            fmt = int(self.user32.EnumClipboardFormats(fmt))
            if fmt == 0:
                break
            if fmt in _BUILTIN_FORMATS:
                names.append(_BUILTIN_FORMATS[fmt])
                continue
            try:
                buf = ctypes.create_unicode_buffer(256)
                n = int(self.user32.GetClipboardFormatNameW(fmt, buf, 256))
                names.append(buf.value if n > 0 else f"#{fmt}")
            except Exception:
                names.append(f"#{fmt}")
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

#: 失败步骤 → 调用方能分支的 reason。
_REASON_BY_KIND = {
    "open": "clipboard_busy",
    "empty": "clipboard_write_failed",
    "alloc": "clipboard_alloc_failed",
    "lock": "clipboard_lock_failed",
    "set": "clipboard_write_failed",
}


def _attempt_once(backend: Any, fmt: int, payload: bytes) -> tuple[bool, str, int]:
    """跑**一轮**完整写入。返回 (ok, reason, winerror)。

    所有权规则都在 finally 里，且只在这一处：
    * ``SetClipboardData`` 成功 ⇒ 内存交给系统，**绝不** ``GlobalFree``；
    * 失败 ⇒ 句柄仍是我们的，必须 ``GlobalFree``（每轮泄漏一块，高频重试可观测）；
    * ``CloseClipboard`` 只在 ``OpenClipboard`` 成功后调用。
    ``last_error()`` 必须在失败调用之后、``CloseClipboard`` 之前读（close 会覆盖它）。
    """
    opened = False
    handle = 0
    transferred = False
    try:
        if not backend.open_clipboard():
            return False, _REASON_BY_KIND["open"], int(backend.last_error())

        opened = True
        if not backend.empty_clipboard():
            return False, _REASON_BY_KIND["empty"], int(backend.last_error())

        handle = int(backend.global_alloc(len(payload)))
        if not handle:
            return False, _REASON_BY_KIND["alloc"], int(backend.last_error())

        ptr = int(backend.global_lock(handle))
        if not ptr:
            return False, _REASON_BY_KIND["lock"], int(backend.last_error())

        try:
            backend.write_memory(ptr, payload)
        except Exception:
            # 写内存失败也要解锁再 free（锁着的句柄 GlobalFree 会失败 ⇒ 泄漏），
            # 并且转成结构化 reason，不把异常抛给调用方。
            return False, _REASON_BY_KIND["set"], int(backend.last_error())
        finally:
            backend.global_unlock(handle)

        if not backend.set_clipboard_data(fmt, handle):
            return False, _REASON_BY_KIND["set"], int(backend.last_error())

        transferred = True
        return True, "", 0
    finally:
        if handle and not transferred:
            backend.global_free(handle)
        if opened:
            backend.close_clipboard()


def set_clipboard_html(
    payload: bytes,
    attempts: int = 1,
    retry_delay_s: float = 0.1,
    api: Optional[Any] = None,
    sleep: Optional[Any] = None,
) -> dict:
    """把 CF_HTML 字节写进剪贴板，只注册 ``HTML Format`` 一种格式。

    重试是**整轮重来**：每轮重新 ``OpenClipboard``/``GlobalAlloc``/写/Set，**不复用**上一轮
    失败留下的句柄；两轮之间 ``sleep(retry_delay_s)`` —— 占用剪贴板的是别的进程，
    不间隔就重试等于空转。

    返回 ``{ok, attempts, value_bytes, attempts_detail}`` 或
    ``{ok: False, reason, attempts, attempts_detail}``。``reason``：
    ``clipboard_busy`` / ``clipboard_alloc_failed`` / ``clipboard_lock_failed`` /
    ``clipboard_write_failed`` / ``format_not_registered``。
    """
    total = max(1, int(attempts))
    backoff = sleep if sleep is not None else time.sleep
    backend = api if api is not None else ClipboardApi()
    fmt = int(backend.register_format(CLIPBOARD_FORMAT))
    if not fmt:
        return {"ok": False, "reason": "format_not_registered", "attempts": 0,
                "attempts_detail": []}

    detail: list[dict] = []
    last_reason = "clipboard_write_failed"
    for attempt in range(1, total + 1):
        started = time.monotonic()
        ok, reason, winerror = _attempt_once(backend, fmt, payload)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if ok:
            return {"ok": True, "attempts": attempt, "value_bytes": len(payload),
                    "attempts_detail": detail}
        last_reason = reason
        detail.append({"n": attempt, "reason": reason,
                       "winerror": winerror, "t_ms": elapsed_ms})
        if attempt < total:
            backoff(max(0.0, float(retry_delay_s)))

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
