# 多 MCP 端点（`/mcp` + `/gui/mcp` …）设计备忘

> 状态：**未实施**。本文只记录 2026-11-28 的一次本地 spike 结果与硬约束，
> 供"是否拆端点 / 怎么拆"的决策使用。决策数据来自 `docs/tool-audit.md` 的调用审计。

## 动机

设备侧工具面 91 个、schema 约 21 KB（≈7k tokens），会全部注入每个接入 agent 的上下文。
若按用途拆成多个端点，发布型 agent 只需挂其中一小部分。

## 已实测（spike，同进程两个 FastMCP 实例挂在同一个 uvicorn 上）

| 假设 | 实测结果 |
|---|---|
| 同进程可挂多个端点，且工具可从主 server **复制**（`get_tool` + `add_tool`） | ✅ 复制了 9 个 GUI 工具，`/gui/mcp` 独立可用 |
| 两个端点**共用**模块级能力注册表（发现层不分裂） | ✅ 在 `/ops/mcp` 调 `list_capabilities` 返回 core 的 49 个工具 |
| **租约按 MCP session 绑定 ⇒ 跨端点调用被拒** | ✅ 在 `/ops/mcp` `acquire` 后，于 `/gui/mcp` 调 `get_screen_size` 得到 `{reason: "device_leased"}` |
| 审计（同进程）写同一份文件 | ✅ 两个端点的调用都落在同一个 `tool-audit.jsonl` |

复现脚本要点（约 60 行）：`srv.mcp` 作主端点 + `FastMCP("gui")` 复制工具 + 两段
`add_middleware(LeaseGate(...))` + `Starlette(Mount("/ops", main_http), Mount("/gui", gui_http))`
+ **合并 lifespan**（`main_http.router.lifespan_context` 套 `gui_http.router.lifespan_context`，
漏了会报 "StreamableHTTPSessionManager task group was not initialized"）。

## 三条硬约束（按严重度）

### 1. 租约按 session 绑定 ⇒ 跨端点会被判另一个人

`LeaseGate` 把租约绑到 MCP session id。拆端点后，agent 在 A 端点 `acquire`、到 B 端点调用，
B 端点的 session id 不同 ⇒ `device_leased`。

可选解法（都需要负责人拍板，涉及安全语义）：

| 方案 | 代价 |
|---|---|
| 每个端点各自 `acquire` | agent 侧要写两次；且两个端点会"同时持有"互不知情 |
| 租约改绑 **holder_name**（客户端声明的身份） | holder_name 本就不是凭证；但能顺带修掉"**客户端重连后 lease 失效**"这个既有缺陷 |
| 端点间共享 session（不可行） | MCP session 就是按 HTTP 会话建立的 |

> operator 的补充：重连换 session id 也会让旧租约"消失"（他今天真实遇到，靠同 `holder_name`
> 重新 `acquire` 续上）。所以"按 holder_name 绑定"不只是为多端点，它同时修一个既有缺陷。

### 2. `list_capabilities` 在子端点上会**说谎**

它是模块级能力注册表的口径 ⇒ 在只挂 9 个工具的 `/gui/mcp` 上调用，它仍报告全部 91 个工具
（实测：`/ops/mcp` 返回 49 个 core 工具）。而如果子端点**不挂**这个工具，调用会直接报
tool-not-found（实测拿到的是 `{"_raw": …}` 错误体）。

⇒ 子端点要么提供一个**端点自知**的变体（返回 `profile=ops` + 本端点工具清单），
要么在文档里明确"发现口径以 `/mcp` 为准"。这必须在实施前定下来。

### 3. 操作顺序无法跨端点保证

"先 `activate_tab` 切前台，再 `clipboard_set_html` + `press_key ctrl+v`"是一串**有顺序**的动作；
拆到两个端点后，两次调用之间没有顺序保证（也无法共享"前台已切"的隐含状态）。
剪贴板本身是系统级资源（跨端点共享，没问题），但**顺序**不是。

## 决策前要量的数据（`scripts/analyze_tool_audit.py`）

```bash
python3 scripts/analyze_tool_audit.py --days 7 --profiles ops,gui,human --sessions 10
```

- `--profiles`：候选端点覆盖了多少真实调用（覆盖 ≥95% 且工具数明显更少才值得拆）；
- `--sessions`：**同一会话内是否跨组**——跨组的会话拆开后要多次连接，且会撞上约束 1。

## 结论（当前）

在约束 1 未定案前**不要拆**。审计先跑几天，等 `--sessions` 数据显示"大多数会话不跨组"，
再讨论是否改租约绑定语义。
