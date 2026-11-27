"""让 Windows server 的自带测试在非 Windows 上也能跑。

`test_win_server.py` 在 import 期拉起整个 win server，依赖 `pywinauto` / `pyautogui` 等
OS 包。非 Windows 环境用 `platforms/tests/_win_stubs.py` 装最小桩——真 Windows 上这些包
本来就在，`load_win_server()` 会直接用真实的（它只在缺包时装桩）。

限制：验的是接线与判定逻辑；Windows 的 OS 行为仍需真机（见验收文档的覆盖矩阵）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parents[3] / "tests"     # platforms/tests
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

try:
    from _win_stubs import install_windows_stubs  # noqa: E402
except Exception:  # pragma: no cover
    install_windows_stubs = None

if install_windows_stubs is not None:
    install_windows_stubs()
