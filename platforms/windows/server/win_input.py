"""Windows 输入/DPI 辅助(AgentHub #100 P1-A/P2)。

- `_ensure_dpi_awareness()`: 让本进程 per-monitor DPI aware, 消除 take_screenshot(物理像素)
  与 tap/get_screen_size(默认逻辑像素)在 DPI 缩放≠100% 机器上的坐标系错位。
- `_send_unicode(text)`: 逐字符用 KEYEVENTF_UNICODE 注入 Unicode 码点, 绕过 VK 键码 →
  中文输入法(搜狗等)不再把 `/` 改写成 `、`(真机实证 pyautogui.typewrite 的 VK 方案被劫持)。

ctypes.windll 仅在函数内惰性引用 → 本模块可在非 Windows 上导入(供纯函数单测)。
"""
from __future__ import annotations


def _utf16_units(text: str) -> "list[int]":
    """把字符串拆成 UTF-16 码元序列(BMP 直接; 非 BMP 拆 surrogate pair)。
    KEYEVENTF_UNICODE 一次发一个 16-bit 码元, 故 emoji 等需两个。纯函数、可测。"""
    units = []
    for ch in text:
        code = ord(ch)
        if code <= 0xFFFF:
            units.append(code)
        else:
            c = code - 0x10000
            units.append(0xD800 + (c >> 10))
            units.append(0xDC00 + (c & 0x3FF))
    return units


def _ensure_dpi_awareness() -> bool:
    """进程设为 per-monitor DPI aware(幂等、失败不抛)。返回是否设置成功(仅供日志/测试)。
    设为 aware 后 ImageGrab、pyautogui.size()、SetCursorPos 三者统一到物理像素、自洽。"""
    try:
        import ctypes
    except Exception:
        return False
    # PER_MONITOR_AWARE_V2 = DPI_AWARENESS_CONTEXT (HANDLE)-4 (Win10 1703+)
    try:
        f = ctypes.windll.user32.SetProcessDpiAwarenessContext
        f.restype = ctypes.c_bool
        f.argtypes = [ctypes.c_void_p]
        if f(ctypes.c_void_p(-4)):
            return True
    except Exception:
        pass
    try:  # 退化: PROCESS_PER_MONITOR_DPI_AWARE = 2 (Win8.1+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        pass
    try:  # 最后退化: 系统级 aware (Vista+)
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


def _send_unicode(text: str, interval: float = 0.0) -> None:
    """逐字符用 KEYEVENTF_UNICODE 直接注入 Unicode 码点(绕开键盘布局与 IME)。Windows only。

    注意: INPUT 的 union 必须能容纳最大成员 MOUSEINPUT, 且 cbSize 传【完整 INPUT 大小】
    (64 位 40 字节)——只放 KEYBDINPUT 会让 sizeof 偏小、cbSize 不符, SendInput 静默失败
    (真机实证: 少了 mi 成员时一个字符都发不出去)。"""
    import ctypes
    import time
    from ctypes import wintypes

    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    INPUT_KEYBOARD = 1
    ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]  # mi 让 union 达到正确大小

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    def _mk(scan, flags):
        inp = _INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki = _KEYBDINPUT(0, scan, flags, 0, None)
        return inp

    send = ctypes.windll.user32.SendInput
    size = ctypes.sizeof(_INPUT)
    for unit in _utf16_units(text):
        arr = (_INPUT * 2)(_mk(unit, KEYEVENTF_UNICODE),
                           _mk(unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        send(2, ctypes.byref(arr), size)
        if interval:
            time.sleep(interval)


def maximize_chrome_window_for_udd(udd: str, timeout: float = 8.0) -> bool:
    """确定性把某 profile(--user-data-dir=udd)的 Chrome 浏览器窗口 Win32 ShowWindow(SW_MAXIMIZE)
    强制最大化(不模拟键盘快捷键)。—— `--start-maximized` 会被 Chrome 的 per-profile 窗口尺寸恢复
    机制覆盖(真机实证公众平台窗口被恢复成 945x1012 半屏, AgentHub #100 轮12), 故 open 后由 server
    按 profile 定位窗口强制最大化。best-effort, 失败/超时返回 False, 永不抛。Windows only。

    定位法: 找 cmdline 含 `--user-data-dir=<udd>` 的 chrome 进程 pid → EnumWindows 取归这些 pid 的
    可见、有标题、类名 Chrome_WidgetWin_1 的顶层窗口(浏览器主窗口) → ShowWindow(SW_MAXIMIZE)。
    """
    try:
        import ctypes
        import time
        from ctypes import wintypes
        import psutil
    except Exception:
        return False

    SW_MAXIMIZE = 3
    user32 = ctypes.windll.user32
    needle = f"--user-data-dir={udd}"

    def _chrome_pids():
        pids = set()
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                nm = (p.info.get("name") or "").lower()
                if "chrome" in nm and needle in " ".join(p.info.get("cmdline") or []):
                    pids.add(p.pid)
            except Exception:
                pass
        return pids

    def _windows_for(pids):
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _lp):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in pids:
                    return True
                if user32.GetWindowTextLengthW(hwnd) <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, buf, 64)
                if buf.value == "Chrome_WidgetWin_1":   # 浏览器主窗口类
                    r = wintypes.RECT()
                    # 过滤 Chrome 的小工具窗口(如某些 298x101 弹层): 只认够大的真浏览器窗口
                    if user32.GetWindowRect(hwnd, ctypes.byref(r)) and \
                            (r.right - r.left) >= 400 and (r.bottom - r.top) >= 300:
                        found.append(hwnd)
            except Exception:
                pass
            return True

        user32.EnumWindows(_cb, 0)
        return found

    end = time.time() + timeout
    hwnds = []
    while time.time() < end:
        pids = _chrome_pids()
        if pids:
            hwnds = _windows_for(pids)
            if hwnds:
                break
        time.sleep(0.3)
    if not hwnds:
        return False
    ok = False
    for h in hwnds:
        try:
            user32.ShowWindow(h, SW_MAXIMIZE)
            ok = True
        except Exception:
            pass
    return ok


def _dpi_to_scale(dpi) -> float:
    """DPI(96=100%) → 显示缩放倍率。dpi 非正/None 视为读取失败 → 1.0。纯函数、可测。"""
    if not dpi or dpi <= 0:
        return 1.0
    return round(dpi / 96.0, 4)


def read_scale_factor() -> float:
    """主屏 OS 显示缩放(1.0/1.25/1.5…)。读不到降级 1.0, 绝不抛。
    仅供自检/诚实上报, 【绝不进 tap 坐标运算】——awareness 生效时截图↔tap 比值恒 1.0,
    与本值(OS 显示缩放)无关(spec §4.3 红线)。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        shcore = ctypes.windll.shcore
        hmon = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)  # MONITOR_DEFAULTTOPRIMARY
        dx, dy = ctypes.c_uint(), ctypes.c_uint()
        # MDT_EFFECTIVE_DPI=0; 成功返回 S_OK(0)
        if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
            return _dpi_to_scale(dx.value)
    except Exception:
        pass
    return 1.0


def dpi_awareness_report(aware: bool):
    """awareness 失败时的 stderr 告警文案(成功→None)。纯函数、可测。"""
    if aware:
        return None
    return ("[dpi] per-monitor DPI awareness 设置失败; 缩放≠100% 屏上截图与 tap 坐标将错位、"
            "视觉点击漂移。请确认 Win10 1703+ 且进程有权限。")
