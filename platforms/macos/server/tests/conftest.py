"""让 mac server 的自带测试在非 macOS 上也能跑。

`test_mac_server.py` 在 import 期会 `import mac_device_mcp`，而后者依赖 `pyautogui` 等
OS 包。非 mac 环境下用 `platforms/tests/_mac_stubs.py` 装最小桩——真 mac 上这些包本来就
存在，`install_mac_stubs()` 不会覆盖它们，因此不影响真实环境。

注意：这只能验"接线与判定逻辑"，mac 的 OS 行为仍需真机（见验收文档的覆盖矩阵）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parents[3] / "tests"     # platforms/tests
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

try:
    from _mac_stubs import install_mac_stubs  # noqa: E402
except Exception:  # pragma: no cover - 仓库结构被移动时的兜底
    install_mac_stubs = None

if install_mac_stubs is not None:
    install_mac_stubs()
