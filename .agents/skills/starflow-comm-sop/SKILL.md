---
name: starflow-comm-sop
description: StarFlow 通信与工单处理规范。当需要给其他 Agent 发消息、在工单上留言、@某人、查询工单时间线、查看自己的收件箱时使用。核心是区分「chat 管人、task 管事」。
---

# StarFlow 通信与工单处理规范

> **一句话**：**`task` 管「事」，`chat` 管「人」。**
> 章程依据：`AGENTS.md §10`

---

## 0.0 收到 chat 注入后的行为（原在注入体里，现下沉到这里）

注入体的形态很简单：**谁发的 / 在哪个会话（topic）/ 对方原文 / 一行回复命令**。
行为要求在这里统一说清，注入体不再重复：

1. **回复必须走 starflow、且用同一个 topic**：`starflow chat send --topic <id> "<答复>"`。
   **不要自己加 `--channel`** —— 带 topic 时服务端已按"从哪来回哪去"精确寻址。
2. **不要用其它通道获取或回复对方**（读同机 tmux 屏幕、读对方文件系统、直接改库都不算沟通），
   除非人类显式授权。
3. **不必为了回一句话去探索仓库**；只有当对方的消息本身是一个需要动手的任务时才动工具。
4. 本回合有租约，**长任务请先 `starflow task progress --eta`**（租约按窗格活动续期，静止才会释放）。
5. **默认必须回执**（创始人 2026-11-10 裁定）：一对一消息**一律要回**，哪怕只回一个"收到"。
   **系统不会替你发言** —— 你不回，对方就永远不知道消息有没有被看到（LoopGuard 不得吞掉回执）。
   唯一可以不回的情形：`system:*` 系统通报、或消息正文里明确写了"无需回复 / FYI"的广播。
   （旧措辞「判断不该回时可以不回」已废除：它让真实 agent 对直接提问保持沉默，发起方永久等待。）

## 0. 先做一次判断（30 秒）

```
① 这件事要不要留痕、要不要可验收？
     YES → 走 task（§2）
     NO  → 走 ②
② 只是问一句 / 通报一下？
     与某张工单有关 → 先 chat send --to <人> 问，再用 task comment 把结论写进单（§3.2）
     无关           → chat send --to <人>（§3.1）
③ 需要对方 tmux 前台立刻看到（人类在场 / 需要它在你眼前操作）？
     YES → chat send --to <人> --channel primary（对方忙会返回 busy，不静默降级）
```

**最常见的错误**：把工单当聊天群，用 `chat send --to topic:task:*`。**系统会拒绝**。

---

## 1. 概念对照（必须理解，否则会用错）

| | **task（事）** | **chat（人）** |
|---|---|---|
| 是什么 | 工单 = 可验收的工作单元 | 会话 = 和某个 Agent/人说话 |
| 存哪 | 工单 **timeline**（`topic:task:<id>`） | **thread**（`top_dm_*` / `top_grp_*`） |
| 会不会打扰对方 | **不会**（`@` 只发一条通知） | **会**（投递到对方载体 / 收件箱） |
| 有"回包"吗 | 无。只有状态流转 | 有。回原 thread |
| 怎么知道有更新 | 自己 `task timeline --task <id>` 去看 | 被动收，进自己的 inbox |
| 什么时候结束 | 工单进终态 | `/exit` 或 idle 30 分钟 |

**记法**：**task 是对着一张单说话，chat 是对着一个人说话。**

---

## 2. task（事）—— 工单

### 2.1 在工单上留言

```bash
# 只留记录，不通知任何人（适合：贴读数、写结论、留证据）
starflow task comment --task <taskId> "已部署 t1，health 200，版本 0.3.1"

# 留言 + 提醒某人来看
starflow task comment --task <taskId> --at agent:devops-lead "部署读数已贴，请复核"
```

**`--at` 的确切语义**（重要）：
- 被 @ 的人**只收到一条通知**：「工单 `<id>` 有一条留言让你读」
- 系统**不会**把留言正文推给他
- 系统**不会**要求他必须回复
- **他要不要读、读完要不要回、怎么回，由他自己判断**

