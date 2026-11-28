# 工具调用审计（决定端点怎么拆的数据来源）

## 为什么有它

2026-11 我们讨论过「把 91 个工具拆成多个 MCP 端点（如 `/human/mcp`）以省 token」。
讨论时发现**没有任何工具级遥测**：

- 设备侧 `~/.agent-fleet/session-audit.log` 只记会话事件（`method/status/event`），**没有工具名**；
- 设备侧 agent 的 `~/.dsh/sessions` 记的是**本机**工具（`pwsh` / `read` / `skill`），不是设备 MCP 调用；
- 调用方日志只覆盖各自视角。

所以先落一个**最小、隐私安全**的审计，跑几天后用真实数据决定拆分，而不是拍脑袋。

## 记什么 / 不记什么

每次工具调用（含所有可选能力）写一行 JSONL：

```json
{"ts":"2026-11-28T07:52:46+00:00","tool":"get_screen_size","ms":6,"ok":true,"pid":4044254,"session":"638c7f93"}
```

| 字段 | 含义 |
|---|---|
| `ts` | UTC 秒级时间 |
| `tool` | 工具名（**不含参数**） |
| `ms` | **墙钟**：从进入中间件到返回，**包含排队与事件循环争用**（见下） |
| `started_at` | 进入中间件的时刻（与 `ts` 相差约等于处理耗时） |
| `ok` | 是否成功（异常记为 `false`） |
| `pid` | 服务进程号（多实例时可区分） |
| `session` | MCP 会话 id 前 8 位（把一次批量操作归到同一会话） |
| `holder` | `acquire` 时声明的 `holder_name`（**唯一**从参数里取的字段；≤64 字符） |

**不记**参数、返回值、异常消息。**唯一例外**是 `holder`：`acquire` 的 `holder_name`
（客户端声明的短字符串，≤64 字符）——因为**同机所有 agent 共享同一个服务进程**，
没有它无法把不同 agent 的调用分开，而这直接决定跨组率虚高还是虚低。
落盘失败**不会**影响工具调用（异常被吞掉）。

## 开关与位置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `FLEET_TOOL_AUDIT` | 开 | `0/false/off/no` 关闭 |
| `FLEET_TOOL_AUDIT_PATH` | `~/.agent-fleet/tool-audit.jsonl` | 落盘位置 |
| `FLEET_TOOL_AUDIT_MAX_BYTES` | `8388608`（8 MiB） | 超过即轮转一份 `.1` |

实现：`platforms/common/_tool_audit.py`（FastMCP 中间件 `ToolAuditLog`），
在每个 server 的 `main()` 里与 `LeaseGate` 并列挂载——因此覆盖 core 与所有可选能力，
不需要改任何工具签名。**重启 server 后生效。**

### 部署时的一个致命细节（2026-11-28 事故）

**不要在 server 提供的 shell 里直接 `Stop-ScheduledTask`**：`run_shell` 由被重启的那个进程服务，
Stop 会先把**这条命令自己**掐掉，后续的 `Start-ScheduledTask` 根本执行不到 —— 设备会直接停在那里
（8766 曾因此停服，只能由有控制台的人重新 `Start-ScheduledTask -TaskName "MCP-WinDevice"`）。

安全做法（任选其一，共同点都是**让重启动作脱离被重启的进程**）：

```powershell
# A（本机唯一可用）：起一个独立进程，延迟 3 秒再 stop/start；调用立即返回
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-Command',
  'Start-Sleep 3; Stop-ScheduledTask -TaskName "MCP-WinDevice"; Start-Sleep 2; Start-ScheduledTask -TaskName "MCP-WinDevice"'

# 也可用机器上现成的垫片（更稳）：
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-File',
  'C:\Users\qjl\.fleet\restart-once.ps1'
```

