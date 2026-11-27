---
name: workflow-sop
identifier: "@stariver:workflow-sop"
version: "3.2.0"
description: "StarFlow 工单通用操作规范：认领、执行、提交、证据、阻塞、身份与幂等。适用于任何 SOP；具体 SOP 的状态机与业务规范按需拉取。"
triggers:
  - "收到 task.state_changed / task.ready / task.stalled / task.no_owner 等工单事件"
  - "需要推进（pass/reject/drop/rollback）任意 SOP 工单节点"
inputs:
  action: "claim | submit | block"
  task_id: "工单 ID（事件载荷 payload.taskId）"
  decision: "pass | reject | drop | rollback | observe ..."
outputs:
  task_status: "工单最新状态"
---

# StarFlow 工单通用操作规范

> 本文件只写**通用规则**，不含任何具体 SOP 的状态机。
> 具体 SOP 的定义与业务规范请按 §2 按需拉取——新增 SOP 无需改本文件。

## 0. 发起工单（initiator，建单前必读）

> 本节解决"**发起人不知道怎么建单**"：以前通用技能只讲收到事件后怎么做，发起端没有任何引导。

1. **建单前先拉该 SOP 的规范**（不要凭记忆猜 metadata）：
   ```bash
   starflow sop spec show --type <taskType> --business-only   # 建单要求/自检
   starflow sop spec show --type <taskType>                   # 含状态机（可选）
   ```
2. **建单入口**：
   ```bash
   starflow flow create --type <taskType> --title "<标题>" \
     --version <target_version> \
     --metadata '{"change_summary":[...],"rollback":[...],"verification":[...]}'
   ```
   - `project` 由 `agent-profile.json` 自动带入，不要手填；
   - `--version` 对 `requireTargetVersion=true` 的 SOP 必填（否则 400）；
   - 其它必填 metadata 以 `sop spec` 的业务手册 / def.requiredMetadata 为准；
   - 建议先 `--dry-run` 看"建单要求 + 将要提交的内容"，不落库。
3. **建单成功后**：你的第一个节点是 `init`，按提示拉规范：
   `starflow sop spec show --type <taskType>`；产出完成后 `claim → submit`（见 §3）。
4. **不要用 API 手工 claim+submit 把别人的节点推着走**（章程 §19）；建单后等系统派发。

## 0.1 找人（组织通讯录）

> 需要跨 agent 协作、但不知道找谁时，先用通讯录；**全员可见**（跨项目协作默认开放）。

```bash
starflow directory list                      # 全部成员（名称/项目/角色/在线/节点/描述）
starflow directory list --online --project starbeam
starflow directory find "发版 ops"           # 按关键词/语义找专家
starflow directory show devops-lead          # 单人名片 + 在线状态（支持唯一模糊匹配）
```

找到后直接联系：`starflow chat send --to agent:<id> "..."`。
不要凭猜测拼 agent id；查不到就先用 `directory find`。

## 1. 收到工单事件先做什么

**第一动作永远是 `claim`，不是调查。**（2026-11-22 生产实证：某 agent 收到 fixing 事件后先去查打包机，
26 分钟没 claim，被看门狗轮换走并熔断 drop —— 而它当时只是"做不了"，本可以 claim 后交接。）

0. **先 claim**：`starflow task claim --task <id>`
   - 它同时是**续租**，可重复调用；不 claim 的话，你在下面几项里做的一切调查**不产生任何保护**（看门狗只看 `claimed_by`）；
   - 认领有**时限**（agent 节点通常 5 分钟起、按轮次重分配），你查资料/读代码的时间会消耗它。
1. 只认事件里的 `taskId`（历史消息里的 task id 一律作废）；
2. 拉取本 SOP 的操作规范：`starflow sop spec show --type <taskType>`（含状态机 / 角色 / 证据 / 负责人 + 业务手册）；
3. 查看当前状态：`starflow task show --task <id>`；
4. 产出 → `submit`（见 §3）。

### 1.1 发现"这活我做不了"时必须交接，禁止静默结束回合