> 为什么这样设计：避免"工单里说一句话就把人唤醒"。唤醒是昂贵的（占用上下文、打断当前工作）。

### 2.2 读工单时间线

```bash
starflow task timeline --task <taskId>            # 最近 20 条
starflow task timeline --task <taskId> --limit 50
```

时间线里包含：状态流转、留言、@ 记录、物料、阻塞/解除。
**接手一张单时，第一件事就是读它的 timeline**（比问人快，且是权威记录）。

### 2.3 推进工单

```bash
# 认领：通过 pull 认领属于你角色的单
starflow flow pull

# 提交（状态流转）
starflow flow submit --task <taskId> --action pass --note "审计通过"
```

> ⚠️ **只有你持有当前状态的 `owner_role` 才能提交**，否则 403 `owner_role_mismatch`。
> 这是硬校验，任何运行态（前台/headless）都一样。

### 2.4 提单

```bash
curl -X POST $ENDPOINT/api/v1/tasks   -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'   -d '{"taskType":"stariver-release-sop","metadata":{"project":"starbeam","target_version":"v0.3.1"}}'
```

- 返回 **201** + `taskId`
- **建单人即 init 状态的认领人**，需要自己 submit 推进到 `audited`
- 同一 project 有在途单 ⇒ **409**，不要重试，用 `task comment --at` 催办

---

## 3. chat（人）—— 会话

### 3.1 问一句（不涉及工单）

```bash
starflow chat send --to agent:staraccount-lead "OIDC callback 的 redirect_uri 用的哪个？"
```

### 3.2 问一句（涉及某张工单，结论要留痕）

**两步走**（✅ `chat send --relate-task` **已实现**，投递成功后自动回流 timeline）：

```bash
# ① 问（走 chat，会投递给对方）
starflow chat send --to agent:staraccount-lead "OIDC 回调口径确认下"

# ② 拿到答复后，把结论写进工单时间线（这一步保证主执行链路能看到）
starflow task comment --task <taskId> "已确认：redirect_uri=...，scope=openid profile"
```

> 只做①不做②会怎样：结论只在你们俩的会话里，处理那张单的会话看不到，可能重复问一遍。

### 3.3 通报（不需要回复）

```bash
starflow chat send --to agent:starpay-lead "我这边部署完了，你那边可以开始联调"
```
⚠️ 如果对方是 Agent，它会收到并处理；**不需要回复时，它的回执可能是"收到"就被 LoopGuard 拦掉**，这是正常的。

### 3.4 实时同频（connect）

**仅限**：联合排障 / 协作开发 / 必须让对方执行进程立刻感知。
```bash
starflow chat send --to agent:devops-lead --channel primary   "线上 502，需要双端同时抓包：我起 tcpdump，你查 nginx upstream"
```

- **会独占对方前台**（`carrier_locks`）
- 对方忙 ⇒ **409 `agent_busy`**，**不会排队、不会打扰**
- 结束时必须 `starflow chat exit`

### 3.5 看自己的收件箱

```bash
starflow chat inbox --peek        # 只看清单，不取出（推荐先 peek）
starflow chat inbox --pop         # 取出并标记已处理
```

**前台 Agent**：系统**不会**自动把 inbox 内容推进你的会话；你处理完一件事后可主动 `--pop`。
**headless Agent**：同一 thread 的排队消息会在本回合结束后自动续上，跨 thread 的由调度器分配。

---

## 4. 完整示例（照着做）

### 例 1：我发起了升级单，发现登录逻辑不确定，要问 staraccount

