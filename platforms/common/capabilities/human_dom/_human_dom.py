"""human_dom 能力: 注册 human_dom_locate/tap/fill。靠 server 注入 tap_fn/type_fn + bridge。"""
from __future__ import annotations
from .._base import CapabilityModule, ORIGIN_SELF_BUILT
from ._locate import resolve_locate


class HumanDomCapability(CapabilityModule):
    id = "human_dom"
    display_name = "浏览器 human_dom(只读 DOM 定位, 配合 human_browser)"
    origin = ORIGIN_SELF_BUILT
    skill = "using-human-dom"
    platforms = None

    def __init__(self, bridge, tap_fn, type_fn):
        self._bridge = bridge; self._tap = tap_fn; self._type = type_fn
        self.description = "只读 DOM 拿元素屏幕坐标(扩展 content script), 操作仍走 OS 级 tap/type; 未命中落 vision_locate。"

    def availability(self):
        # 只探注册期能定的依赖(WS 库)。"扩展是否在线"是运行时 locate 的事, 不在此判。
        try:
            import starlette.websockets  # noqa: F401
            return True, ""
        except Exception as e:
            return False, f"starlette WS 不可用: {e}"

    def register(self, mcp) -> list[str]:
        bridge, tap, type_ = self._bridge, self._tap, self._type

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
            """定位 + 点击聚焦 + OS 级输入。"""
            r = await resolve_locate(bridge, query, css=css or None)
            if not r.get("ok") or not r["candidates"]:
                return {"ok": False, "reason": r.get("reason", "not_found"), "suggest": "vision_locate"}
            x, y = r["candidates"][0]["center"]
            tap(int(round(x)), int(round(y)))
            type_(text)
            return {"ok": True, "filled_at": [int(round(x)), int(round(y))]}

        return ["human_dom_locate", "human_dom_tap", "human_dom_fill"]