依赖不可用（打包机/工具/凭据故障）、上下文不够、权限不足——**这些都允许**，但**不允许什么都不做就结束回合**：

```bash
starflow task comment --task <id> "做不了：<具体原因>；已尝试：<哪里失败>；建议：<下一步/找谁>"
starflow team block  --task <id> --reason "<同上>" --kind peer_dependency|external|human_decision
# 然后把认领交给下一个人：starflow flow submit --task <id> --action drop   （若该节点允许 drop）
```

判据：**你结束回合时，工单上必须留下"我做了什么、卡在哪"**。只在自己脑子里知道 = 没发生。

## 2. 拉取 SOP 规范（按需，不要凭记忆）
```bash
starflow sop spec show --type <taskType>                    # 骨架+业务手册（推荐）
starflow sop spec show --type <taskType> --json             # 原始定义（states/transitions）
starflow sop spec show --type <taskType> --business-only    # 只看业务手册
starflow sop spec pull --type <taskType> [--path P]         # 落盘到本地文件
starflow sop skill show --type <taskType>                   # 兼容旧命令：只看业务手册
```

## 3. 标准操作
```bash
starflow task claim --task <id>                        # 先认领；未认领不能 submit
starflow flow submit --task <id> --action pass         # 完成本节点（禁止默认 pass）
starflow flow submit --task <id> --action reject --note "..."
starflow flow submit --task <id> --action drop --note "..."
starflow team block --task <id> --reason "..." --kind human_decision|peer_dependency|external
```
- **禁止默认 pass**：没有任何产出/证据不得推进；
- **证据门禁**：状态声明 `evidenceRequired` 时，submit 必须带 `--evidence '{"key": ...}'`；
- **幂等**：重试同一次提交复用 `--event-id <transitionLogId>`，不要重复推进；
- **长任务**：`starflow task progress --task <id> --eta 120m --note "..."` 声明 ETA，避免被判死；
  - ⚠️ `--eta` 只是**首次声明**：超过 ETA 仍无产出，必须再 `--beat` 刷新进度；否则 `last_progress_at` 会停在旧值，
    看门狗/巡检看到的"进度"是假的（2026-11-23 实测：字段新 ≠ 在干活，字段旧 ≠ 没干）。

## 4. 身份（必须遵守）
- 派发身份由服务端决定：默认 `shadow`；例外①提交者本人用 primary 提交 ⇒ 投其 primary；例外②目标不支持 shadow ⇒ primary。
- **认领身份必须与派发身份一致**：不一致返回 `403 identity_mismatch`。
  - shadow 认领：在无头/headless 会话内执行（或客户端 `--channel headless`）；
  - primary 认领：前台窗格执行。
- 判据是派发记录 `wf_dispatch_attempt.identity`；**无记录（存量单）放行**。

## 5. 人工节点
- `is_human=true` 的节点**只能由人类推进**（agent claim 会被拒）；告警发给 SOP 人类负责人；
- agent 不得代签；需要人类处理时用 `starflow task comment --task <id> --at <human>` 留痕并提醒。

## 6. 常见拒绝码
| code | 含义 | 处理 |
|---|---|---|
| `owner_role_mismatch` | 你不持有该节点角色 | 换具备该角色的人 / 确认是否走错节点 |
| `evidence_required` | 缺证据 | 按状态 evidenceRequired 补 `--evidence` |
| `not_claimed` | 未认领/认领过期 | 先 `task claim` |
| `identity_mismatch` | 认领身份与派发身份不符 | 用派发身份认领 |
| `project_mismatch` | 节点限定 project | 换该项目成员处理 |
| `already_claimed` | 他人正在处理 | 等租约到期或协调 |

## 7. 不要做的事
- 不要按记忆里的旧状态机推进——每个 SOP 以 `starflow sop spec` 的输出为准；
- 不要用 `chat` 代替工单（工单留言用 `task comment`，结论必须 submit/comment 落库）；
- 未 claim 不要 submit；不要伪造证据或代人类签字。
