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


def _human_dom_ext_dir() -> "str | None":
    """human_dom 扩展目录(给 --load-extension 用,让一个【新 profile】启用 human_dom——
    扩展是 per-profile 的,新建的专用 profile 默认没装,靠这个随启动加载)。"""
    d = Path(__file__).resolve().parent.parent / "human_dom" / "extension"
    return str(d) if (d / "manifest.json").exists() else None


def _human_launch_args(binary: str, udd: str, pdir: "str | None", url: str,
                       load_extension: "str | None" = None) -> list:
    """构造带专用 user-data-dir 的 Chrome 启动参数(纯函数,可测)。
    load_extension: 扩展目录 → 加 --load-extension(让该 profile 启用 human_dom 扩展)。"""
    args = [binary, f"--user-data-dir={udd}"]
    if pdir:
        args.append(f"--profile-directory={pdir}")
    if load_extension:
        args.append(f"--load-extension={load_extension}")
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
        def human_browser_open(url: str = "", profile: str = "", with_human_dom: bool = False) -> dict:
            """启动/聚焦宿主真实 Chrome(**无 debug 端口、无自动化标志 → 零自动化痕迹**),可选打开 url。
            之后用 core 的 take_screenshot+tap/type_text 或 human_dom 作为人本人操作。仅自有设备/授权账号/正当用途。

            profile: 留空 = 宿主【真实日常 Chrome 默认 profile】(持久,即用户平时的浏览器)。
            传【专用持久 profile】(路径如 '~/.fleet/wechat-publisher',或 'dir@ProfileName') →
            用 --user-data-dir 起一个独立持久 profile:登录态跨 run 持久、与用户日常浏览隔离。
            ★ 真账号 operator(每 run 复用同一登录)请【固定用同一个 profile 值】,且【全程只用
            human_browser(+human_dom),不要混用 agent_browser】——混用会落到不同 profile、每次重登。
            传给 agent_browser 与 human_browser 同一个 profile 值 = 同一磁盘 user-data-dir = 同一份登录(R4)。

            with_human_dom(仅对【专用 profile】生效):=True 时随启动 --load-extension 把 human_dom 扩展
            加载进【这个新 profile】,让该 profile 立即能用 human_dom 定位。**新建的专用 profile 默认没装
            human_dom 扩展**(扩展是 per-profile 的),所以第一次为某 profile 开 human_dom 就传 with_human_dom=True。
            注意:--load-extension 只在【全新启动】生效——若该 profile 的 Chrome 已在运行,需先全部关掉再重开;
            且会有 Chrome "开发者模式扩展" 横幅(本地可见、网页探不到)。默认 profile(留空)请改用持久安装(见 skill)。"""
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
                    note = "真实日常 Chrome 已启动(默认 profile,持久);take_screenshot+tap/type_text 或 human_dom 操作。"
                    if with_human_dom:
                        note += ("【with_human_dom 对默认 profile 不生效——默认 profile 走 open -a/直起,"
                                 "不支持 --load-extension;请用 install 脚本持久 Load unpacked,或改传专用 profile=。】")
                    return {"ok": True, "opened": url or "(chrome)", "profile": "(default-daily)",
                            "human_dom_ext": False, "note": note}
                binary = _chrome_binary()
                if binary is None:
                    return {"ok": False, "error": "Google Chrome 可执行文件未找到"}
                udd, pdir, key = _resolve_profile(profile)
                ext = _human_dom_ext_dir() if with_human_dom else None
                if with_human_dom and ext is None:
                    return {"ok": False, "error": "human_dom 扩展目录未找到(应在 capabilities/human_dom/extension)"}
                args = _human_launch_args(binary, udd, pdir, url, load_extension=ext)
                subprocess.Popen(args, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                note = f"专用持久 profile 已启动(user-data-dir={udd});登录态跨 run 持久。"
                note += (f" human_dom 扩展已随启动加载进该 profile(load-extension={ext};仅全新启动生效)。"
                         if ext else "真账号请固定同一 profile + 全程 human_browser(+human_dom)。")
                return {"ok": True, "opened": url or "(chrome)", "profile": key,
                        "human_dom_ext": bool(ext), "note": note}
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        return ["human_browser_open"]
