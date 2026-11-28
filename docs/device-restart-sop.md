# 测试设备重启 SOP（草案，待 owner 授权填写）

> 状态：**草案**。文中两个「留空」项必须由设备 owner 填写后，本 SOP 才生效。
> 触发背景：2026-11-28 一次事故——在**被重启进程自己提供的 shell** 里执行
> `Stop-ScheduledTask`，`Stop` 先把下发命令的自己掐掉，`Start` 没跑到，设备停服约 1 小时，
> 只能由人走 RDP 恢复。

## 0. 两个权限（**分别填写，不要合并**）

执行与回滚经常不是同一个人：能开 shell 的人未必有权决定"回滚到哪一版"。

| 权限 | 谁 | 边界 |
|---|---|---|
| **发起/执行重启** | `<待 owner 填写>` | 允许在满足 §1 前置条件时执行 §2；**不包含**回滚决策 |
| **回滚到上一版本** | `<待 owner 填写>` | 允许在 §3 判定失败时执行回滚；**不要求**具备发起权限 |

## 1. 前置检查（全部满足才可执行）

| # | 检查 | 判据 |
|---|---|---|
| 1 | 租约空闲 | `get_status` → `in_use: false` |
| 2 | 无发布任务 | 发布类进程数为 0（按设备实际口径） |
| 3 | 记录回滚锚点 | 当前 `pid`（审计尾行）+ `git -C <repo> rev-parse HEAD` |
| 4 | 端口归属 | `Get-NetTCPConnection -LocalPort <port> -State Listen` 的 OwningProcess 是"你以为的那个进程" |
| 5 | 变更内容明确 | 说清"改什么/为什么/期望工具数"（期望值取 `scripts/_expectations.py`） |

## 2. 执行（**必须 detached**，本机唯一安全方式）

```powershell
# 方式 A：机器上现成的垫片（推荐）
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-File',
  'C:\Users\qjl\.fleet\restart-once.ps1'

# 方式 B：内联延迟脚本（等价）
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-Command',
  'Start-Sleep 3; Stop-ScheduledTask -TaskName "MCP-WinDevice"; Start-Sleep 2; Start-ScheduledTask -TaskName "MCP-WinDevice"'
```

**禁止**：在 `run_shell` 里直接 `Stop-ScheduledTask` / 直接 `Stop-Process` 真身。
本机 **没有** supervisor 守护循环（`.venv` 那个是包装器，不是 supervisor），
杀掉真身通常整条退出、任务停在 Stopped。

## 3. 验证（四件，缺一不可）

```bash
python3 scripts/verify_restart.py --url http://<host>:<port>/mcp --old-pid <重启前pid>
```

| # | 检查 | 证明什么 |
|---|---|---|
| 1 | `/health` 200 | 服务在监听（**可能耗时 2–4 分钟**，别急着判死） |
| 2 | 工具数 == 期望 | 功能面完整（期望值来自 `scripts/_expectations.py`，**不要硬编码**） |
| 3 | 审计有新行 | 中间件在写 |
| 4 | **新行 pid ≠ 重启前 pid** | **新代码进了内存**（关键；前三件旧进程也满足） |
| 5 | （可选）`holder` 字段 | 审计升级是否落地 |

## 4. 回滚（判据不是"服务活着"）

**回滚判据**：验证失败，或 **pid 又换了一次但行为未变**（说明回到的还是旧码/错码）。

步骤：`git -C <repo> checkout <锚点 HEAD>` → 按 §2 再重启一次 → 再跑 §3（`--old-pid` 用本轮 pid）。

## 5. 记录（每次执行后）

在 `docs/tool-audit.md` 的「部署记录」追加一行：时间 / 锚点 HEAD / 重启前 pid / 重启后 pid /
验证结果 / 执行人（agent 或人）。**没有记录等于没做**——下次出事无从追溯。
