"""human_dom 能力: 注册 human_dom_locate/tap/fill。靠 server 注入 tap_fn/fill_fn + bridge。"""
from __future__ import annotations
from .._base import CapabilityModule, ORIGIN_SELF_BUILT
from ._locate import resolve_locate
from ._ident import human_dom_profile_id


def _installed_on_disk(meta):
    """查该 profile 的 Chrome Secure Preferences 是否含本扩展(CDP loadUnpacked 会把
    unpacked 扩展的 source path 写进 Secure Preferences; 扩展不落 Extensions/<id>/, 故查 prefs)。
    返回 True/False; meta 无 udd(旧副本) → None(交由调用方兜底)。agent-fleet 是本机进程直接查盘。"""
    import json, os
    udd = meta.get("udd")
    if not udd:
        return None
    pdir = meta.get("profile_dir") or "Default"
    sp = os.path.join(os.path.expanduser(udd), pdir, "Secure Preferences")
    try:
        text = open(sp, encoding="utf-8", errors="ignore").read()
    except Exception:
        return False
    pid = meta.get("profile_id") or ""
    # source path = <home>/.fleet/human-dom-ext/<pid>; 两段子串同现 = 本扩展已登记该 profile
    return ("human-dom-ext" in text) and bool(pid) and (pid in text)


def compute_status(ext_root, self_bridge_port, connected_ids):
    import json, os
    out = []
    root = os.path.expanduser(ext_root)
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        try:
            meta = json.load(open(os.path.join(root, name, "meta.json")))
        except Exception:
            continue
        if int(meta.get("bridge_port", -1)) != int(self_bridge_port):
            continue
        pid = meta.get("profile_id")
        disk = _installed_on_disk(meta)
        installed = disk if disk is not None else True  # 旧 meta 无 udd → 兜底 baked-existence
        out.append({"profile_id": pid, "installed": installed,
                    "bridge_port": int(self_bridge_port), "connected": pid in connected_ids})
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
        # 2. 探安装标记——扩展已由用户一次性装入真实 Chrome profile。
        import os
        if not os.path.exists(os.path.expanduser("~/.fleet/human-dom-ready")):
            return False, (
                "human_dom 扩展未安装(无 ~/.fleet/human-dom-ready 标记)。"
                "跑 platforms/macos/scripts/install-human-dom-extension.sh"
                " 把扩展装进真实 Chrome 后重连即启用。"
            )
        return True, ""

    def register(self, mcp) -> list[str]:
        bridge, tap, fill = self._bridge, self._tap, self._fill

        @mcp.tool
        async def human_dom_locate(query: str, css: str = "", max_results: int = 10, profile: str = "") -> dict:
            """只读 DOM 定位: 按文字/aria-label/placeholder(或 css)找元素, 返回屏幕坐标候选。
            先 human_browser_open 并等页面 load。未命中/桥未连会建议改用 vision_locate。"""
            return await resolve_locate(bridge, query, css=css or None, max_results=max_results,
                                        profile_id=human_dom_profile_id(profile))

        @mcp.tool
        async def human_dom_tap(query: str, nth: int = 0, css: str = "", profile: str = "") -> dict:
            """定位 + OS 级点击(locate+tap 合一缩小漂移窗)。"""
            r = await resolve_locate(bridge, query, css=css or None,
                                     profile_id=human_dom_profile_id(profile))
            if not r.get("ok") or not r["candidates"]:
                return {"ok": False, "reason": r.get("reason", "not_found"), "suggest": "vision_locate"}
            x, y = r["candidates"][min(nth, len(r["candidates"]) - 1)]["center"]
            tap(int(round(x)), int(round(y)))
            return {"ok": True, "tapped": [int(round(x)), int(round(y))]}

        @mcp.tool
        async def human_dom_fill(query: str, text: str, css: str = "", profile: str = "") -> dict:
            """定位 + 点击聚焦 + OS 级填充(全选 + 剪贴板粘贴, 覆盖式, 支持中文)。"""
            r = await resolve_locate(bridge, query, css=css or None,
                                     profile_id=human_dom_profile_id(profile))
            if not r.get("ok") or not r["candidates"]:
                return {"ok": False, "reason": r.get("reason", "not_found"), "suggest": "vision_locate"}
            x, y = r["candidates"][0]["center"]
            tap(int(round(x)), int(round(y)))
            fill(text)
            return {"ok": True, "filled_at": [int(round(x)), int(round(y))]}

        bp = self._bridge_port
        @mcp.tool
        async def human_dom_status() -> dict:
            """human_dom 双维度状态: {installed, connected, profiles, hint}(只统本 server 桥端口的 profile)。
            installed=已装扩展(查该 profile Secure Preferences), connected=当前连着桥。
            关键: installed=true/connected=false ≠ 未安装 —— 别重装, 重开 human_browser_open 或导航到目标页即可(见 hint)。"""
            connected = {c["profile_id"] for c in list(bridge._clients)}
            return build_status(compute_status("~/.fleet/human-dom-ext", bp, connected))

        return ["human_dom_locate", "human_dom_tap", "human_dom_fill", "human_dom_status"]