> ⚠️ **不存在的"B 方案"**：曾以为"只 `Stop-Process` 就行，launcher 的 while 循环会重新拉起"。
> 2026-11-28 现场核实：这台机器上**没有守护循环**——`pid=273212`（`.venv\python.exe`）是
> **包装器**、`pid=266180`（`c:\python311\python.exe`）才是真正监听的那个，两者是
> "包装器 → 真身"，不是 supervisor。杀掉真身最可能的结果是**整条一起退出、任务停在 Stopped**，
> 而不是自动重启。⇒ 本机只能走 A（任务计划 stop/start，且必须 detached）。
> B 仅在**确认 launcher 是 supervisor 且有重试间隔**时成立，别默认套用。

无论哪种，**部署后必须验证**：`/health` 200 → `list_capabilities()` 工具数 → 任意调用后
`~/.agent-fleet/tool-audit.jsonl` 出现新行。

## 部署记录（2026-11-28，win-device 8766）

| 步骤 | 读数 |
|---|---|
| 代码 | 设备仓 `C:\Users\qjl\agent-fleet` fast-forward 到含审计的提交 |
| 启动 | `Start-ScheduledTask -TaskName "MCP-WinDevice"`（由人在 RDP/控制台执行） |
| 启动耗时 | **约 195 秒**才 `/health` 200（此前已记录"这台机器 2–4 分钟"） |
| 工具面 | `list_capabilities()` = **91**（core 49 / agent_browser 29 / human_browser 1 / vision 3 / human_dom 5 / devtools 4） |
| 审计落盘 | `~/.agent-fleet/tool-audit.jsonl` **已生成**，记录形如 `{"ts":"…","tool":"list_capabilities","ms":150,"ok":true,"pid":266180,"session":"fecac181"}` |

### 重启后验证：**必须**检查 `pid` 变了（否则验的是旧进程）

`/health` 200、工具数 91、审计出现新行 —— **旧进程全都满足**，它们只能证明"有个进程在服务"。
唯一能证明"新代码进了内存"的判据是 **pid 变了**（审计每行都带 `pid`）。

脚本：`scripts/verify_restart.py`

```bash
# 重启前先记下 pid（例如从审计尾行读）与 git HEAD
python3 scripts/verify_restart.py --url http://test-win11:8766/mcp     --old-pid 266180 --expect-tools 91 --expect-holder
```

| # | 检查 | 证明什么 |
|---|---|---|
| 1 | `/health` 200 | 服务在监听 |
| 2 | 工具数 == 期望 | 功能面完整 |
| 3 | 审计有新行 | 中间件在写 |
| 4 | **新行 pid ≠ 重启前 pid** | **新代码进了内存** |
| 5 | （可选）`holder` **自证** | 脚本自己 `acquire(holder_name="verify-restart-…")` 再 `release`，然后断言审计里出现该 holder —— **不依赖窗口里恰好有人 acquire**；pid 未变时直接 skipped，不误判成"字段未落地" |

> 实测（2026-11-28，未重启时跑）：1–3 全 PASS、第 4 条 FAIL（`pid=266180` 与重启前相同）
> —— 这正是第 4 条存在的意义。

**回滚判据**：也不是"服务活着"，而是 **pid 又换了一次 + 工具数/审计行为回到上一版**。
所以重启前必须记录 **当前 pid 与 `git HEAD`**（回滚要回到哪一版才有据可查）。

> 部署时**必须**按上一节的"致命细节"执行：重启动作要脱离被重启的进程，否则 Stop 会掐掉
> 下发命令的自己（本次已真实发生，靠人工 RDP 才恢复）。

## 几天后怎么分析

```bash
# 最近 7 天：按天、按工具（含失败与慢调用标记）
python3 scripts/analyze_tool_audit.py --days 7

# 评估候选端点：覆盖了多少真实调用、需要挂几个工具
python3 scripts/analyze_tool_audit.py --days 7 --profiles ops,gui,human,devtools
```

判定标准（脚本里也写了）：

- **覆盖 ≥95% 且工具数明显更少** 才值得单独开端点；
- 换端点意味着调用方要换 URL，**频繁换端点比多几个工具更贵**；
- 候选只是起点：`PROFILES` 在 `scripts/analyze_tool_audit.py` 顶部，按真实数据改。

