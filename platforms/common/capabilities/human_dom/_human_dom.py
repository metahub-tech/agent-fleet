"""human_dom 能力: 注册 human_dom_locate/tap/fill。靠 server 注入 tap_fn/fill_fn + bridge。"""
from __future__ import annotations
import asyncio
from .._base import CapabilityModule, ORIGIN_SELF_BUILT
from ._locate import resolve_locate
from ._ident import resolve_profile_id


def _fill_snippet(text, n: int = 16) -> str:
    """取填入文本的前 n 个非空白字符作回读匹配片段(够独特, 又不至于把整段拿来匹配)。纯函数、可测。"""
    return (text or "").strip()[:n]


async def _verify_fill(bridge, text, css, profile_id) -> bool:
    """R2 回读校验(AgentHub #100): fill 后按【填入片段本身】再 locate, 某候选 visibleText 含该片段
    才算真落字。**绝不只判「非空」**—— 空 ProseMirror 的占位串也在 innerText 里, 判非空会假成功。
    永不抛(回读出错→视为未通过, 保守降级 vision)。"""
    snip = _fill_snippet(text)
    if not snip:
        return True  # 填空串无意义, 不拦
    try:
        await asyncio.sleep(0.4)  # 让编辑器处理完 paste 事件、DOM 落定再回读
        r = await resolve_locate(bridge, snip, css=css, profile_id=profile_id, timeout=3.0)
    except Exception:
        return False
    if not r.get("ok"):
        return False
    low = snip.lower()
    return any(low in (c.get("text") or "").lower() for c in r.get("candidates", []))


async def _do_fill(bridge, tap, fill, query, text, css, pid) -> dict:
    """定位 → tap 聚焦 → OS fill → 回读校验; 失败重试一次(re-tap 复用首次 center、不 re-locate)再降级。
    模块级(非闭包)便于单测。resolved_profile 一路带回可观测。retry 只一次防死循环;
    _os_fill 全选+粘贴覆盖式, re-fill 不追加、无副作用(取证文档实证落字机制本身 work)。"""
    r = await resolve_locate(bridge, query, css=css, profile_id=pid)
    if not r.get("ok") or not r["candidates"]:
        return {"ok": False, "reason": r.get("reason", "not_found"),
                "resolved_profile": pid, "suggest": "vision_locate"}
    x, y = r["candidates"][0]["center"]
    ix, iy = int(round(x)), int(round(y))
    for attempt in range(2):                 # 首次 + 至多重试一次
        tap(ix, iy)                          # 重试复用首次 center(不 re-locate, 避 R3 重排漂移)
        fill(text)
        if await _verify_fill(bridge, text, css=css, profile_id=pid):
            return {"ok": True, "filled_at": [ix, iy], "verified": True,
                    "resolved_profile": pid, "retried": attempt > 0}
    return {"ok": False, "reason": "fill_verify_failed", "suggest": "vision_locate",
            "filled_at": [ix, iy], "resolved_profile": pid}


def _installed_on_disk(ext_subdir):
    """查该 profile 的 human_dom 是否已装入 Chrome —— 读我方在 CDP loadUnpacked 成功那刻写的
    <ext_dir>/loaded.json 标记。**不用 Chrome 的 Secure Preferences**: 它 flush 惰性(真机实证
    open 后数秒仍空), 即时查盘不可靠; loaded.json 由 _loader 装成功即写, 端口一致性由外层 meta 保证。"""
    import json, os
    try:
        m = json.load(open(os.path.join(ext_subdir, "loaded.json"), encoding="utf-8"))
        return bool(m.get("loaded"))
    except Exception:
        return False


def compute_status(ext_root, self_bridge_port=None, connected_ids=frozenset()):
    """扫 ~/.fleet/human-dom-ext 的每个 bake 目录报 {profile_id, installed, bridge_port, connected}。
    installed = 纯盘扫描(loaded.json 标记), **不按 bridge_port 过滤** —— 换 server/换桥端口后
    旧 profile 的 installed 信息不丢(AgentHub #100: profiles=[] 把 installed 也丢了)。
    connected = 该 profile_id 是否连在【本 server 的桥】(connected_ids), 才是活跃 WS 维度。
    self_bridge_port 已不用于过滤(保留形参兼容)。"""
    import json, os
    out = []
    root = os.path.expanduser(ext_root)
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        subdir = os.path.join(root, name)
        try:
            meta = json.load(open(os.path.join(subdir, "meta.json")))
        except Exception:
            continue
        pid = meta.get("profile_id")
        out.append({"profile_id": pid, "installed": _installed_on_disk(subdir),
                    "bridge_port": meta.get("bridge_port"), "connected": pid in connected_ids})
    return out


