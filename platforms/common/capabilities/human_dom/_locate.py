"""locate 编排: query → bridge.locate → 候选映射屏幕坐标 → 结构化结果/兜底。永不抛到 server。"""
from __future__ import annotations
from ._geom import viewport_to_screen

async def resolve_locate(bridge, query, css=None, max_results=10, timeout=3.0) -> dict:
    try:
        reply = await bridge.locate(query, css=css, max_results=max_results, timeout=timeout)
    except TimeoutError:
        return {"ok": False, "reason": "bridge_no_active_tab",
                "suggest": "vision_locate",
                "hint": "页面未就绪或无 active tab 的扩展连入; 先 take_screenshot 确认页面 load, 或用 vision_locate"}
    except Exception as e:
        return {"ok": False, "reason": f"bridge_error:{type(e).__name__}", "suggest": "vision_locate"}
    if not reply.get("ok"):
        return {"ok": False, "reason": "not_found", "dom_sample": reply.get("dom_candidates", []),
                "suggest": "vision_locate"}
    geom = reply["viewport"]
    out = []
    for c in reply.get("candidates", [])[:max_results]:
        m = viewport_to_screen(c["rectViewport"], geom)
        out.append({"text": c.get("text"), "role": c.get("role"),
                    "center": m["center"], "box": m["box"],
                    "visible": c.get("visible", True), "clickable": c.get("clickable", True)})
    return {"ok": True, "candidates": out}