### ⚠️ 分析前必读：会话会被重连切成碎片

审计里的 `session` 是**连接级**标识，客户端重连就会换新 id（2026-11-28 实测：win 上重启后
同一 pid 下 session 依次变成 `fecac181 → ea8d68ed → 5d439ee8 → 8b0cd62c`）。
于是一条真实工作流会被切成两个"单组会话" ⇒ **跨组耦合被系统性低估**，而低估的方向恰好指向
**"可以拆"** —— 这是最容易出事的偏差（拆完才发现"先 acquire 再调工具"跨了端点）。

### 两个偏差方向（结论是**区间**，不是点估计）

| 偏差来源 | 方向 | 处置 |
|---|---|---|
| **重连碎片**：session 换 id，一条工作流被切成多个"单组会话" | 跨组率**偏低**（下界） | 按同一归属键 + 间隔粘回 |
| **多 agent 同时段**：`pid` 是**服务端进程**，同机所有 agent 共享 | 跨组率**偏高**（上界） | 按 `holder` 分组 |

脚本按 **`(pid, holder)` + 相邻调用间隔 ≤ 180s**（`--stitch-gap` 可调）粘回，并打印：

| 输出 | 读法 |
|---|---|
| `原始会话数` vs `粘贴后单元` | 差距大 = 重连频繁 |
| `单元调用数分布` | **过半单元只有 1–2 次调用 ⇒ 多半是碎片，不是工作流** |
| `带 holder 的记录 X/Y` | 不足 100% ⇒ 无 holder 的记录只能按 pid 归并，可能把不同 agent 缝在一起 |
| `因超过 Ns 被切开的相邻对` | 数量偏多 ⇒ 阈值偏小（发布流程等页面/等激活可能 >180s） |

**结论口径**：跨组率是**区间**（碎片给下界、多租户给上界），不是精确值；报告里两个方向都要写。

### ⚠️ `ms` 不是"工具执行耗时"：它包含排队

真机样本（同一 `pid`、20 条记录内）：

```
run_shell  ms=68815 / 67989 / 48988   ← 内容只是"读 20 行文件 / Test-Path"，毫秒级操作
```

而调用方感知的往返是**秒级**。⇒ `ms` 是**从进入中间件到返回**的墙钟，服务器忙时会把
"排队与事件循环争用"算进去。因此：

- **不要用单条最大值给工具排"慢"**——那会把"服务器忙的时候调了 `run_shell`"误读成"`run_shell` 慢"；
- 分析脚本现在按工具输出 **p50 / p95 / max**（`stats["latency"]`），排序看 **p50**；
- 真要归因排队，需要客户端侧记录发送时刻（服务端看不到请求到达前的等待）。

### `session` 不能归属到人（真实交错样本）

同一 `pid` 的 7 分钟内出现 **6 个 session**，且存在**交错**：
`43a76921`（run_shell 872ms）夹在两条 `8b0cd62c` 之间，间隔 2 秒——这是两个客户端在
**同一个服务进程**上真实并发，不是构造数据。

⇒ 只靠 `session` 无法判断"这条是谁调的"；也正因如此才需要 `holder`（`acquire` 声明，
落地后按 `(pid, holder)` 归并）。而**未 acquire 的调用**（`get_status` / `list_capabilities` 等
免租约工具）仍然没有 holder——它们只能按 pid 归并，这是已知的残余误差。
服务端重启会换 `pid`，跨重启的工作流必然被切断，这部分损失无法避免，也计入下界。

### 比"调用次数"更该看的：**同一会话内的工具序列**

```bash
python3 scripts/analyze_tool_audit.py --days 7 --sessions 10
```

输出每个会话的工具序列，并标记 `⚠ 跨组`（该会话同时用到 ≥2 个候选端点组）。
**这类会话不适合拆端点**，原因不是"多连一次"，而是：