def _status_hint(profiles):
    """讲清 installed/connected 语义, 终结「未连接=未安装」误判(#100)。"""
    if not profiles:
        return ("本 server 暂无已装 human_dom 的 profile。传专用 profile 调 "
                "human_browser_open(profile=..) 会自动烤+经 CDP 装扩展(零 GUI)。")
    parts = []
    if any(p["installed"] and p["connected"] for p in profiles):
        parts.append("有 profile human_dom 就绪(installed+connected)。")
    inst_not_conn = [p for p in profiles if p["installed"] and not p["connected"]]
    if inst_not_conn:
        parts.append(f"{len(inst_not_conn)} 个 profile 已装扩展但当前未连桥——多半是没开页/没导航到 http 页/"
                     "桥没起, 重新 human_browser_open(会幂等自动重装+重连)或导航到目标页即可, 【不要重复装】。")
    not_inst = [p for p in profiles if not p["installed"]]
    if not_inst:
        parts.append(f"{len(not_inst)} 个 profile 尚未装扩展;human_browser_open(profile=..) 会自动装。")
    return " ".join(parts)


def build_status(profiles):
    """把 per-profile 明细汇成 {installed, connected, profiles, hint}(#100 双维度)。
    installed/connected 为任一 profile 的聚合布尔; profiles 为逐 profile 明细。"""
    return {
        "installed": any(p["installed"] for p in profiles),
        "connected": any(p["connected"] for p in profiles),
        "profiles": profiles,
        "hint": _status_hint(profiles),
    }


