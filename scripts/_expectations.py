"""设备验证的**期望值唯一来源**（改能力后就改这里，别散落在脚本里）。

为什么单独放：工具数会随能力增减变化（今天 91 = core 49 + agent_browser 29 +
human_browser 1 + vision 3 + human_dom 5 + devtools 4）。把它硬编码在验证脚本里，
下次加/关一个能力就会变成**假红**；更糟的是有人为了让检查变绿去改数字。

用法：`verify_restart.py` 不传 `--expect-tools` 时按 URL 主机名查这张表；
查不到就打印"期望（未指定）"，不做判定——**宁可不说，也不猜**。
"""

#: 每台设备的期望工具面（运行时 `list_capabilities()` 的口径）。
EXPECTED_TOOLS: dict[str, int] = {
    # 2026-11-28 实测：core 49 + agent_browser 29 + human_browser 1 + vision 3 + human_dom 5 + devtools 4
    "test-win11": 91,
}

#: 期望的 holder 字段是否已落地（审计升级后应为 True）
EXPECT_HOLDER: dict[str, bool] = {
    "test-win11": True,
}


def expected_tools_for(url: str) -> int | None:
    """按 URL 里的主机名查期望工具数；查不到返回 None（调用方不应据此判红）。"""
    for host, count in EXPECTED_TOOLS.items():
        if host in (url or ""):
            return count
    return None


def expect_holder_for(url: str) -> bool:
    for host, flag in EXPECT_HOLDER.items():
        if host in (url or ""):
            return flag
    return False
