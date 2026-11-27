"""用桩模块把 **Windows server** 在 Linux 上 import 起来，真跑它的纯逻辑接线。

为什么需要：`win_device_mcp.py` 在导入期就 import `pywinauto` / `pyautogui` / `pyperclip`
等 Windows-only 包，CI 的 Linux 上**导入即失败** —— 于是"`run_actions` 的白名单、
`wait_for` 的 kind 解析、能力注册"这些逻辑只能靠 AST 断言。

做法：把缺失的 Windows-only 模块替换成最小桩（只提供导入期会被访问的属性），
然后真实 import 被测 server。这样 `wait_for` / `run_actions` 的**行为**可以被真跑，
而 OS 调用那部分在测试里用 monkeypatch 换掉。

限制（写在前面，避免误读）：这不是"Windows 真机测试"。桩不做任何 OS 操作，
`Desktop`/`pyautogui` 全是假的 —— 它只证明**接线与判定逻辑**正确。
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

REPO = pathlib.Path(__file__).resolve().parents[2]
WIN_SERVER = REPO / "platforms" / "windows" / "server"


def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


class _FakeDesktop:
    """pywinauto.Desktop 的最小替身：调用即抛，确保"没被真的用到"。"""

    def __init__(self, *args, **kwargs):
        self.backend = kwargs.get("backend")

    def windows(self):
        return []

    def window(self, *args, **kwargs):
        raise RuntimeError("stub Desktop.window() called")


def install_windows_stubs() -> None:
    """安装/覆盖 Windows-only 依赖的桩模块（幂等）。"""
    if "pywinauto" not in sys.modules:
        _module("pywinauto", Desktop=_FakeDesktop)

    if "pyautogui" not in sys.modules:
        silent = lambda *a, **k: None  # noqa: E731
        _module(
            "pyautogui",
            FAILSAFE=True, PAUSE=0.0,
            size=lambda: (1920, 1080), moveTo=silent, click=silent, mouseDown=silent,
            mouseUp=silent, position=lambda: (0, 0), typewrite=silent, hotkey=silent,
            keyDown=silent, keyUp=silent, press=silent, scroll=silent,
            screenshot=silent, dragTo=silent,
        )

    if "pyperclip" not in sys.modules:
        _module("pyperclip", paste=lambda: "", copy=lambda text: None)

    if "psutil" not in sys.modules:
        _module("psutil", Process=lambda *a, **k: None,
                NoSuchProcess=type("NoSuchProcess", (Exception,), {}),
                AccessDenied=type("AccessDenied", (Exception,), {}),
                process_iter=lambda *a, **k: [])


def load_win_server(name: str = "win_device_mcp_under_test"):
    """导入 Windows server 并返回模块（共享同一个 sys.modules 实例）。"""
    if name in sys.modules:
        return sys.modules[name]
    install_windows_stubs()
    for path in (str(REPO / "platforms" / "common"), str(WIN_SERVER), str(REPO / "platforms")):
        if path not in sys.path:
            sys.path.insert(0, path)
    # 能力注册期会探测 npx/chrome：测试环境不应触发 `npx` 的联网安装，临时把它们藏起来。
    import shutil as _shutil

    real_which = _shutil.which
    hidden = {"npx", "node", "chrome", "google-chrome", "chromium"}

    def _which(cmd, *a, **k):
        if str(cmd).split("/")[-1].split("\\")[-1] in hidden:
            return None
        return real_which(cmd, *a, **k)

    spec = importlib.util.spec_from_file_location(name, WIN_SERVER / "win_device_mcp.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    _shutil.which = _which
    try:
        spec.loader.exec_module(module)
    finally:
        _shutil.which = real_which
    return module
