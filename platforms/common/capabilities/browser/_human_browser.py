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

import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

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


# 专用 profile 干净启动 flag(test-win11 真机验证)——两类原生弹窗抑制:
# ① 首启抑制: 消除全新 profile 的登录提示/设默认横幅/What's New/FRE 原生窗口(AgentHub #211),
#    否则操作员 agent 不认识会乱处理(误关标签/重开落登录页/误触其它应用)。
# ② --hide-crash-restore-bubble: 上次 Chrome 被异常退出(强杀/崩溃)后 profile 带「未正确关闭」标记,
#    下次开窗弹「要恢复页面吗」气泡, 干扰 operator 判断(连锁误诊登录态/tab 迷失, AgentHub #100 轮10)。
#    我方清理已改优雅关窗, 但产品兜住用户侧任何异常退出场景。
# ③ --start-maximized: 首帧最大化提示(会被 Chrome per-profile 窗口尺寸恢复覆盖成半屏, 真正强制靠
#    open 后 server 侧 Win32 ShowWindow, 见 _maybe_maximize / maximize_fn; 此 flag 只作首帧观感)。
# 均不禁用扩展、不影响 human_dom 加载(扩展走 CDP loadUnpacked)。--disable-features 的 feature 名单
# 单列, 便于与 human_dom 的 LNA disable 合并成【一个】--disable-features(Chrome 有多个只认最后一个)。
_FIRST_RUN_FLAGS = ["--no-first-run", "--no-default-browser-check", "--disable-fre",
                    "--hide-crash-restore-bubble", "--start-maximized"]
_FIRST_RUN_DISABLE_FEATURES = ["ChromeWhatsNewUI", "SigninPromo", "ForYouFre"]
# human_dom(remote_debug)时额外关掉「本地网络访问(LNA/PNA)」检查: 否则 content script 从
# 公开页(example.com/公众号等)直连 localhost 桥(ws://127.0.0.1)会被 Chrome gate ——弹「本地
# 网络访问 允许/屏蔽」且即使允许也有长延迟, WS 注册不上 → human_dom_locate 持续 no_tab_for_profile
# (AgentHub #100 真机实锤)。关掉后全新 profile 首启即 connected、零弹窗零人工。作用域仅本专用
# profile 的 Chrome(不动用户日常 Chrome); 非自动化标志, navigator.webdriver 仍 false, moat 不破。
_HUMANDOM_DISABLE_FEATURES = ["LocalNetworkAccessChecks"]


def _human_launch_args(binary: str, udd: str, pdir: "str | None", url: str,
                       remote_debug: bool = False) -> list:
    """构造带专用 user-data-dir 的 Chrome 启动参数(纯函数,可测)。

    含首启抑制 flag(见 _FIRST_RUN_* 注释)。remote_debug=True(human_dom)时:
    ① 加 `--remote-debugging-port=0`(临时端口 → DevToolsActivePort)供 CDP `Extensions.loadUnpacked`
    确定性装扩展; ② 关 LocalNetworkAccessChecks 让 content script 直连 localhost 桥不被 PNA gate。
    不加 --enable-automation → navigator.webdriver 仍 false; 本机 no-Origin 客户端才连得上 CDP,
    moat 不破。所有 --disable-features 合并成一个 flag。url 保持最后一个位置参。"""
    feats = list(_FIRST_RUN_DISABLE_FEATURES)
    if remote_debug:
        feats += _HUMANDOM_DISABLE_FEATURES
    args = [binary, f"--user-data-dir={udd}", *_FIRST_RUN_FLAGS,
            f"--disable-features={','.join(feats)}"]
    if pdir:
        args.append(f"--profile-directory={pdir}")
    if remote_debug:
        args.append("--remote-debugging-port=0")
    if url:
        args.append(url)
    return args