| 跨端点会分裂的东西 | 后果 |
|---|---|
| **MCP session** | 租约（`LeaseGate`）是**按 session 绑定**的：在 `/ops/mcp` acquire、再去 `/gui/mcp` 调用，会被认成"另一个会话"⇒ `device_leased` |
| 剪贴板 | 系统级全局资源，跨端点仍共享（这条反而没问题） |
| 前台窗口 / Chrome 焦点 | 系统级共享，但**操作顺序**会被打断：拆开后无法保证"先切前台再粘贴"在同一会话里 |

> 同一进程内多端点（多个 `FastMCP` 挂在同一个 uvicorn 上）时，`_state_registry`、租约、
> human_dom bridge 都是**模块级单例**，不会各自一套；真正的分裂发生在**多进程/多端口**
> （例如 side-car 实例）——2026-11-28 在 8767 side-car 上就见过"两个 server 各自一套 lease"。

所以拆之前至少量两件事：**典型任务跨几个工具**、**其中多少依赖同一份会话态**。

> 端点拆分的可行性、三条硬约束（租约按 session 绑定 / `list_capabilities` 会说谎 /
> 操作顺序无法跨端点保证）见 [`docs/mcp-endpoints-design.md`](mcp-endpoints-design.md)——
> 那里有 2026-11-28 的本地 spike 实测结果。

## 已知局限

1. **只有本服务进程视角**：一个设备被多个调用方用，审计是合并的（`session` 只能分组，不能反查是谁）；
2. **不含跨设备路由**：`device=` 参数不记录（隐私优先）；多设备场景请按 `pid` 或多实例路径区分；
3. **轮转会丢最旧的一份**：只保留当前 + `.1`；长期趋势请定期把文件取走归档。

## 2026-11-28 的抽样：数据出处与口径（**不是**审计文件）

先说清楚，避免以后拿审计数据复核时对不上：

| 项 | 内容 |
|---|---|
| **来源** | 本机（agent 主机）`~/.dsh/sessions/**/session.v4.jsonl.zstd`——DSH 会话日志里的 `tool/call` 事件 |
| **口径** | 统计 `type=="tool/call"` 且名字含 `mcp` 的调用；按事件时间过滤最近 5 天 |
| **算的是** | **调用尝试次数**（失败也会留下 `tool/call`，随后才是 `tool/result`）；每次重试算一次独立调用 |
| **没算的** | 非 MCP 工具（`pwsh`/`read`/`skill` 等本机工具）；设备侧记录（设备只有会话级日志，无工具名） |
| **与审计的关系** | 与 `tool-audit.jsonl` **无重叠**（审计 2026-11-28 才落地）；两者口径不同，数字不可直接相加 |

样本：167 个会话、1,945 次 MCP 调用、分布在 3 台设备。

### 阶段性结论（比"要不要部署审计"更有用）

| 设备 | 调用数 | 主要成分 | 判断 |
|---|---|---|---|
| `win-device` | 1,419 | `run_shell` 654、`read_process_output` 232、`start_process` 189、`write_file` 172… | **GUI 与发布负载都在这一台** |
| `mac-device` | 299 | **`run_shell` 292（98%）** | **ops 机**：验收重点是 shell/进程管理，不是页面元素/发布链路 |
| `win-device-qjl` | 171 | `run_shell` 135、`start_process` 14… | 远端运维用途 |

⇒ 两个推论：

1. **「拆端点」这个问题实际只需要在 `win-device` 的数据上回答**——mac 那 299 次可以整段不看
   （它只会再次证明 ops 占绝对多数）；
2. mac 的验收重点应放在 shell/进程管理，**不要照搬公众号/页面元素那套 playbook**。

## 与 2026-11-27 的一次抽样结论的关系

当时用**调用方会话日志**（本机 167 个会话 / 近 5 天 / 1,945 次 MCP 调用）做过一次抽样：
`ops/shell/file` 90.8%、lease/admin 8.4%、UI/screen 0.7%、`human_*` 0.1%。
那份数据只能说明**这台主机上的 agent** 怎么用，不能代表发布型 agent——所以才有这个审计。
