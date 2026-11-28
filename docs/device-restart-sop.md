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
| 3 | 记录回滚锚点 | **`pre_pull_head`**（pull 前实际在跑的版本，回滚回到它）+ `pid`；另记 `deployed_head`（本次要装的版本）。**回滚锚点必须是 pull 之前的 HEAD**，否则回滚只能回到一个还没部署过的提交 |
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
python3 scripts/verify_restart.py --url http://test-win11:8766/mcp --old-pid 266180
```

| # | 检查 | 证明什么 |
|---|---|---|
| 1 | `/health` 200 | 服务在监听（**可能耗时 2–4 分钟**，别急着判死） |
| 2 | 工具数 == 期望 | 功能面完整（期望值来自 `scripts/_expectations.py`，**不要硬编码**） |
| 3 | 审计有新行 | 中间件在写 |
| 4 | **新行 pid ≠ 重启前 pid** | **新代码进了内存**（关键；前三件旧进程也满足） |
| 4b | **新 pid 的记录 `build` == `deployed_head`**（比较时统一小写取前 7 位；**`dirty=true` 时降级为 SKIP**，因为 HEAD 相同不代表代码相同） | **跑的就是期望那份代码**——审计每行带 `build`（git 短 HEAD），这是直接读数；不要用「某字段出现了所以大概是新码」这类代理指标 |
| 5 | （可选）`holder` 字段 | 审计升级是否落地；**由脚本自己 acquire 一次自证**（pid 未变时 skipped） |

## 3.1 三种状态：通过 / 失败 / **无法验证**

判据要分两类：**能力不足**（本次没能验）与**结论为否**（验了，不通过）。
把所有情况硬塞进红或绿，会把"没法验"读成"验不过"，下一步动作就错了。

| 状态 | 含义 | 例子 | 退出码 |
|---|---|---|---|
| `PASS` | 验过，成立 | pid 变了、工具数对 | 0 |
| `FAIL` | 验了，不成立 | pid 未变（旧码）、工具数不符 | 1 |
| `SKIP` | **本次没能验** | 设备被他人占用（acquire 失败）、无 `about:blank`、缺依赖 | 不影响 |

`verify_restart.py` 的输出形如 `3 passed, 1 failed, 1 skipped`：
**人工模式**只有 FAIL 让退出码非零；**CI 模式加 `--strict`**，有 SKIP 时返回 **4（未完整）**，不报绿。

### 脚本家族的退出码（同一台机器上不要混用含义）

| 码 | `smoke_ops` / `smoke_devtools` | `verify_restart` |
|---|---|---|
| 0 | 全部检查通过 | 全部通过（人工模式允许有 SKIP） |
| 1 | 有检查失败 | 有 FAIL |
| 2 | 连不上 / 用法错 | 连不上 / 用法错 |
| **3** | **设备上跑的不是这批代码**（缺必需工具 / 能力未启用） | **不使用**（保留给上面那一族） |
| **4** | 不使用 | **未完整**（`--strict` 且有 SKIP） |

> 规则：**CI 判绿只看 0**；看到 3 先查版本/能力，看到 4 才去看 SKIP。

> 为什么要分开：人工跑时"这次没验成"不算失败是合理的；但进了 CI，退出码 0 会被读成"通过"，
> 一个长期 SKIP 的检查就会静默退化成一盏永远亮的绿灯。`--strict` 让 CI 能把"未完整"当独立状态处理。

## 3.2 在 CI 里怎么组合（**不要用 `&&` 串联**）

`cmd1 && cmd2` 会在第一个非 0 处短路，后面的脚本**根本不会跑** —— 于是你失去
"是版本问题（3）还是没验完（4）"的区分，只剩一个笼统的失败。

正确做法：**各自跑、各自收集退出码，最后按优先级汇总**。

```bash
set +e
python3 scripts/smoke_ops.py      --url "$URL"                 ; smoke=$?
python3 scripts/verify_restart.py --url "$URL" --old-pid "$PID" --strict ; verify=$?
set -e

# 优先级：1（失败） > 3（版本/能力不符） > 4（未完整） > 0（全绿）
for code in "$smoke" "$verify"; do
  case "$code" in
    1) echo "GATE: FAIL (有检查失败)"; exit 1 ;;
  esac
done
for code in "$smoke" "$verify"; do
  case "$code" in
    3) echo "GATE: VERSION (设备上跑的不是这批代码)"; exit 3 ;;
  esac
done
for code in "$smoke" "$verify"; do
  case "$code" in
    4) echo "GATE: INCOMPLETE (有检查被 SKIP)"; exit 4 ;;
  esac
done
echo "GATE: GREEN"
```

> 为什么这个优先级：看到 1 先修失败；没有 1 但有 3 说明**代码没生效**（此时 4 的 skip
> 多半是它导致的，先解决版本）；3 也没有但有 4，才是"跑了但没验全"。

## 4. 回滚（判据不是"服务活着"）

**回滚判据**：验证失败，或 **pid 又换了一次但行为未变**（说明回到的还是旧码/错码）。

步骤：`git -C <repo> checkout <锚点 HEAD>` → 按 §2 再重启一次 → 再跑 §3（`--old-pid` 用本轮 pid）。

## 5. 记录（每次执行后）

在 `docs/tool-audit.md` 的「部署记录」追加一行：时间 / 锚点 HEAD / 重启前 pid / 重启后 pid /
验证结果 / 执行人（agent 或人）。**没有记录等于没做**——下次出事无从追溯。