def _maybe_load_human_dom(udd: str, ext_dir: str, navigate_url=None) -> "dict | None":
    """经 CDP 把烤好的 human_dom 扩展副本装进该 profile 的 Chrome(零 GUI); 装完(可选)导航到
    navigate_url 让 content script 注入(见 loader: 必须 load 后再 navigate)。
    human_dom 能力不在本 server → 返回 None; 否则返回 loader 的 {ok,...} 结果。永不抛。"""
    try:
        from ..human_dom._loader import load_dom_extension
    except Exception:
        return None
    try:
        return load_dom_extension(udd, ext_dir, navigate_url=navigate_url)
    except Exception as e:  # loader 已保证不抛, 这里再兜一层防御
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _maybe_foreground(fn, udd: str, activate: bool) -> bool:
    """起窗后调平台注入的窗口置前/最大化。activate=True: 激活最大化(Win32 ShowWindow(SW_MAXIMIZE));
    activate=False: 非激活最大化(win 填工作区不夺焦点, spec §6.1)。`--start-maximized` 会被 Chrome
    per-profile 尺寸恢复覆盖(真机实证半屏), 故 server 侧确定性强制。返回是否真的调用生效(供 activated/
    maximized 如实置, 不再用 bool(fn))。无 fn(mac/linux 未注入)→ False。best-effort, 永不抛。"""
    if not fn:
        return False
    try:
        return bool(fn(udd, activate))
    except Exception:
        return False


def _ensure_human_dom_ext(profile: str, bridge_port: "int | None") -> "str | None":
    """全新 profile 起浏览器时,自动为它烤好 human_dom 扩展副本(若缺、或副本桥端口与当前不符)。
    返回副本目录(供 agent chrome://extensions Load-unpacked);拿不到返回 None,绝不阻断开浏览器。
    便利封装:省掉 agent 另跑 install 脚本——这是 per-profile 启用最易漏的坑(漏烤会去 Load
    仓库模板目录而失败,模板含占位符不连桥)。human_dom 扩展走 Load-unpacked(Chrome137+ 禁了
    --load-extension),本函数只负责【烤好副本】,Load-unpacked 仍由 agent 在 chrome://extensions 做。"""
    if not profile or not bridge_port:
        return None  # 默认日常 profile(无 profile) / 无桥端口 → 不 auto-bake
    try:
        from ..human_dom._ident import human_dom_profile_id
        from ..human_dom._setup import prepare_extension, template_hash
    except Exception:
        return None  # human_dom 能力不在本 server → human_browser 仍可独立用
    try:
        pid = human_dom_profile_id(profile)
        ext_dir = os.path.expanduser(f"~/.fleet/human-dom-ext/{pid}")
        meta = Path(ext_dir) / "meta.json"
        need = True
        if meta.exists():
            try:  # 已有副本: 桥端口不符(server 换端口副本失效)或 content.js 模板变了(R1/R3 改了扩展)→ 重烤
                m = json.loads(meta.read_text(encoding="utf-8"))
                need = m.get("bridge_port") != int(bridge_port) or m.get("tpl_hash") != template_hash()
            except Exception:
                need = True  # meta 损坏 → 重烤
        if need:
            prepare_extension(ext_dir, bridge_port, pid)  # 已存在会先 rmtree 再 copytree
        return ext_dir
    except Exception:
        return None


# ── 幂等复用(AgentHub #100 轮31)──────────────────────────────────────────────
# 真实场景: 操作员 agent 把 human_browser_open 当"翻页/刷新"反复调(一个任务 17 次)。原实现
# 每次无条件重启 Chrome + 重跑 CDP 装扩展 → ①慢(每次冷启动数秒)②破坏(把已登录的目标页顶成新标签/
# Google 首页, agent 落错页 churn)。光靠 skill 文案劝不住模型的重开习惯, 故在【工具层】做成幂等:
# 同一 profile 的 Chrome 已在运行就复用 —— 不重 spawn、不重装扩展、不顶掉当前页。
#
# 探测两路(先盘、后进程内): ① 盘扫描 <udd>/DevToolsActivePort + /json/version 探活的 CDP 端点
# (human_dom 起窗带 --remote-debugging-port=0, 端口随 Chrome 存活; 跨 server 重启也可探到)。
# ② 进程内启动注册表(本 server 生命周期内起过的 profile→Popen 句柄; 覆盖【无 debug 端口】的非
# human_dom 专用 profile)。任一命中即视为已开。冷启动路径起窗后登记, 供后续复用探测。
_LAUNCHED: "dict[str, subprocess.Popen]" = {}
_LAUNCHED_LOCK = threading.Lock()      # 守 _LAUNCHED 与 _KEY_LOCKS 两个字典的读写
_KEY_LOCKS: "dict[str, threading.Lock]" = {}