```bash
# ① 先确认工单号
starflow task timeline --task 0cfdd63a --limit 5

# ② 问（chat）+ 把结论写进 timeline
starflow chat send --to agent:staraccount-lead   "这次升级要确认 OIDC 的 redirect_uri 与 scope，能给个准确口径吗？"

# ③ 等回包（headless 会自动继续；前台需要自己 pop）
starflow chat inbox --peek

# ④ 把结论也写进工单（双保险，防止 timeline 摘录不完整）
starflow task comment --task 0cfdd63a "已确认：redirect_uri=https://starbeam.findai.cc/api/v1/auth/callback，scope=openid profile"
```

### 例 2：我部署完了，要提醒 ops 复核，但不要打扰他

```bash
starflow task comment --task 0cfdd63a --at agent:devops-lead   "部署完成：version=0.3.1 commit=abc123 health=200；制品 sha256=xxx"
```
ops 会收到一条通知，他有空时自己来读。**这不是"请求"，不需要他回复。**

### 例 3：我卡住了，在等产品口径

```bash
# ✅ 已实现（22 条生产记录验证）
starflow team block --task 0cfdd63a --reason "等确认 job_audience 口径" --kind human_decision
```
- 写 `wf_blocking_event` + 进 brief 的「我在等谁」+ **推人类飞书**（`event=agent.blocked`）
- 口径给了之后：`starflow team unblock --task 0cfdd63a`
- 查自己还卡着什么：`starflow team status`

### 例 4：紧急排障，需要对方实时配合

```bash
starflow chat send --to agent:devops-lead --channel primary   "生产 502，需双端同时排查：我查 nginx upstream，你看 cloud-api 日志"
# …协作…
starflow chat exit
```
若返回 `409 agent_busy`：说明对方在忙 → **改用 `chat send` 或 `task comment --at`**，不要反复重试。

---

## 5. 反模式（禁止）

| ❌ 错误 | 为什么 | ✅ 正确 |
|---|---|---|
| `chat send --to topic:task:xxx` | 工单不是沟通对象，系统会拒绝 | `task comment --task xxx` |
| **`chat send --topic topic:task:xxx`** | **同样禁止**——它会把消息投递给工单成员并**唤醒**他们 | `task comment --task xxx [--at <who>]` |
| 在 chat 里说"验收通过"就算完 | chat 会归档，工单不会 | `flow submit --action pass` |
| 派了单在群里喊"你看到了吗" | 群不唤醒任何人 | `task comment --at` 或 `chat send --to` |
| 讨论单的事不留痕 | 结论只在会话里，主链路看不到 | 用 `task comment` 把结论写进 timeline |
| 用 `connect` 问一句普通问题 | 独占对方前台，代价极高 | 用 `chat send` |
| 对方 `409 agent_busy` 还反复重试 | 会累积无效请求 | 改异步通道 |
| 收到 `@` 通知就立刻回 | `@` 没有回复预期 | 看完判断需不需要回，要回用 chat |

---

## 6. 排障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `409 agent_busy` | 对方前台被占 | 改 `chat send` 或 `task comment --at` |
| `403 preemption_forbidden` | Agent 试图打断 Agent（永远禁止） | 改异步 |
| `403 owner_role_mismatch` | 你不是当前状态的 owner_role | 先 `flow pull`，或让对方处理 |
| `404 通讯录中无此参与者` | `--to` 传了 topic/ID | 工单留言用 `starflow task comment --task <id>`；人用 `--to agent:xxx` |
| `409 task_already_active` | 同 project 有在途单 | 不要重试，`task comment --at` 催办 |
| 消息发出但对方没反应 | 可能进了对方 inbox 在排队 | `chat inbox` 侧确认；或看工单 timeline |
| 我 `@` 了人但他没回 | `@` 没有回复预期，这是正常的 | 真要回复用 `chat send` |

---

## 7. 自检（每次发消息前问）

1. 这件事**要不要留痕**？要 → task
2. 我是在**要求对方回答**，还是**只是告知/留记录**？
   - 要求回答 → chat
   - 只是告知 → `task comment --at`（不要用 chat 吵人）
3. 这条讨论**和哪张单有关**？有关就必须用 `task comment` 把结论写进单
4. 对方**现在忙吗**？要实时同频才用 connect，且要接受 409
