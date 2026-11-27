"""用桩模块把 **macOS server** 在 Linux 上导入，真跑它的判定逻辑。

`mac_device_mcp.py` 模块级 import `pyautogui` / `pyperclip` / `psutil`（pyobjc 是**惰性**
import，只有真调用 AX/AppKit 时才触发），所以只需要最小桩就能在 Linux 上 import。

限制：桩不做任何真实操作；本模块提供的测试只验证**判定逻辑与接线**
（`*_gone` / `timeout` vs `probe_failed` / 批量白名单 / AX 预算包装），
mac 真机行为仍未验证（诚实记录在验收文档里）。
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

REPO = pathlib.Path(__file__).resolve().parents[2]
MAC_SERVER = REPO / "platforms" / "macos" / "server"


def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def install_mac_stubs() -> None:
    if "pyautogui" not in sys.modules:
        silent = lambda *a, **k: None  # noqa: E731
        _module(
            "pyautogui",
            FAILSAFE=True, PAUSE=0.0,
            size=lambda: (1440, 900), moveTo=silent, click=silent, mouseDown=silent,
            mouseUp=silent, position=lambda: (0, 0), typewrite=silent, hotkey=silent,
            keyDown=silent, keyUp=silent, press=silent, scroll=silent,
            screenshot=silent, dragTo=silent,
        )
    if "pyperclip" not in sys.modules:
        _module("pyperclip", paste=lambda: "", copy=lambda text: None)


def load_mac_server(name: str = "mac_device_mcp_under_test"):
    if name in sys.modules:
        return sys.modules[name]
    install_mac_stubs()
    for path in (str(REPO / "platforms" / "common"), str(MAC_SERVER), str(REPO / "platforms")):
        if path not in sys.path:
            sys.path.insert(0, path)

    import shutil as _shutil

    real_which = _shutil.which
    hidden = {"npx", "node", "chrome", "google-chrome", "chromium"}

    def _which(cmd, *a, **k):
        if str(cmd).split("/")[-1] in hidden:
            return None
        return real_which(cmd, *a, **k)

    spec = importlib.util.spec_from_file_location(name, MAC_SERVER / "mac_device_mcp.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    _shutil.which = _which
    try:
        spec.loader.exec_module(module)
    finally:
        _shutil.which = real_which
    return module