def _key_lock(key: str) -> threading.Lock:
    """取该 profile_key 的专属锁(不存在则建)。用于把「探测冷/热 → 冷启动 spawn → 登记」串成
    原子临界区: 同一 profile 的并发 open(FastMCP 同步工具跑在线程池, 多客户端/重叠调用会并发)
    只会冷启动一次, 不会双 spawn/双装扩展。不同 profile 各自的锁 → 仍可并发起窗(参照
    BrowserLeaseRegistry.bind 把 start_fn 收进锁内的范式, 但按 key 细粒度以免拖累跨 profile)。"""
    with _LAUNCHED_LOCK:
        lk = _KEY_LOCKS.get(key)
        if lk is None:
            lk = _KEY_LOCKS[key] = threading.Lock()
        return lk


def _proc_alive(proc) -> bool:
    """我方起的 Chrome 进程是否仍存活(poll()==None)。探测出错保守判否。"""
    try:
        return proc is not None and proc.poll() is None
    except Exception:
        return False


def _record_launch(key: str, proc) -> None:
    """冷启动起窗后登记 profile_key→进程句柄, 供后续 human_browser_open 复用探测。"""
    with _LAUNCHED_LOCK:
        _LAUNCHED[key] = proc


def _probe_debug_port(udd: str, _open=urllib.request.urlopen, timeout: float = 1.5) -> "int | None":
    """快速单探: 该 udd 是否已有【存活的】Chrome CDP 端点。读一次 <udd>/DevToolsActivePort,
    /json/version 响应且是 Chrome → 返回端口; 文件缺失 / 陈旧死端口(连接被拒) → None。永不抛。
    (陈旧端口: 上次 Chrome 崩溃留下的 DevToolsActivePort 指向已死端口 → /json/version 失败 → None,
    正确地判冷、走冷启动。)"""
    try:
        from ..human_dom._loader import _read_port_once, _http_json
    except Exception:
        return None
    try:
        port = _read_port_once(udd)
        if not port:
            return None
        ver = _http_json(f"http://127.0.0.1:{port}/json/version", _open, timeout=timeout)
        if ver.get("webSocketDebuggerUrl") or "Chrome" in (ver.get("Browser", "") or ""):
            return port
    except Exception:
        return None
    return None


def _detect_reuse(key: str, udd: str, _probe=None) -> "dict | None":
    """该 profile 的 Chrome 是否已在运行? 已开返回 {'port': int|None, 'via': str}(warm), 否则 None(冷)。
    先盘扫 debug 端点(跨重启 / human_dom 专用 profile 都可探到), 再退回进程内启动注册表(覆盖无 debug
    端口的非 human_dom profile, 仅本 server 生命周期内)。命中进程内但进程已死 → 清掉陈旧记录、判冷。"""
    probe = _probe or _probe_debug_port
    port = probe(udd)
    if port is not None:
        return {"port": port, "via": "debug-port"}
    with _LAUNCHED_LOCK:
        proc = _LAUNCHED.get(key)
        if proc is not None and _proc_alive(proc):
            return {"port": None, "via": "in-process"}
        if proc is not None:  # 进程已死 → 丢弃陈旧记录, 判冷
            _LAUNCHED.pop(key, None)
    return None


def _same_origin(a: str, b: str) -> bool:
    """两 url 是否同源(scheme+host+port 一致)。解析失败或空串 → False(视为不同源)。"""
    try:
        pa, pb = urlparse(a or ""), urlparse(b or "")
        if not pa.hostname or not pb.hostname:
            return False
        return (pa.scheme, pa.hostname, pa.port) == (pb.scheme, pb.hostname, pb.port)
    except Exception:
        return False