class HumanDomCapability(CapabilityModule):
    id = "human_dom"
    display_name = "浏览器 human_dom(只读 DOM 定位, 配合 human_browser)"
    origin = ORIGIN_SELF_BUILT
    skill = "using-human-dom"
    platforms = None
    usage_hint = (
        "配合 human_browser 在真账号页面做 DOM 精确定位(只读扫 DOM→屏幕坐标,动作仍 OS 级、零痕迹)。"
        "human_dom_locate(query|css)→坐标;human_dom_tap=定位+点击;"
        "human_dom_fill(query,text,css)=定位+聚焦+覆盖填(全选+粘贴,支持中文大段)。"
        "★往富文本编辑器(公众号正文等 contenteditable)写大段:"
        "human_dom_fill(css='[contenteditable]', query='占位符如 从这里开始写正文', text=...),"
        "比截图+键盘可靠(实测正文字数 0→52)。"
        "扩展 per-profile,先装进该 profile(见 using-human-dom);"
        "拿不到(canvas/自定义按钮如发布)落 vision_locate。"
    )

    def __init__(self, bridge, tap_fn, fill_fn, bridge_port=8779):
        self._bridge = bridge; self._tap = tap_fn; self._fill = fill_fn
        self._bridge_port = bridge_port
        self.description = "只读 DOM 拿元素屏幕坐标(扩展 content script), 操作仍走 OS 级 tap/fill; 未命中落 vision_locate。"

    def availability(self):
        # 1. 探 starlette WS 库依赖（注册期静态判定）。
        try:
            import starlette.websockets  # noqa: F401
        except Exception as e:
            return False, f"starlette WS 不可用: {e}"
        # 2. 探【本 host 启用标记】——决定是否在本机注册 human_dom 工具族(host 级开关)。
        #    per-profile 扩展现由 human_browser_open 起专用 profile 时经 CDP 自动装(见 _loader),
        #    无需手动跑安装脚本; 这个 marker 只表示"本 host 要用 human_dom"。
        import os
        if not os.path.exists(os.path.expanduser("~/.fleet/human-dom-ready")):
            return False, (
                "本 host 未启用 human_dom(无 ~/.fleet/human-dom-ready 标记)。"
                "创建该标记文件(touch ~/.fleet/human-dom-ready)并重启 server 即注册 human_dom 工具;"
                "之后 human_browser_open(profile=..) 会自动把扩展装进该 profile(零 GUI)。"
            )
        return True, ""

    def register(self, mcp) -> list[str]:
        bridge, tap, fill = self._bridge, self._tap, self._fill

        @mcp.tool
        async def human_dom_locate(query: str, css: str = "", max_results: int = 10, profile: str = "") -> dict:
            """只读 DOM 定位: 按文字/aria-label/placeholder(或 css)找元素, 返回屏幕坐标候选。
            省略 profile 时解析到当前活跃 operator profile(非硬 default); 成功带 resolved_profile。
            先 human_browser_open 并等页面 load。未命中/桥未连会建议改用 vision_locate。"""
            pid = resolve_profile_id(bridge, profile)
            r = await resolve_locate(bridge, query, css=css or None, max_results=max_results, profile_id=pid)
            r["resolved_profile"] = pid   # 成功/未命中/no_tab 都带, 与 tap/fill 统一可观测(catch 静默误解析)
            return r

        @mcp.tool
        async def human_dom_tap(query: str, nth: int = 0, css: str = "", profile: str = "") -> dict:
            """定位 + OS 级点击(locate+tap 合一缩小漂移窗)。省略 profile 解析到活跃 operator。"""
            pid = resolve_profile_id(bridge, profile)
            r = await resolve_locate(bridge, query, css=css or None, profile_id=pid)
            if not r.get("ok") or not r["candidates"]:
                return {"ok": False, "reason": r.get("reason", "not_found"),
                        "resolved_profile": pid, "suggest": "vision_locate"}
            x, y = r["candidates"][min(nth, len(r["candidates"]) - 1)]["center"]
            tap(int(round(x)), int(round(y)))
            return {"ok": True, "tapped": [int(round(x)), int(round(y))], "resolved_profile": pid}

        @mcp.tool
        async def human_dom_fill(query: str, text: str, css: str = "", profile: str = "") -> dict:
            """定位 + 点击聚焦 + OS 级填充(全选 + 剪贴板粘贴, 覆盖式, 支持中文) + 回读校验(失败重试一次)。
            省略 profile 解析到活跃 operator。R2(#100): fill 后按填入片段回读, 真落字才 ok:True/verified:True;
            两次都没落字→ ok:False/reason:fill_verify_failed/suggest vision, 不再假成功。带 resolved_profile。"""
            pid = resolve_profile_id(bridge, profile)
            return await _do_fill(bridge, tap, fill, query, text, css or None, pid)

        @mcp.tool
        async def human_dom_status() -> dict:
            """human_dom 双维度状态: {installed, connected, profiles, hint}。
            installed=扩展已装入该 profile(纯盘扫描 loaded.json 标记, 报所有已装副本、不按桥端口过滤);
            connected=该 profile 当前连在【本 server 的桥】; 每条 bridge_port 是它烤入的桥端口。
            关键: installed=true/connected=false ≠ 未安装 —— 别重装, 重开 human_browser_open 或导航到目标页即可(见 hint)。"""
            connected = {c["profile_id"] for c in list(bridge._clients)}
            st = build_status(compute_status("~/.fleet/human-dom-ext", connected_ids=connected))
            for p in st["profiles"]:              # 观测: 每 profile 带上 focused(带外查; 未连/旧扩展→None; 不影响 installed/connected)
                p["focused"] = bridge.focus_state(p["profile_id"])
            return st

        @mcp.tool
        async def human_dom_focused(profile: str = "") -> dict:
            """前台检查(带外, Class C, 取代截图目测作首选): 该 profile 活跃 tab 是否真持焦点(document.hasFocus())。
            focused=True → 可直接 OS 操作; False → human_browser_open(profile, activate=True) 拉回后复查;
            None → 拿不到信号(未连桥 / chrome:// / 非 Chrome / 旧扩展未上报) → 调用方回落 take_screenshot(spec §5.2/§6.4)。
            省略 profile 走与 locate/tap/fill 相同的 resolve_profile_id(继承活跃 operator)。"""
            pid = resolve_profile_id(bridge, profile)
            f = bridge.focus_state(pid)
            reason = "focused" if f is True else ("not_focused" if f is False else "no_signal")
            return {"ok": True, "focused": f, "profile": pid, "reason": reason}

        return ["human_dom_locate", "human_dom_tap", "human_dom_fill", "human_dom_status", "human_dom_focused"]
