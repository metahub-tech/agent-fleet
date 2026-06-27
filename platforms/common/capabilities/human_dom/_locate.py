"""locate 编排: query → bridge.locate → 候选映射屏幕坐标 → 结构化结果/兜底。永不抛到 server。"""
from __future__ import annotations
from ._geom import viewport_to_screen

async def resolve_locate(bridge, query, css=None, max_results=10, profile_id="default", timeout=3.0) -> dict:
    try:
        reply = await bridge.locate(query, css=css, max_results=max_results, profile_id=profile_id, timeout=timeout)
    except TimeoutError:
        return {"ok": False, "reason": "no_tab_for_profile", "profile": profile_id,
                "suggest": "该 profile 可能没起浏览器/没导航到目标页，或没装 human_dom 扩展(每 profile 单独装,见 using-human-dom);或 vision_locate"}
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