def _warm_navigate(port: "int | None", url: str, _open=urllib.request.urlopen) -> str:
    """复用路径下的窗口内导航决策(绝不新开标签、绝不 spawn)。返回状态 token:
      no-url          — 未传 url, 保持当前页不动。
      no-port         — 无 debug 通道(非 human_dom profile), 无法窗口内导航, 保持不动(不 spawn)。
      probe-failed    — 读不到窗口标签态, 保守保持不动。
      multi-tab-noop  — 窗口有多个标签, 无法可靠判定"前台页", 遵循"宁可 no-op"不自动导航(R2 防破坏)。
      same-origin-noop— (单标签)与当前页同源(视为已在目标站), 不重载以保护登录态/编辑器(R2 防破坏)。
      navigated       — (单标签)在当前页内导航到目标 url 成功。
      nav-failed      — 尝试窗口内导航未成功。

    只在【恰好一个 page 标签】时才做窗口内导航: 多标签下 CDP /json 无法可靠标出"操作员当前前台看的
    那张标签", 盲选 page[0] 可能把已登录的目标页导航掉(reviewer #1), 故多标签一律不动、交操作员手切。"""
    if not url:
        return "no-url"
    if not port:
        return "no-port"
    try:
        from ..human_dom._loader import _http_json, _navigate
    except Exception:
        return "no-port"
    try:
        pages = _http_json(f"http://127.0.0.1:{port}/json", _open)
        page_urls = [t.get("url", "") for t in pages if t.get("type") == "page"]
    except Exception:
        return "probe-failed"          # 读不到标签态 → 保守不动(绝不盲导航)
    if len(page_urls) > 1:
        return "multi-tab-noop"        # 多标签: 无法可靠判前台页 → 不动
    if page_urls and _same_origin(page_urls[0], url):
        return "same-origin-noop"      # 唯一标签已同源 → 不重载
    return "navigated" if _navigate(port, url, _open) else "nav-failed"


