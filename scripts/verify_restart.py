#!/usr/bin/env python3
"""重启后验证：证明"**新代码真的进了内存**"，而不只是"服务还活着"。

为什么需要它：`/health` 200、工具数 91、审计有新增行 —— 这三条**旧进程全都满足**
（health 本来 200、工具数本来就是 91、审计本来就在写）。它们只能证明"有个进程在服务"，
证明不了"重启后跑的是新码"。

**唯一定性判据是 pid 变了**：审计每行都带 `pid`，重启会换进程号。所以：

| # | 检查 | 证明什么 |
|---|---|---|
| 1 | `/health` 返回 200 | 服务在监听 |
| 2 | `list_capabilities()` 工具数 == 期望 | 功能面完整 |
| 3 | 审计文件有新行 | 审计中间件在写 |
| 4 | **新行 pid ≠ 重启前 pid** | **新代码进了内存**（关键） |

用法::

    # 重启前先记下 pid 与 git HEAD（回滚要有据可查）
    python3 scripts/probe_multi.py --url http://<host>:<port>/mcp \
        --cases <(echo '[{"tool":"run_shell","args":{"script":"..."}}]')

    # 重启后
    python3 scripts/verify_restart.py --url http://test-win11:8766/mcp \
        --old-pid 266180 --expect-tools 91 --expect-holder

退出码：

| 码 | 含义 |
|---|---|
| 0 | 全部通过（人工模式允许有 SKIP） |
| 1 | 有 FAIL |
| 4 | **≥1 个 SKIP 且开了 `--strict`** —— "未完整"，**CI 里不应报绿** |
| 2 | 用法错 / 连不上 |

> 为什么不用 3：`smoke_ops` / `smoke_devtools` 里 **3 = 「设备上跑的不是这批代码」**。
> 同一台机器的 CI 里两个 3 指向完全不同的事，排障的人看到 3 会先去查版本而不是看 skip。
> 所以"未完整"独占 **4**，3 留给"版本/环境不符"那一族。

> 为什么要单独一档：只在人工模式下"这次没验成不算失败"才合理；进了 CI，退出码 0 会被读成"通过"，
> 一个长期 SKIP 的检查就会静默退化成一盏永远亮的绿灯。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _expectations import expect_holder_for, expected_tools_for  # noqa: E402
from _mcp_probe import load_transport, payload_of  # noqa: E402

#: 读审计尾部的 PowerShell 片段（设备是 Windows；mac/linux 用 --audit-cmd 覆盖）
WIN_TAIL = ('$p = "$env:USERPROFILE\\.agent-fleet\\tool-audit.jsonl"; '
            'if (Test-Path $p) { Get-Content $p -Tail 5 } else { "" }')


def parse_audit_lines(stdout: str) -> list[dict]:
    """从 `Get-Content -Tail` 的纯文本里解析出审计记录（坏行跳过）。"""
    out: list[dict] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("tool"):
            out.append(rec)
    return out


def latest_pid(records: list[dict]) -> Optional[int]:
    """最后一条记录的 pid（没有则 None）。"""
    for rec in reversed(records):
        pid = rec.get("pid")
        if isinstance(pid, int):
            return pid
    return None


def count_tools(caps: dict) -> int:
    return sum(len(c.get("tools") or []) for c in (caps.get("capabilities") or []))


def health_ok(url: str, timeout_s: float = 5.0) -> tuple[bool, str]:
    """`/health` 探活（把 MCP 路径换掉）。"""
    base = url.rstrip("/")
    if base.endswith("/mcp"):
        base = base[: -len("/mcp")]
    try:
        with urllib.request.urlopen(base + "/health", timeout=timeout_s) as resp:  # noqa: S310
            return resp.status == 200, f"HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def normalize_build(value: str) -> str:
    """统一形状再比较：小写、取前 7 位（短 HEAD 7 / 长 HEAD 40 / 自定义串都可比）。

    之前直接用 `==` 比较，会出现"同一个提交因形状不同（7 位 vs 40 位）被判不等"的假红。
    """
    text = (value or "").strip().lower()
    return text[:7] if len(text) >= 7 else text


def build_verdict(pid_changed: bool, records: list[dict], expect_build: str,
                  new_pid: Optional[int]) -> tuple[bool, str, bool]:
    """断言"**新进程跑的确实是期望的那份代码**"。

    返回 `(ok, detail, skipped)`。这是**直接读数**，不是代理指标：
    审计的每条记录都带 `build`（git 短 HEAD），所以能断言"新 pid 的 build == 期望 commit"，
    而不是"某个字段出现了，所以大概是新码"。

    旧版本的记录没有 `build` ⇒ 记 skipped（不能因此判失败，那会把"没法验"读成"验不过"）。
    """
    if not pid_changed:
        return True, "skipped: pid 未变（旧码），不判 build", True
    if not expect_build:
        return True, "skipped: 未指定 --expect-build", True
    for rec in reversed(records):
        if rec.get("pid") == new_pid and rec.get("build"):
            got = str(rec["build"])
            if rec.get("dirty") is True:
                # 工作区有未提交改动 ⇒ HEAD 相同但代码可能不同，build 断言不可信
                return True, (f"skipped: 工作区 dirty（build={got} 只代表 HEAD，"
                              f"实际代码可能已改）"), True
            if normalize_build(got) == normalize_build(expect_build):
                return True, f"build={got}（与期望 {expect_build} 一致）", False
            return False, f"build={got}，期望 {expect_build}（跑的不是期望的代码）", False
    return True, "skipped: 新 pid 的记录里没有 build 字段（旧版审计）", True


def holder_verdict(pid_changed: bool, acquired: bool, records: list[dict],
                   marker: str) -> tuple[bool, str]:
    """判定 `holder` 字段是否落地——**有序两段**，且证据由本脚本自己造。

    为什么要拆：原措辞「未出现——说明跑的仍是旧码**或**该会话未 acquire」把两条因果绑在一起，
    红的时候分不出是"重启没生效"还是"验证方法没造出证据"，而这两者的下一步动作完全不同。

    - `pid_changed == False` ⇒ 直接判「旧码，重启未生效」，**不再看 holder**；
    - `pid_changed == True` ⇒ 只看本脚本以 `marker` 身份 acquire 之后写下的那条记录。
    """
    if not pid_changed:
        return True, "skipped: pid 未变（旧码），不判 holder"
    if not acquired:
        return True, "skipped: 设备被他人持有，无法自证（不代表字段未落地）"
    hit = [r for r in records if r.get("holder") == marker]
    if hit:
        return True, f"已自证：holder={marker}"
    return False, f"未找到 holder={marker} 的记录——字段未落地（重启成功但跑的是旧码？）"


async def _read_audit(call, audit_cmd: str) -> str:
    """`call` 已经做过 payload 归一化；**不要**再包一层 payload_of（会把 dict 变成 []）。"""
    payload = await call("run_shell", {"script": audit_cmd})
    if isinstance(payload, dict):
        return str(payload.get("stdout") or "")
    return ""


async def run_checks(url: str, old_pid: Optional[int], expect_tools: Optional[int],
                     expect_holder: bool, audit_cmd: str,
                     expect_build: str = "") -> list[dict]:
    results: list[dict] = []

    def add(check: str, ok: bool, detail: str, skipped: bool = False) -> None:
        """三状态：pass / fail / **skipped（本次没能验）**。

        operator 的补充：判据要分「**能力不足**」与「**结论为否**」两类。
        设备被占、没有 about:blank、acquire 失败 —— 这些是"没验成"，不是"验不过"；
        硬塞进红或绿都会误导下一步动作。
        """
        results.append({"check": check, "ok": bool(ok), "skipped": bool(skipped),
                        "detail": detail})

    ok, detail = health_ok(url)
    add("/health 200", ok, detail)

    transport = load_transport()
    if transport is None:
        add("list_capabilities", False, "MCP client SDK 不可用")
        return results
    from mcp import ClientSession

    async with transport(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool: str, args: dict) -> Any:
                return payload_of(await session.call_tool(tool, args))

            caps = await call("list_capabilities", {})
            tools = count_tools(caps if isinstance(caps, dict) else {})
            if expect_tools is None:
                add("工具数", True, f"实际 {tools} / 期望（未指定，不做判定）")
            else:
                add("工具数", tools == expect_tools, f"实际 {tools} / 期望 {expect_tools}")

            # 触发一次调用，保证有"新行"
            await call("get_status", {})
            stdout = await _read_audit(call, audit_cmd)
            records = parse_audit_lines(stdout)
            pid = latest_pid(records)
            add("审计有新行", bool(records), f"{len(records)} 行（tail 5）")
            pid_changed = old_pid is None or (pid is not None and pid != old_pid)
            add("新码进内存（pid 变化）", pid_changed,
                f"重启后 pid={pid}，重启前 pid={old_pid}")

            ok_build, detail_build, skip_build = build_verdict(
                pid_changed, records, expect_build, pid)
            add("运行的代码版本（build）", ok_build, detail_build, skipped=skip_build)

            if expect_holder:
                # 证据自己造：无条件 acquire 一次（唯一名字），再 release，然后读回审计
                marker = f"verify-restart-{os.getpid()}-{int(time.time())}"
                acquired = False
                if pid_changed:
                    acq = await call("acquire", {"holder_name": marker})
                    acquired = bool(isinstance(acq, dict) and acq.get("acquired"))
                    if acquired:
                        await call("release", {"holder_name": marker})
                        stdout = await _read_audit(call, audit_cmd)
                        records = parse_audit_lines(stdout)
                ok, detail = holder_verdict(pid_changed, acquired, records, marker)
                add("holder 字段落地（自证）", ok, detail, skipped=detail.startswith("skipped"))
    return results


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a device restart actually loaded new code")
    ap.add_argument("--url", required=True, help="e.g. http://test-win11:8766/mcp")
    ap.add_argument("--old-pid", type=int, default=None,
                    help="pid observed BEFORE the restart (the key evidence)")
    ap.add_argument("--expect-tools", type=int, default=None,
                    help="expected tool count; omit to look it up in scripts/_expectations.py by host")
    ap.add_argument("--expect-holder", action="store_true",
                    help="require the holder field in the new audit lines (auto per host when omitted)")
    ap.add_argument("--expect-build", default="",
                    help="expected git short HEAD the device should be running (asserted via audit build field)")
    ap.add_argument("--strict", action="store_true",
                    help="CI 模式：有 SKIP 时不报绿，而是以退出码 3 表示「未完整」")
    ap.add_argument("--audit-cmd", default=WIN_TAIL,
                    help="command run on the device to print the audit tail")
    args = ap.parse_args(argv)

    expect_tools = args.expect_tools if args.expect_tools is not None else expected_tools_for(args.url)
    expect_holder = args.expect_holder or expect_holder_for(args.url)
    try:
        results = asyncio.run(asyncio.wait_for(
            run_checks(args.url, args.old_pid, expect_tools,
                       expect_holder, args.audit_cmd, args.expect_build), timeout=120))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    for row in results:
        label = "SKIP" if row.get("skipped") else ("PASS" if row["ok"] else "FAIL")
        print(label, row["check"], "|", row["detail"])
    failed = [r for r in results if not r["ok"]]
    skipped = [r for r in results if r.get("skipped")]
    passed = len(results) - len(failed) - len(skipped)
    print(f"\nSUMMARY: {passed} passed, {len(failed)} failed, {len(skipped)} skipped")
    if failed:
        return 1
    if skipped and args.strict:
        print("STRICT: 有检查被 SKIP ⇒ 判「未完整」，不报绿（CI 模式）", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
