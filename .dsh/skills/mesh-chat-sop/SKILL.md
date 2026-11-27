# Skill · mesh-chat-sop（StarFlow 跨智能体协同）

> **2026-11-01 模型改造**：`connect`（电话模式）已取消。端点由发起方用 `--channel` 选择。

## 一、 端点模型（三层，勿混用）

| 层 | 含义 | 取值 |
|:--:|---|---|
| **runtime** | 引擎 | `dsh` / `claude-code` / `openclaw` |
| **endpoint** | 联系方式 | `primary`（唯一常驻）+ `shadow`（0..N，无头并发）|
| **capability** | 能否开分身 | `supports_shadow: true/false` |

- **primary**：物理 tmux 前台窗格或 headless 常驻会话，**一次一个 turn**，`turn_timeout` 默认 30 分钟
- **shadow**：后台无头，**可并发**（上限 `max_concurrent`，默认 5），零打扰对端前台

## 二、 怎么发

```bash
starflow chat send --to agent:<x> "内容"                    # 默认 auto（有 shadow 走 shadow）
starflow chat send --to agent:<x> --channel primary "内容"  # 显式投前台
starflow chat send --to agent:<x> --channel headless "内容" # 显式投 shadow
starflow chat send --to agent:<x> --reply-to <msgId> "内容" # 显式回复某条
starflow chat send --to agent:<x> --relate-task <taskId> "内容"  # 关联工单（结论必须回流）
```

## 三、 三种失败码与应对

| code | 含义 | exit | 应对 |
|---|---|:--:|---|
| `busy` | 对方 primary 忙 | 3 | 看 `has_shadow`：有就改发 shadow；没有就等 `retry_after` 秒 |
| `shadow_unsupported` | 对方不支持分身 | 2 | 消息已落其 inbox，**不会注入其唯一 session**（保护其上下文）；改用 task comment |
| `endpoint_offline` | 对方离线 | 0 | 消息已入持久化信箱，等它上线 |

**`busy` 的 payload 有八字段：**
```json
{"reason":"primary_occupied","busy_since":"...","expected_free_at":"...",
 "occupied_by":{"agent":"X","topic":"..."},"has_shadow":true,"shadow_ready":true,
 "retry_after":120,"alternatives":["send_to_shadow","wait","force_if_human"]}
```
**⇒ 别自己猜"等多久"，读 `retry_after`。**

## 四、 Origin-Sticky（回复回哪）

- 在 tmux 发起 ⇒ 对端回帖**强制回传原始发起窗格**
- `origin_pane` 取自**该 agent 自己 profile 的 `primary_endpoint.address.pane`**，不是 `$TMUX`
- 服务端做**归属校验**：`origin_pane` 不属于发起方 ⇒ **降级 shadow + 落 `origin_pane_mismatch` 告警**，绝不投错窗格

## 五、 DND（免打扰）

```bash
starflow dnd on --reason "深度开发 Task 5~11"   # 只阻断前台注入，headless 照常
starflow dnd off
starflow dnd status
```
- **只锁前台，不断通信**：DND 生效时 headless 通道照常工作
- **agent 永远无权打断 agent**（`force_override` 只给人类）

## 六、 会话归档

```bash
starflow chat exit --topic <id> --memo "100~200字结构化备忘"
```
- **必须带 `--memo`**（服务端 schema 要求 `summaryMemo`）
- 归档**不动 epoch**；下次建新会话才用 `epoch = MAX+1`（两代共存）
- 归档后不要再往旧 topic 发

## 七、 chat 与 task 的分工（硬约束）

**`task` 管「事」，`chat` 管「人」。**

| 维度 | task（事）| chat（人）|
|---|---|---|
| 对象 | 工单 = 可验收的工作单元 | Agent / 人 = 沟通对象 |
| 是否唤醒 | 不唤醒（`@` 除外）| 会投递 |
| 有无回包 | 无，只有状态流转 | 有，回原 thread |

- 工单留言用 `starflow task comment --task <id>`，**禁止** `chat send --to topic:task:*`
- **只在 chat 说过 = 没说过**：结论必须落到工单
- **阻塞必须 `starflow team block`**（只在聊天里说"我在等"不算，历史事故卡 22.5 小时）

## 八、 禁止

- 🔴 混用 role（primary/shadow）与 kind（tmux/headless）
- 🔴 用 runtime 类型推投递方式
- 🔴 daemon 代 agent 上报端点
- 🔴 系统代 agent 发言
- 🔴 把"测试失败"直接当代码 bug（先怀疑测试方法：管道吞 exit code / 传截断 id / 跨 topic 引用 / 从错误窗格执行）
