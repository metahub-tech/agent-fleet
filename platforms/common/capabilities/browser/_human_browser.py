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
from _browser_lease import _resolve_profile

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


def _chrome_binary() -> "str | None":
    """Chrome 可执行文件路径(用于 --user-data-dir 启动; mac 要 .app 里的二进制,
    不是 open -a 用的 .app 路径)。"""
    if sys.platform == "darwin":
        b = f"{_MAC_CHROME_APP}/Contents/MacOS/Google Chrome"
        return b if Path(b).exists() else None
    return _chrome_path()  # win/linux: 本来就是 exe


def _human_launch_args(binary: str, udd: str, pdir: "str | None", url: str) -> list:
    """构造带专用 user-data-dir 的 Chrome 启动参数(纯函数,可测)。"""
    args = [binary, f"--user-data-dir={udd}"]
    if pdir:
        args.append(f"--profile-directory={pdir}")
    if url:
        args.append(url)
    return args


class HumanBrowserCapability(CapabilityModule):
    id = "human_browser"
    display_name = "浏览器 human_browser(零自动化痕迹,作为人本人)"
    origin = ORIGIN_SELF_BUILT
    skill = "using-human-browser"
    platforms = None  # any host with a real Chrome + GUI session
    usage_hint = (
        "作为人本人操作真实账号时用(零自动化痕迹)。"
        "★真账号 / 长期 operator(发布员/cron)→ 必须带固定 profile:"
        "human_browser_open(url, profile='~/.fleet/<固定值>')——每 run 固定同一 profile 才能跨 run 复用登录"
        "(用户只扫一次码);漏传 profile 会落到用户默认日常 Chrome、登录落错地方、每次重登。"
        "再 take_screenshot + tap(x,y)/type_text 或 human_dom 操作(网页不在无障碍树)。"
        "裸 human_browser_open(url)=默认日常 Chrome,仅一次性/非长期用,真账号别用。仅自有设备/授权账号。"
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
        def human_browser_open(url: str = "", profile: str = "") -> dict:
            """启动/聚焦宿主真实 Chrome(**无 debug 端口、无自动化标志 → 零自动化痕迹**),可选打开 url。
            之后用 core 的 take_screenshot+tap/type_text 或 human_dom 作为人本人操作。仅自有设备/授权账号/正当用途。

            profile: 留空 = 宿主【真实日常 Chrome 默认 profile】(持久,即用户平时的浏览器)。
            传【专用持久 profile】(路径如 '~/.fleet/wechat-publisher',或 'dir@ProfileName') →
            用 --user-data-dir 起一个独立持久 profile:登录态跨 run 持久、与用户日常浏览隔离。
            ★ 真账号 operator(每 run 复用同一登录)请【固定用同一个 profile 值】,且【全程只用
            human_browser(+human_dom),不要混用 agent_browser】——混用会落到不同 profile、每次重登。
            传给 agent_browser 与 human_browser 同一个 profile 值 = 同一磁盘 user-data-dir = 同一份登录(R4)。

            想让某个 profile 用 human_dom(DOM 精度):human_dom 扩展是 per-profile 的,要装进那个 profile。
            **Chrome 137+ 已禁用 --load-extension 命令行加载**,所以靠 chrome://extensions 持久 Load-unpacked
            安装(开发者模式→加载未打包→选扩展目录;一次性、跨 run 持久)。视觉 agent 可自助装(见 using-human-dom
            「为某 profile 启用 human_dom」)。全新 profile 首次连桥(127.0.0.1:8779)会弹 Chrome "本地网络访问"
            授权,需点一次"允许"才连得上桥(见 skill)。"""
            url = (url or "").strip()
            profile = (profile or "").strip()
            try:
                if not profile:
                    chrome = _chrome_path()
                    if chrome is None:
                        return {"ok": False, "error": "Google Chrome 未安装"}
                    if sys.platform == "darwin":
                        args = ["open", "-a", "Google Chrome"] + ([url] if url else [])
                        subprocess.run(args, timeout=15, check=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        args = [chrome] + ([url] if url else [])
                        subprocess.Popen(args, start_new_session=True,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return {"ok": True, "opened": url or "(chrome)", "profile": "(default-daily)",
                            "note": "真实日常 Chrome 已启动(默认 profile,持久);take_screenshot+tap/type_text 或 human_dom 操作。"}
                binary = _chrome_binary()
                if binary is None:
                    return {"ok": False, "error": "Google Chrome 可执行文件未找到"}
                udd, pdir, key = _resolve_profile(profile)
                args = _human_launch_args(binary, udd, pdir, url)
                subprocess.Popen(args, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {"ok": True, "opened": url or "(chrome)", "profile": key,
                        "note": f"专用持久 profile 已启动(user-data-dir={udd});登录态跨 run 持久。"
                                "真账号请固定同一 profile + 全程 human_browser(+human_dom)。"
                                "想给该 profile 用 human_dom 见 using-human-dom(Load-unpacked,Chrome137+ --load-extension 已禁用)。"}
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        return ["human_browser_open"]
