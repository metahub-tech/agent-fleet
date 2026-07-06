"""win/mac DPI 纯函数单测(惰性 import, 平台无关, 本机可跑; 非 CI)。"""
import platform
import sys
from pathlib import Path

# win_input 在 platforms/windows/server, 无重依赖、Linux 可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "windows" / "server"))
import win_input


def test_dpi_to_scale_common_ratios():
    assert win_input._dpi_to_scale(96) == 1.0
    assert win_input._dpi_to_scale(120) == 1.25
    assert win_input._dpi_to_scale(144) == 1.5
    assert win_input._dpi_to_scale(192) == 2.0


def test_dpi_to_scale_bad_input_defaults_to_1():
    assert win_input._dpi_to_scale(0) == 1.0
    assert win_input._dpi_to_scale(-5) == 1.0
    assert win_input._dpi_to_scale(None) == 1.0


def test_ensure_dpi_awareness_returns_bool_and_false_off_windows():
    r = win_input._ensure_dpi_awareness()
    assert isinstance(r, bool)
    if platform.system() != "Windows":
        assert r is False  # 无 ctypes.windll → 三级全失败 → 优雅 False


def test_dpi_awareness_report_text():
    assert win_input.dpi_awareness_report(True) is None
    msg = win_input.dpi_awareness_report(False)
    assert msg and "漂移" in msg


def test_read_scale_factor_fallback_off_windows():
    # 无 windll → 优雅降级 1.0, 不抛
    assert win_input.read_scale_factor() == 1.0


# --- mac ---
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "macos" / "server"))
import mac_dpi


def test_mac_read_scale_factor_fallback_off_mac():
    # 无 AppKit(非 mac) → 优雅降级 1.0, 不抛
    assert mac_dpi.read_scale_factor() == 1.0
