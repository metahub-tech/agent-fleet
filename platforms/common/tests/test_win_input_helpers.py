"""P1-A/P2(AgentHub #100) win 输入/DPI 纯函数单测。win 主文件在 platforms/windows,
这里只测可跨平台导入的纯逻辑(UTF-16 拆分)。真机行为(SendInput/DPI)靠 test-win11 验。"""
import sys
from pathlib import Path
WIN = Path(__file__).resolve().parent.parent.parent / "windows" / "server"
sys.path.insert(0, str(WIN))


def test_utf16_units_bmp():
    from win_input import _utf16_units
    assert _utf16_units("/") == [0x2F]
    assert _utf16_units("A中") == [0x41, 0x4E2D]


def test_utf16_units_surrogate_pair():
    from win_input import _utf16_units
    # 😀 U+1F600 → surrogate pair D83D DE00
    assert _utf16_units("😀") == [0xD83D, 0xDE00]


def test_utf16_units_slashes_not_altered():
    from win_input import _utf16_units
    # `//` 就是两个 0x2F, 不被改写(IME 劫持在 VK 层, 我们发 unicode 码点绕过)
    assert _utf16_units("//") == [0x2F, 0x2F]
