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
| `ms` | 本次调用耗时 |
| `ok` | 是否成功（异常记为 `false`） |
| `pid` | 服务进程号（多实例时可区分） |
| `session` | MCP 会话 id 前 8 位（把一次批量操作归到同一会话） |

**不记**参数、返回值、异常消息。落盘失败**不会**影响工具调用（异常被吞掉）。

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
# A. 先起一个独立进程，延迟 3 秒再 stop/start；调用立即返回
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-Command',
  'Start-Sleep 3; Stop-ScheduledTask -TaskName "MCP-WinDevice"; Start-Sleep 2; Start-ScheduledTask -TaskName "MCP-WinDevice"'

# B. 用任务计划自身的"重新启动"能力（RestartCount / RestartInterval），只结束 python 进程
Stop-Process -Id <PID>   # 交给 launcher 的 while 循环重新拉起
```

无论哪种，**部署后必须验证**：`/health` 200 → `list_capabilities()` 工具数 → 任意调用后
`~/.agent-fleet/tool-audit.jsonl` 出现新行。

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

## 已知局限

1. **只有本服务进程视角**：一个设备被多个调用方用，审计是合并的（`session` 只能分组，不能反查是谁）；
2. **不含跨设备路由**：`device=` 参数不记录（隐私优先）；多设备场景请按 `pid` 或多实例路径区分；
3. **轮转会丢最旧的一份**：只保留当前 + `.1`；长期趋势请定期把文件取走归档。

## 与 2026-11-27 的一次抽样结论的关系

当时用**调用方会话日志**（本机 167 个会话 / 近 5 天 / 1,945 次 MCP 调用）做过一次抽样：
`ops/shell/file` 90.8%、lease/admin 8.4%、UI/screen 0.7%、`human_*` 0.1%。
那份数据只能说明**这台主机上的 agent** 怎么用，不能代表发布型 agent——所以才有这个审计。
