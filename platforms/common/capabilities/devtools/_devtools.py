"""devtools 能力：直连 Chrome DevTools Protocol 的 4 个原语。

为什么需要它：社媒运营（公众号等）跑在真实 Chrome 里，需要的是
「读端口 / 看标签 / 在指定 profile 里 eval」，而不是再一次坐标点击。
每个失败都必须**带原因**，调用方靠 `reason` 分支，不靠超时去猜。

四条硬契约（来自 device-operator 的验收清单）：
1. 绝不自动重启浏览器 —— 会让调用方丢掉标签状态，把"未知"变成"更糟"；
2. 结果超限 / 不可序列化 → **报错不截断**（截断的 JSON 会被当成真数据）；
3. 后台冻结标签只报 `unknown`，调用方先 `activate_tab` 再 eval；
4. `port_file_age_ms` 只在 `version_probe_failed` 时出现，且仅作代理指标。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Optional

import _cdp
from _browser_lease import _resolve_profile
from .._base import ORIGIN_SELF_BUILT, CapabilityModule

# 单次调用的时间预算（秒）。全部用单调时钟计时。
ACTIVATE_TIMEOUT = 3.0
EVAL_TIMEOUT = 5.0
FRAME_TIMEOUT = 2.0
DEFAULT_MAX_RESULT_BYTES = 1024 * 1024
DEFAULT_PROBE_BUDGET_MS = 300


# ---------------------------------------------------------------------------
# 纯辅助（可在任何平台单测）
# ---------------------------------------------------------------------------

def resolve_udd(profile: str) -> str:
    """profile 字符串 → Chrome user-data-dir（与 human_browser 同一套解析）。"""
    udd, _pdir, _key = _resolve_profile(profile or "")
    return udd


def normalize_tab(target: dict) -> dict:
    """`/json` 的目标 → 工具契约里的 tab（url 完整不截断）。

    ⚠️ **两套词表，别混用**：

    * CDP `/json` 的原始页对象用 ``id``（还会带 ``webSocketDebuggerUrl``）；
    * 本函数产出的**工具契约**用 ``target_id``（外加 url/title/visibility）。

    真出过一次事故：`smoke_devtools.choose_target()` 的回退分支读 ``tab["id"]``，
    而它拿到的是本函数产出的 tab ⇒ 永远空串、回退分支成了死代码。新增读取 tab 字段的
    代码时，请以这里的返回键为准。
    """
    return {
        "target_id": str(target.get("id") or ""),
        "url": str(target.get("url") or ""),
        "title": str(target.get("title") or ""),
        "visibility": "unknown",
    }


#: 激活失败后的重试次数（真机实测：浏览器忙时 3s 会超时，空闲时 300ms 就够）
ACTIVATE_RETRIES = 1
#: 重试前的等待（秒）
ACTIVATE_RETRY_DELAY_S = 0.2


def activate_with_retry(sock, target_id: str, *,
                        retries: int = ACTIVATE_RETRIES,
                        delay_s: float = ACTIVATE_RETRY_DELAY_S,
                        call=None,
                        sleep=None) -> tuple[Optional[dict], Optional[dict]]:
    """`Target.activateTarget`，失败（超时/CDP 错误）后**重试一次**。

    为什么值得重试：真机同一 profile、10 分钟内，`eval(activate=True)` 与
    `activate_tab` 都出现过 3.3s/3.1s 的 `cdp_timeout`（当时另一个发布流程在跑），
    而空闲时同一调用只要 **296ms**。激活是幂等操作，重试一次比把超时调大一倍更划算
    （最坏情况 3s+0.2s+3s，成功路径基本不变）。

    返回与 `_cdp.call` 相同：``(message, error)``。
    """
    caller = call or _cdp.call
    sleeper = sleep or time.sleep
    params = {"targetId": target_id}
    msg, err = caller(sock, 1, "Target.activateTarget", params, timeout=ACTIVATE_TIMEOUT)
    attempt = 0
    while err is not None and attempt < retries:
        attempt += 1
        sleeper(delay_s)
        msg2, err2 = caller(sock, 2 + attempt, "Target.activateTarget", params,
                            timeout=ACTIVATE_TIMEOUT)
        msg, err = msg2, err2
    return msg, err


def pick_page(pages: list[dict], *, target_id: str = "",
              url_part: str = "") -> tuple[Optional[dict], Optional[str]]:
    """按调用方给的线索选页：target_id 优先，其次 url 子串，最后"唯一页"。

    为什么要这个：真账号 profile 常常有几十个标签页（实测 33 个），"唯一页"假设不成立，
    而 CDP 的 `/json` 不暴露哪个是前台——所以不给线索时只能报 ambiguous；给了线索就精确命中。
    """
    tid = (target_id or "").strip()
    if tid:
        for page in pages:
            if str(page.get("id") or "") == tid:
                return page, None
        return None, "no_target"
    needle = (url_part or "").strip()
    if needle:
        page, hits = match_pages(pages, needle)
        if page is not None:
            return page, None
        return None, ("page_ambiguous" if hits else "no_target")
    return pick_single_page(pages)


def pick_single_page(pages: list[dict]) -> tuple[Optional[dict], Optional[str]]:
    """没有明确目标时选页：唯一页直接用；多页**不猜**，返回 ambiguous。"""
    if not pages:
        return None, "no_target"
    if len(pages) == 1:
        return pages[0], None
    return None, "page_ambiguous"


def match_pages(pages: list[dict], url_part: str) -> tuple[Optional[dict], list[dict]]:
    """按 url 子串找页：返回 (唯一命中 | None, 候选列表)。

    0 命中与多命中都给候选，让调用方能自己决定重试条件，而不是盲探。
    """
    needle = (url_part or "").strip().lower()
    if not needle:
        return None, []
    hits = [p for p in pages if needle in str(p.get("url") or "").lower()]
    if len(hits) == 1:
        return hits[0], hits
    return None, hits


def probe_visibilities(
    pages: list[dict],
    probe: Callable[[dict, float], Optional[str]],
    *,
    budget_s: float,
    max_workers: int = 8,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, str]:
    """并发探测每个页面的 visibility，**总预算不变**。

    为什么并发：真账号 profile 常有几十个标签页（实测 33 个）。串行探测在 300ms 预算里
    只能轮到 1–2 个，其余全 `unknown`——而 unknown 恰恰是"不知道该先 activate 哪个"的来源。
    并发把同样的预算摊给更多页；仍未完成的记 `unknown`，**不重试**（总延迟可控）。

    返回 ``{target_id: "visible"|"hidden"|"unknown"}``；``probe(page, remaining_s)``
    返回三态之一或抛异常（按 unknown 处理）。
    """
    deadline = clock() + max(0.0, float(budget_s))
    results: dict[str, str] = {}
    if not pages:
        return results
    lock = threading.Lock()
    queue = list(pages)
    queue_lock = threading.Lock()

    def worker() -> None:
        while True:
            with queue_lock:
                if not queue:
                    return
                page = queue.pop(0)
            remaining = deadline - clock()
            if remaining <= 0:
                return
            try:
                value = probe(page, remaining)
            except Exception:
                value = None
            visibility = value if value in ("visible", "hidden") else "unknown"
            with lock:
                results[str(page.get("id") or "")] = visibility

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(max(1, min(max_workers, len(pages))))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(max(0.0, deadline - clock()))
    # 没赶上的页一律 unknown（不重试）
    for page in pages:
        results.setdefault(str(page.get("id") or ""), "unknown")
    return results


def value_size_bytes(value: Any) -> int:
    """求值结果的 UTF-8 字节数（超限判据用它，而不是字符数）。"""
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        return 0


def classify_eval_error(error: dict, *, activated: bool) -> str:
    """CDP 层错误 → 稳定 reason 枚举。

    没有激活时的超时无法与"标签被冻结"区分；按契约归为 `frozen_background_tab`
    （调用方该先 activate_tab），而不是笼统的 cdp_timeout。
    """
    message = str((error or {}).get("message") or "")
    if "couldn't be returned by value" in message or "not serializable" in message.lower():
        return "not_serializable"
    if (error or {}).get("reason") == "cdp_timeout" and not activated:
        return "frozen_background_tab"
    return "cdp_timeout"


def find_frame_id(frame_tree: Any, wanted: str) -> Optional[str]:
    """在 Page.getFrameTree 的结果里按 frameId 精确匹配或 url 子串匹配。"""
    needle = (wanted or "").strip().lower()
    if not needle:
        return None

    def walk(node: Any) -> Optional[str]:
        if not isinstance(node, dict):
            return None
        frame = node.get("frame") or {}
        fid = str(frame.get("id") or "")
        url = str(frame.get("url") or "").lower()
        if fid and fid.lower() == needle:
            return fid
        if fid and needle in url:
            return fid
        for child in node.get("childFrames") or []:
            found = walk(child)
            if found:
                return found
        return None

    return walk(frame_tree)


# ---------------------------------------------------------------------------
# 能力模块
# ---------------------------------------------------------------------------

class DevtoolsCapability(CapabilityModule):
    id = "devtools"
    display_name = "浏览器 devtools(CDP 直连: 端口 / 标签 / eval)"
    origin = ORIGIN_SELF_BUILT
    skill = "using-human-browser"
    platforms = ["windows", "macos"]
    usage_hint = (
        "真账号 Chrome 的 CDP 原语, 与 human_browser 共用同一 profile 语义。"
        "cdp_port(profile)→端口/存活/失败原因(调用方别缓存端口, 每次重启都会变);"
        "list_tabs(profile)→标签清单(后台冻结标签 visibility=unknown, 不挂死);"
        "activate_tab(profile, url_part|target_id)→按 url 子串或 target_id 激活(多命中报 PAGE_AMBIGUOUS);"
        "eval_in_profile(profile, js)→在该 profile 的页面里求值(默认先激活, 后台只读需显式 activate=False)。"
        "只读/写页面用它们比截图+坐标稳; 绝不自动重启浏览器。"
    )

    def description_for(self) -> str:  # pragma: no cover - 人读
        return "自建: 纯 stdlib CDP 客户端(无 websockets/cryptography 依赖), 复用 human_dom 的端口探测与 ws 握手。"

    def availability(self) -> tuple[bool, str]:
        # 纯 stdlib；只要平台适用就能用（端口/浏览器是否活着由工具自己报 reason）
        return True, ""

    def register(self, mcp) -> list[str]:  # noqa: C901 - 四个工具各自独立，线性展开更可读
        @mcp.tool
        def cdp_port(profile: str = "") -> dict:
            """Chrome 调试端口是否可用：{ok, alive, port, ws_url, browser, reason, probe_ms}。

            `reason` 稳定枚举：`port_file_missing`（没开浏览器，先 human_browser_open）/
            `version_probe_failed`（有端口文件但探活失败，可能陈旧或正在启动）/
            `handshake_timeout`（端点活着但拿不到可连的 ws 地址）。
            **端口每次重启都会变，调用方不许缓存**；本工具绝不自动重启浏览器。
            `port_file_age_ms` 只在 `version_probe_failed` 时出现（代理指标，不是事实）。
            """
            started = time.monotonic()
            udd = resolve_udd(profile)
            port = _cdp.read_port_once(udd)
            if port is None:
                return {"ok": False, "alive": False, "port": None,
                        "reason": "port_file_missing",
                        "probe_ms": int((time.monotonic() - started) * 1000)}
            probe_start = time.monotonic()
            info, reason = _cdp.probe_version(port)
            probe_ms = int((time.monotonic() - probe_start) * 1000)
            if info is not None and reason is None:
                return {"ok": True, "alive": True, "port": port,
                        "ws_url": str(info.get("webSocketDebuggerUrl") or ""),
                        "browser": str(info.get("Browser") or ""),
                        "probe_ms": probe_ms}
            result = {"ok": False, "alive": False, "port": port,
                      "reason": reason or "version_probe_failed", "probe_ms": probe_ms}
            if info is not None:
                result["browser"] = str(info.get("Browser") or "")
            if result["reason"] == "version_probe_failed":
                age_ms, note = _cdp.port_file_age_ms(udd)
                if age_ms is not None:
                    result["port_file_age_ms"] = age_ms
                if note:
                    result["note"] = note
            return result

        @mcp.tool
        def list_tabs(profile: str = "", probe_budget_ms: int = DEFAULT_PROBE_BUDGET_MS) -> dict:
            """列出该 profile 的页面标签：{ok, tabs:[{target_id,url,title,visibility}], probe_ms, duration_ms}。

            `visibility ∈ visible | hidden | unknown`。探测**并发**进行（有界并发 8），**总预算**默认 300ms；
            没赶上的记 `unknown` 且**不重试**（总延迟可控）。
            ⚠️ 拿到 `unknown` **不要**以为 `activate_tab` 就能让 eval 选对页：CDP 的 `/json` 不暴露
            哪个是前台，选页只能靠 `eval_in_profile(url_part=…|target_id=…)` 显式指定。
            真账号 profile 常有几十个标签页，串行探测会让绝大多数变成 unknown，故采用并发。
            不给 `frozen` 布尔：探针本身会挂在冻结标签上，猜一个 false 比 unknown 更坏。
            `url` 完整不截断（截断会让调用方匹配误判）。
            """
            started = time.monotonic()
            udd = resolve_udd(profile)
            port = _cdp.read_port_once(udd)
            if port is None:
                return {"ok": False, "tabs": [], "probe_ms": 0,
                        "reason": "port_file_missing",
                        "duration_ms": int((time.monotonic() - started) * 1000)}
            _info, reason = _cdp.probe_version(port)
            if reason:
                return {"ok": False, "tabs": [], "probe_ms": 0, "reason": reason,
                        "duration_ms": int((time.monotonic() - started) * 1000)}
            pages, reason = _cdp.page_targets(port)
            if reason:
                return {"ok": False, "tabs": [], "probe_ms": 0, "reason": reason,
                        "duration_ms": int((time.monotonic() - started) * 1000)}
            budget_s = max(0, int(probe_budget_ms)) / 1000.0
            probe_start = time.monotonic()

            def _probe_one(page: dict, remaining: float) -> Optional[str]:
                sock = None
                try:
                    sock = _cdp.ws_connect(page["webSocketDebuggerUrl"], timeout=remaining)
                    msg, _err = _cdp.call(
                        sock, 1, "Runtime.evaluate",
                        {"expression": "document.visibilityState", "returnByValue": True},
                        timeout=remaining,
                    )
                    return (((msg or {}).get("result") or {}).get("result") or {}).get("value")
                finally:
                    if sock is not None:
                        _cdp.close_quietly(sock)

            visibility = probe_visibilities(pages, _probe_one, budget_s=budget_s)
            tabs = []
            for page in pages:
                tab = normalize_tab(page)
                tab["visibility"] = visibility.get(str(page.get("id") or ""), "unknown")
                tabs.append(tab)
            return {"ok": True, "tabs": tabs,
                    "probe_ms": int((time.monotonic() - probe_start) * 1000),
                    "duration_ms": int((time.monotonic() - started) * 1000)}

        @mcp.tool
        def activate_tab(profile: str = "", url_part: str = "",
                         target_id: str = "") -> dict:
            """按 url 子串激活标签：{ok, target_id, url}。

            0 命中 → `{ok:false, reason:"no_target", candidates:[...]}`；
            多命中 → `{ok:false, reason:"PAGE_AMBIGUOUS", candidates:[...]}`（不猜）；
            也可直接给 `target_id`（来自 `list_tabs`）跳过子串匹配。
            验收方式：激活后再 `list_tabs`，目标 tab 应为 `visible`。
            """
            udd = resolve_udd(profile)
            sock, port = _cdp.connect_browser(udd, ACTIVATE_TIMEOUT)
            if sock is None:
                return {"ok": False, "reason": "port_file_missing" if _cdp.read_port_once(udd) is None
                        else "version_probe_failed"}
            try:
                pages, reason = _cdp.page_targets(port)
                if reason:
                    return {"ok": False, "reason": reason}
                page, reason = pick_page(pages, target_id=target_id, url_part=url_part)
                if page is None:
                    # `activate_tab` 的历史契约用大写 `PAGE_AMBIGUOUS`（文档与真机证据都按它写），
                    # 而 `eval_in_profile` 用小写 `page_ambiguous`。这里**保持各自既有口径**，
                    # 只把新的 `target_id` 能力加进来。
                    return {"ok": False,
                            "reason": "PAGE_AMBIGUOUS" if reason == "page_ambiguous" else reason,
                            "candidates": [normalize_tab(p) for p in pages[:10]]}
                _msg, err = activate_with_retry(sock, page["id"])
                if err:
                    return {"ok": False, "reason": classify_eval_error(err, activated=True),
                            "error": err.get("message")}
                return {"ok": True, "target_id": page["id"], "url": str(page.get("url") or "")}
            finally:
                _cdp.close_quietly(sock)

        @mcp.tool
        def eval_in_profile(profile: str = "", js: str = "", frame: str = "",
                            activate: bool = True,
                            max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
                            url_part: str = "", target_id: str = "") -> dict:
            """在该 profile 的页面里求值：{ok, value, activated, size_bytes, reason?}。

            - 默认先 `Target.activateTarget`（后台标签在冻结时 eval 会挂）；
              显式 `activate=False` 时若超时 → `reason:"frozen_background_tab"`；
            - 结果 `returnByValue`：超过 `max_result_bytes` → `result_too_large`（**不截断**）；
              不可序列化 → `not_serializable`；JS 抛错 → `js_exception`；
            - `frame` 按 frameId 精确或 url 子串匹配，找不到 → `frame_not_found`；
            - 选页：给 `target_id` 或 `url_part`（来自 list_tabs）就精确命中；
              都不给且有多页 → `page_ambiguous`（真账号 profile 常有几十个标签页）。
            """
            started = time.monotonic()
            udd = resolve_udd(profile)
            browser_sock, port = _cdp.connect_browser(udd, ACTIVATE_TIMEOUT)
            if browser_sock is None:
                return {"ok": False, "activated": False,
                        "reason": "port_file_missing" if _cdp.read_port_once(udd) is None
                        else "version_probe_failed"}
            # 真机反馈：偶发 9.3s（贴着超时线）。没有分解只能猜，故把 connect / activate /
            # eval 三段耗时都带回去，下次慢的时候能直接看出是哪一段。
            t_after_connect = time.monotonic()
            activated = False
            try:
                pages, reason = _cdp.page_targets(port)
                if reason:
                    return {"ok": False, "activated": False, "reason": reason}
                page, reason = pick_page(pages, target_id=target_id, url_part=url_part)
                if page is None:
                    return {"ok": False, "activated": False, "reason": reason,
                            "hint": ("pass url_part= (substring) or target_id= from list_tabs "
                                     "when the profile has several tabs"),
                            "candidates": [normalize_tab(p) for p in pages[:10]]}
                activated = bool(activate)
                if activate:
                    _msg, err = activate_with_retry(browser_sock, page["id"])
                    if err:
                        return {"ok": False, "activated": False,
                                "reason": classify_eval_error(err, activated=True),
                                "error": err.get("message")}
            finally:
                _cdp.close_quietly(browser_sock)
            t_after_activate = time.monotonic()

            sock = None
            try:
                sock = _cdp.ws_connect(page["webSocketDebuggerUrl"], timeout=EVAL_TIMEOUT)
                params: dict[str, Any] = {
                    "expression": js, "returnByValue": True, "awaitPromise": True,
                }
                if frame:
                    tree_msg, err = _cdp.call(sock, 2, "Page.getFrameTree", timeout=FRAME_TIMEOUT)
                    if err:
                        return {"ok": False, "activated": activated,
                                "reason": classify_eval_error(err, activated=activated),
                                "error": err.get("message")}
                    frame_id = find_frame_id((tree_msg or {}).get("result"), frame)
                    if not frame_id:
                        return {"ok": False, "activated": activated,
                                "reason": "frame_not_found", "frame": frame}
                    world_msg, err = _cdp.call(
                        sock, 3, "Page.createIsolatedWorld",
                        {"frameId": frame_id, "worldName": "fleet-eval"}, timeout=FRAME_TIMEOUT,
                    )
                    context_id = (((world_msg or {}).get("result") or {}).get("executionContextId"))
                    if err or context_id is None:
                        return {"ok": False, "activated": activated,
                                "reason": classify_eval_error(err or {"reason": "cdp_error"},
                                                              activated=activated),
                                "error": (err or {}).get("message") or "createIsolatedWorld failed"}
                    params["contextId"] = context_id

                msg, err = _cdp.call(sock, 4, "Runtime.evaluate", params, timeout=EVAL_TIMEOUT)
                if err:
                    return {"ok": False, "activated": activated,
                            "reason": classify_eval_error(err, activated=activated),
                            "error": err.get("message")}
                result = ((msg or {}).get("result") or {})
                if result.get("exceptionDetails"):
                    details = result["exceptionDetails"]
                    text = (((details.get("exception") or {}).get("description"))
                            or details.get("text") or "js exception")
                    return {"ok": False, "activated": activated,
                            "reason": "js_exception", "error": str(text)}
                value = ((result.get("result") or {}).get("value"))
                size = value_size_bytes(value)
                if size > int(max_result_bytes):
                    return {"ok": False, "activated": activated,
                            "reason": "result_too_large", "size_bytes": size,
                            "max_result_bytes": int(max_result_bytes)}
                now = time.monotonic()
                return {"ok": True, "value": value, "activated": activated,
                        "size_bytes": size,
                        "elapsed_ms": int((now - started) * 1000),
                        "timings": {
                            "connect_ms": int((t_after_connect - started) * 1000),
                            "activate_ms": int((t_after_activate - t_after_connect) * 1000),
                            "eval_ms": int((now - t_after_activate) * 1000),
                        }}
            except Exception as exc:
                return {"ok": False, "activated": activated,
                        "reason": "cdp_timeout", "error": f"{type(exc).__name__}: {exc}"}
            finally:
                if sock is not None:
                    _cdp.close_quietly(sock)

        return ["cdp_port", "list_tabs", "activate_tab", "eval_in_profile"]