_WARM_NAV_NOTE = {
    "no-url": " 未指定 url, 保持当前页不动。",
    "no-port": " 已复用窗口; 无 debug 通道做窗口内导航, 如需换页请在窗口内点链接/地址栏。",
    "probe-failed": " 未能读取窗口标签状态, 保持当前页不动; 如需换页请在窗口内点链接/地址栏。",
    "multi-tab-noop": " 窗口内有多个标签, 为避免顶掉当前页未自动导航; 如需换页请在窗口内点链接/地址栏切换。",
    "same-origin-noop": " 目标 url 与当前页同源(视为已在目标站), 未重载以保护登录态/编辑器。",
    "navigated": " 已在现有窗口内导航到目标 url(未新开标签)。",
    "nav-failed": " 窗口内导航未成功, 请在窗口内手动导航。",
}


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

    def __init__(self, bridge_port: "int | None" = None, maximize_fn=None):
        # bridge_port: 本 server 的 human_dom 桥端口(由 server 注入)。起【专用 profile】时
        # 用它 auto-bake 该 profile 的 human_dom 扩展副本(把此端口烤进副本)。None=不 auto-bake。
        # maximize_fn(udd): 平台注入的窗口强制最大化(win: Win32 ShowWindow); None=不最大化(mac/linux)。
        self._bridge_port = bridge_port
        self._maximize_fn = maximize_fn
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
        def human_browser_open(url: str = "", profile: str = "", activate: bool = False) -> dict:
            """启动/聚焦宿主真实 Chrome(**无 debug 端口、无自动化标志 → 零自动化痕迹**),可选打开 url。
            activate=False(默认)【不抢前台】(复用路径零重激活, 治 #188);即将在浏览器里动手前才传
            activate=True 把该 profile 的 Chrome 拉前台(见 using-human-browser 的"查→不对才拉"循环:
            先 human_dom_focused 查, 不对才 activate=True)。
            之后用 core 的 take_screenshot+tap/type_text 或 human_dom 作为人本人操作。仅自有设备/授权账号/正当用途。

            profile: 留空 = 宿主【真实日常 Chrome 默认 profile】(持久,即用户平时的浏览器)。
            传【专用持久 profile】(路径如 '~/.fleet/wechat-publisher',或 'dir@ProfileName') →
            用 --user-data-dir 起一个独立持久 profile:登录态跨 run 持久、与用户日常浏览隔离。
            ★ 真账号 operator(每 run 复用同一登录)请【固定用同一个 profile 值】,且【全程只用
            human_browser(+human_dom),不要混用 agent_browser】——混用会落到不同 profile、每次重登。
            传给 agent_browser 与 human_browser 同一个 profile 值 = 同一磁盘 user-data-dir = 同一份登录(R4)。

            想让某个 profile 用 human_dom(DOM 精度):**无需操作员任何手动操作**——传专用 profile 时
            server 会自动把 human_dom 扩展装进该 profile(auto-bake 副本 + 起 Chrome 带临时 debug 端口 +
            经 CDP `Extensions.loadUnpacked` 确定性装,零 GUI/零视觉;Chrome137+ 禁了 --load-extension,
            这是替代路径)。返回里 human_dom.ok=true 即已装好,导航到目标页后直接 human_dom_locate/tap/fill。
            全新 profile 首次连桥会弹 Chrome "本地网络访问"授权,点一次"允许"才连得上桥(见 skill)。

            幂等复用:对【专用 profile】,该 profile 的 Chrome 已在运行时本调用会复用现有窗口——
            不重启浏览器、不重装扩展、不新开标签,返回 reused:true。只首次冷启动 spawn+装扩展。
            故反复调用廉价且无破坏:传 url 且与当前页同源即视为已在目标站不重载(保护登录态/编辑器);
            仅换到不同源目标时在现有窗口内导航(不新开标签)。不必把本工具当翻页用,同站跳转在窗口内点链接/
            地址栏即可;想确认窗口状态用 human_dom_status。"""
            url = (url or "").strip()
            profile = (profile or "").strip()
            try:
                if not profile:
                    chrome = _chrome_path()
                    if chrome is None:
                        return {"ok": False, "error": "Google Chrome 未安装"}
                    if sys.platform == "darwin":
                        bg = [] if activate else ["-g"]     # -g: 不抢前台(spec §6.2, mac 此路径能兑现)
                        args = ["open"] + bg + ["-a", "Google Chrome"] + ([url] if url else [])
                        subprocess.run(args, timeout=15, check=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        # Windows/Linux: Chrome 单例转发由 Chrome 自身控制前台, activate 压不掉(§6.3)。
                        args = [chrome] + ([url] if url else [])
                        subprocess.Popen(args, start_new_session=True,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return {"ok": True, "opened": url or "(chrome)", "profile": "(default-daily)",
                            "reused": False, "activated": None,   # 不确定性控前台(§6.3): None, 不假称 False
                            "note": "真实日常 Chrome 已启动(默认 profile,持久);take_screenshot+tap/type_text 或 human_dom 操作。"
                                    "(默认日常 Chrome 由 Chrome 自身单例转发把窗口带前台, activate 不控;"
                                    "需后台/不打扰运行请用专用 profile。幂等复用仅对专用 profile 生效。)"}
                binary = _chrome_binary()
                if binary is None:
                    return {"ok": False, "error": "Google Chrome 可执行文件未找到"}
                udd, pdir, key = _resolve_profile(profile)
                # 幂等复用: 该 profile 的 Chrome 已在运行就复用 —— 不重 spawn、不重装扩展、不顶掉当前页
                # (AgentHub #100 轮31: 操作员把 human_browser_open 当翻页反复调, 重开数秒冷启动 + 顶登录页)。
                # 「探测冷/热 → (冷)spawn → 登记」收进 per-key 锁, 保证同一 profile 并发 open 只冷启动一次
                # (不双 spawn/双装扩展); 慢的 CDP 装扩展留在锁外(不长占锁, 不拖累别的 profile)。
                ext_dir = None
                with _key_lock(key):
                    warm = _detect_reuse(key, udd)
                    if warm is None:
                        ext_dir = _ensure_human_dom_ext(profile, self._bridge_port)  # auto-bake 扩展副本(缺则烤)
                        # 有 human_dom: 先起空页(不带目标 url), 装完扩展再经 CDP navigate 到 url ——
                        # content script 只在【新导航】时注入, 启动就带 url 会导致装好前页面已加载、脚本不注入。
                        launch_url = "" if ext_dir else url
                        args = _human_launch_args(binary, udd, pdir, launch_url, remote_debug=bool(ext_dir))
                        proc = subprocess.Popen(args, start_new_session=True,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        _record_launch(key, proc)  # 锁内登记 → 后续同 profile open 即探到热、跳过 spawn+装扩展
                        print(f"[human_browser] cold-start profile={key} human_dom={bool(ext_dir)}", file=sys.stderr)
                # ── 热路径(复用): 锁外做窗口内导航/最大化(非破坏)──
                if warm is not None:
                    nav = _warm_navigate(warm["port"], url)
                    # 复用默认【不抢前台】(P0 治 #188): 仅 activate=True 才拉前台+最大化; 默认零重激活。
                    acted = _maybe_foreground(self._maximize_fn, udd, activate) if activate else False
                    print(f"[human_browser] reuse profile={key} via={warm['via']} nav={nav} activate={activate}", file=sys.stderr)
                    return {
                        "ok": True, "opened": url or "(chrome)", "profile": key,
                        "reused": True, "reuse_via": warm["via"],
                        "note": "该 profile 的 Chrome 已在运行, 复用现有窗口(未重启浏览器、未重装扩展、未新开标签)。"
                                + _WARM_NAV_NOTE.get(nav, ""),
                        "maximized": acted, "activated": acted and activate,
                    }
                # ── 冷路径(首开): 锁外做 CDP 装扩展/导航/最大化 ──
                resp = {"ok": True, "opened": url or "(chrome)", "profile": key, "reused": False,
                        "note": f"专用持久 profile 已启动(user-data-dir={udd});登录态跨 run 持久。"
                                "真账号请固定同一 profile + 全程 human_browser(+human_dom)。"}
                if ext_dir:
                    # 确定性装扩展: 起 Chrome 带临时 debug 端口, 经 CDP loadUnpacked 把烤好的副本装进该
                    # profile, 再 navigate 到目标 url —— 零 GUI/零视觉/零 DPI(Chrome137+ 禁 --load-extension 的替代)。
                    load = _maybe_load_human_dom(udd, ext_dir, navigate_url=url or None)
                    resp["human_dom"] = load or {"ok": False, "error": "human_dom 能力不在本 server"}
                    if load and load.get("ok"):
                        navd = load.get("navigated")
                        nav_note = ("" if url == "" else
                                    ("已导航到目标页。" if navd else "但目标页导航未成功, 请手动导航(导航后 content script 自动注入)。"))
                        resp["note"] += (" human_dom 扩展已自动装入该 profile(CDP loadUnpacked, 零 GUI, 无需操作员点扩展页);"
                                         f"{nav_note}之后 human_dom_locate/tap/fill 可用。装一次即可, 后续 human_browser_open 复用现有窗口不重装。")
                    else:
                        err = (load or {}).get("error", "未知")
                        # 降级: 装扩展没成但仍要把用户请求的 url 打开(否则停在空白页)。正在运行的
                        # Chrome 会把该 url 转给现有实例; 没起来的话这条会新建一个带 url 的实例。
                        if url:
                            try:
                                subprocess.Popen(_human_launch_args(binary, udd, pdir, url),
                                                 start_new_session=True,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            except Exception:
                                pass
                        resp["note"] += (f" human_dom 扩展自动装入未成功({err});已照常打开目标页, 仍可用 human_browser"
                                         "(截图+tap), human_dom 精度暂不可用。可重试 human_browser_open, 或见 using-human-dom 排错。")
                else:
                    resp["note"] += " 想给该 profile 用 human_dom 见 using-human-dom(server 侧 CDP 自动装, 无需操作员手动)。"
                # 起窗后 server 侧最大化(Win32): activate=True 激活最大化; activate=False 非激活最大化
                # (填工作区不夺焦点, §6.1)——防 Chrome per-profile 尺寸恢复覆盖 --start-maximized; 不模拟键盘。
                acted = _maybe_foreground(self._maximize_fn, udd, activate)
                resp["maximized"] = acted
                resp["activated"] = acted and activate
                return resp
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        return ["human_browser_open"]
