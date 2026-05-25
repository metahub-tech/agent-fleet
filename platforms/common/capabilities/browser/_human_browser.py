"""human_browser — self-built capability: act as the HUMAN in their real browser
(design §9.3, Phase 2b).

Launches the host's REAL daily Chrome with **no debug port and no automation
flags** → zero automation traces (navigator.webdriver stays false, no CDP to
probe, OS input is genuinely trusted). Page interaction is done with CORE tools
(take_screenshot + tap(x,y) + type_text) — web content is not in the OS a11y
tree, so this path is screenshot + coordinates, by design. Use it when acting as
the human on real accounts/identity; for testing/automation use agent_browser.

Self-built (origin=self-built) — this is the moat (OS-level real control), not a
graft. It exposes one launcher tool; everything else is core + the skill.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .._base import CapabilityModule, ORIGIN_SELF_BUILT

_MAC_CHROME_APP = "/Applications/Google Chrome.app"
_WIN_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _chrome_path() -> str | None:
    if sys.platform == "darwin":
        return _MAC_CHROME_APP if Path(_MAC_CHROME_APP).exists() else None
    if os.name == "nt":
        for p in _WIN_CHROME_PATHS:
            if Path(p).exists():
                return p
        return shutil.which("chrome")
    return shutil.which("google-chrome") or shutil.which("google-chrome-stable")


def _gui_session_ok() -> tuple[bool, str]:
    """Headed real Chrome needs a logged-in desktop session."""
    if sys.platform == "darwin":
        try:
            user = subprocess.run(
                ["stat", "-f%Su", "/dev/console"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if user and user not in ("root", "_windowserver"):
                return True, ""
            return False, "无活动 GUI 会话(/dev/console 未登录真实用户)"
        except Exception:
            return True, ""  # probe failed — don't block
    return True, ""  # win/linux: best-effort


class HumanBrowserCapability(CapabilityModule):
    id = "human_browser"
    display_name = "浏览器 human_browser(零自动化痕迹,作为人本人)"
    origin = ORIGIN_SELF_BUILT
    skill = "using-human-browser"
    platforms = None  # any host with a real Chrome + GUI session
    usage_hint = (
        "作为人本人操作真实账号/配置时用:human_browser_open(url) 启真人日常 Chrome"
        "(无 debug 端口、零自动化痕迹)→ 再用 core 的 take_screenshot 看页面、tap(x,y)/type_text "
        "操作(网页内容不在无障碍树,走截图+坐标)。仅自有设备/授权账号/正当用途。"
    )

    def __init__(self):
        self.description = (
            "自建:启动宿主真实日常 Chrome(无 debug 端口、无自动化标志 → 零自动化痕迹),"
            "通过截图 + OS 级坐标点击/输入(core 工具)作为人本人操作真实账号/身份。"
        )

    def availability(self) -> tuple[bool, str]:
        if _chrome_path() is None:
            return False, "Google Chrome 未安装"
        return _gui_session_ok()

    def register(self, mcp) -> list[str]:
        @mcp.tool
        def human_browser_open(url: str = "") -> dict:
            """启动/聚焦宿主真实日常 Chrome(**无 debug 端口、无自动化标志 → 零自动化痕迹**),
            可选打开 url。之后用 core 的 take_screenshot 看页面、tap(x,y)/type_text 作为人本人操作
            (网页内容不在 OS 无障碍树 → 走截图+坐标)。用于作为人本人操作真实账号/身份;
            仅限自有设备 / 自有或授权账号 / 正当用途。"""
            chrome = _chrome_path()
            if chrome is None:
                return {"ok": False, "error": "Google Chrome 未安装"}
            url = url.strip()  # expects a standard (encoded) URL, not a path with spaces
            try:
                if sys.platform == "darwin":
                    args = ["open", "-a", "Google Chrome"] + ([url] if url else [])
                    subprocess.run(args, timeout=15, check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    args = [chrome] + ([url] if url else [])
                    subprocess.Popen(args, start_new_session=True,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {
                    "ok": True,
                    "opened": url or "(chrome)",
                    "note": "真实 Chrome 已启动(无自动化痕迹);用 take_screenshot 看页面、tap/type_text 操作。",
                }
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        return ["human_browser_open"]
