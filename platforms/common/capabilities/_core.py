"""core capability — always-on device control (metadata-only).

core's tools are defined inline in each platform server; this module carries
only metadata for list_capabilities() (register() -> [] keeps core untouched).
"""
from __future__ import annotations

from ._base import CapabilityModule, ORIGIN_SELF_BUILT, CORE_ID


class CoreCapability(CapabilityModule):
    id = CORE_ID
    origin = ORIGIN_SELF_BUILT

    def __init__(self, skill: str | None = None, display_name: str = "核心设备控制"):
        self.skill = skill
        self.display_name = display_name
        self.description = (
            "操控本设备的基础能力:截图、坐标点击/滑动、键盘输入、"
            "element-action 语义点击(find_elements/tap_element)、shell 执行、"
            "文件读写、应用生命周期、设备占用状态。"
        )
        self.usage_hint = (
            "桌面操作优先 element-first:tap_element(query)/find_elements(query) 语义定位;"
            "无匹配或歧义再 take_screenshot + tap(x,y) 坐标兜底。"
        )
