"""human_dom 能力: 注册 human_dom_locate/tap/fill。靠 server 注入 tap_fn/fill_fn + bridge。"""
from __future__ import annotations
from .._base import CapabilityModule, ORIGIN_SELF_BUILT
from ._locate import resolve_locate


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

    def __init__(self, bridge, tap_fn, fill_fn):
        self._bridge = bridge; self._tap = tap_fn; self._fill = fill_fn
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
        async def human_dom_locate(query: str, css: str = "", max_results: int = 10) -> dict:
            """只读 DOM 定位: 按文字/aria-label/placeholder(或 css)找元素, 返回屏幕坐标候选。
            先 human_browser_open 并等页面 load。未命中/桥未连会建议改用 vision_locate。"""
            return await resolve_locate(bridge, query, css=css or None, max_results=max_results)

        @mcp.tool
        async def human_dom_tap(query: str, nth: int = 0, css: str = "") -> dict:
            """定位 + OS 级点击(locate+tap 合一缩小漂移窗)。"""
            r = await resolve_locate(bridge, query, css=css or None)
            if not r.get("ok") or not r["candidates"]:
                return {"ok": False, "reason": r.get("reason", "not_found"), "suggest": "vision_locate"}
            x, y = r["candidates"][min(nth, len(r["candidates"]) - 1)]["center"]
            tap(int(round(x)), int(round(y)))
            return {"ok": True, "tapped": [int(round(x)), int(round(y))]}

        @mcp.tool
        async def human_dom_fill(query: str, text: str, css: str = "") -> dict:
            """定位 + 点击聚焦 + OS 级填充(全选 + 剪贴板粘贴, 覆盖式, 支持中文)。"""
            r = await resolve_locate(bridge, query, css=css or None)
            if not r.get("ok") or not r["candidates"]:
                return {"ok": False, "reason": r.get("reason", "not_found"), "suggest": "vision_locate"}
            x, y = r["candidates"][0]["center"]
            tap(int(round(x)), int(round(y)))
            fill(text)
            return {"ok": True, "filled_at": [int(round(x)), int(round(y))]}

        return ["human_dom_locate", "human_dom_tap", "human_dom_fill"]
