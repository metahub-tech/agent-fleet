# 设备侧验收清单（社媒操作优化 · 2026-11-27）

> **读者**：在 Windows 设备上跑真机的 operator（`agent:device-operator-lead` 或人为代跑）。
> **目的**：把这一批改动从"代码写完"推进到"真机可验收"。每项都写了**判据**，判据不通过就贴证据，
> 不要用"看起来正常"代替读数（判据纪律见 `AGENTS.md` §6）。
> **只读优先**：A/B/E 组不改变现场；C/D 组会动剪贴板与临时文件，按自己的节奏跑。

---

## `list_tabs` 的 unknown 比例是负载相关，不是故障（三组连续读数）

真机同一台机器、同一个 36 标签 profile，三次观测：

| 版本 | tabs | unknown | 耗时 |
|---|---|---|---|
| `d39b3d1` | 34 | **28** | 313ms |
| 未记版本 | 36 | **36**（预算被打满） | 391ms |
| `c7862fd` | 36 | **33** | 328ms |

unknown 在 28–36 之间浮动，与设计一致：**并发探测在 `probe_budget_ms`（默认 300ms）内没赶上的页
记 `unknown`，且不重试**。所以：

- 看到大量 `unknown` **不是**"工具坏了"，是"预算内没探完"；
- 需要更准的可见性时，调大 `probe_budget_ms`（代价是总时长上升），或直接 `activate_tab` 后再 `list_tabs`；
- 只有 0 tab / 报错 才说明真出问题。

> 这条来自 `agent:device-operator-lead` 连续**四次**真机读数（2026-11-27），不是推断；第四组（36/36/483ms）见「第六轮（v5）」——四组放在一起看，规律是
**unknown 数与 duration_ms 正相关**，比单看比例更有解释力。

## 一页速览：真机验证到哪一步了

### 证据强度分四档（不要二值化）

> 采纳 `device-operator-lead` 的建议：这轮反复出现"这条算不算验过"的争论，二值（验过/没验过）
> 会把 L1 读成 L2、把 L0 读成 L3。

| 档 | 含义 | 典型 |
|---|---|---|
| **L0** | 未验证：只有代码 / 推断 | 规则 2「全重复时选中」 |
| **L1** | 有野外观测：真机偶然出现且抓到原始返回，但**不能按需复现** | `frozen_background_tab`（第八节） |
| **L2** | 脚本可复现：一条命令能重复跑出同一判据 | A 组 12/12、7/7、target-id 8/8 |
| **L3** | 多轮稳定：**不同现场状态**下重复通过 | `smoke_ops` 在两轮不同 tip 上 12/12 |

| 项 | 档 | 依据 |
|---|---|---|
| `smoke_ops` | **L3** | 两轮不同 tip（`d39b3d1`、`d417e97`）均 12/12，34 标签 profile |
| `smoke_devtools` | **L2** | `c7862fd` 一轮 7/7（此前 `d417e97` 上 3/6，已定位为脚本判据 bug 并修） |
| B1 选页维度 | **L2** | `url_part` 命中唯一页、62ms |
| B1 冻结分支 | **L1** | 长期后台标签返回该 reason（原始返回已抓），`activate=True` 恢复；脚本化未跑成 |
| B2 富文本（四项） | **L2** | h2/bl=4px/pCount=2/gaps 24/ufffd=0/字数 22/22（一轮，专用夹具） |
| B3 UIA 卡死回归 | **L2** | `dump_ui` 9797ms 有界返回（两轮读数一致） |
| B4 中文逐字节点 | — | 环境不具备（设备无微信 PC 端），记 N/A |
| §5 验证 JS | **L2** | 真机 1343 字草稿原样跑过（`roots.length=2`） |
| `choose_target` 规则 1 | **L2** | 真机命中唯一 url（v4） |
| `eval_in_profile(target_id=…)` 管线 | **L2** | v5 直传 target_id 拿到 value=1 |
| `choose_target` 规则 2 | **L0** | 代码已修 + 离线构造覆盖，无真机读数 |
| 头条「草稿不落库」 | **L2** | 90s 轮询 9 采样点（页脚/字数）+ 结束时草稿箱 0 条 |
| 知乎端到端 | **L2** | 11 步 9 成功、7 项复验全绿、1240/1240（对方 lab） |
| 抖音 | **L0** | 无任何记录 |

> **引用规则**：写 PR 时按档说话——L2 说"脚本可复现"，L3 才说"多轮稳定"，L1 只能写"野外观测到、
> 不能按需复现"，L0 不要出现在"已验证"叙述里。

## 0. 前置（只做一次）

```powershell
# 1) 设备上切到集成分支并重启 server（能力是导入期静态注册，不重启看不到新工具）
git -C <repo> fetch origin
git -C <repo> checkout integ/operator-p0-p1
# 重启 win-device（任务计划 / launcher 二者之一，按本机既有方式）

# 2) 自查：新工具是否真的注册上了
```

```text
list_capabilities()   → core.tools 里应包含：
                        file_put, file_get, clipboard_set_html
                        （devtools 默认开启，应出现 devtools 能力且 status=enabled）
```

| 勾 | 项 | 判据 |
|---|---|---|
| ☐ | server 已重启 | `list_capabilities()` 的 `core.tools` 含上述 3 个新工具名 |
| ☐ | 版本一致 | 设备上的 checkout 是 `integ/operator-p0-p1`（`git -C <repo> log -1 --format=%h`） |
| ☐ | skill 是**拷贝**模式（Windows 常态）时，pull 后要重装 | `python3 scripts/install_skills.py --platform win-device --target <你的技能目录> --force`；否则 agent 读到的仍是旧 SOP（符号链接模式会自动跟随，无需重装） |
### 交付前：新增文件会触发另一个门禁

`blueprint-check` 是 CI 的 **required** 检查，而它只看 `docs/internal/blueprint/MAP.md` 是否与
仓库结构一致。所以**只要新增了 `scripts/`、`platforms/`、`cli/` 下的文件**，就必须重跑：

```bash
./scripts/gen-blueprint-map.sh            # 写
./scripts/gen-blueprint-map.sh --check    # 验（应 exit 0）
./scripts/gen-blueprint-interface.sh      # 改了工具签名时还要跑这个
```

我在本 PR 里就漏跑过一次，门禁当场报 `map=1`。这类"新增文件触发另一个门禁"和下面
"端口归属"是同一性质：**动作本身没错，但有一个不在眼前的必做步骤**。

### 重启前必须做：确认端口上没有**陈旧监听进程**

真机撞到过（2026-11-27）：父 wrapper 被 kill 后，**子 python 仍占着端口**，新实例启动直接
`OSError: [Errno 10048]`（bind failed）——而看父进程会觉得"起不来"，白排查半小时。

```powershell
# 端口归属：拿到 OwningProcess，再核对它是不是你以为的那个进程
Get-NetTCPConnection -LocalPort 8766 -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess
Get-CimInstance Win32_Process -Filter "ProcessId=<上面的PID>" | Select-Object ProcessId,Name,CommandLine
```

判据与处置：

| 看到什么 | 含义 | 怎么做 |
|---|---|---|
| 没有监听 | 端口空着 | 正常启动 |
| 监听 PID = 你刚起的那个 | 正常 | 等它开始服务 |
| 监听 PID 是**另一个** python（命令行指向旧 checkout） | 陈旧监听抢占 | 先 `Stop-Process -Id <PID>`（确认不是别人的会话），再起 |
| 启动日志有 `Errno 10048` | 端口被占 | 同上；**别**反复重启（会一直失败） |

另一条现场事实：这台机器上**新实例可能要 2–4 分钟才开始监听**（python 被其它工作饿着），
跑一次 smoke 只要 5 秒。所以"3 分钟没响应"不等于起不来；判断"真的挂了"应当看进程是否存活
+ 日志有无异常，而不是等端口。


---

## A0. 一键跑（覆盖 A / B / D2 的脚本判据）

```bash
python3 scripts/smoke_ops.py --url http://<host>:8766/mcp --json
（脚本会按设备**实际工具集**自动判定平台：有 `file_put` ⇒ Windows 跑全部；
  只有 `wait_for` ⇒ macOS 跑通用项并跳过文件/剪贴板；两者都没有 ⇒ exit 3，说明代码不是这批。）
```

脚本会做：工具注册检查 / 二进制往返 sha（含 **76 列折行 base64** —— 标准编码器常见输出）/
超限不落盘 / 富文本剪贴板（格式列表只有 `HTML Format` + 回读通过 + **`attempts` 重试路径**）/
`wait_for` 预算是否被执行 / `run_actions` 顺序执行与**整批预校验** / **UIA 调用是否在预算内返回**（`dump_ui`/`list_windows`/`find_elements` 三条延迟判据，验证「卡死」修复在真机上成立）。**副作用**：会覆盖设备剪贴板，并在 `C:\Windows\Temp` 写一个临时文件；
不会点击/输入/启动任何东西。

退出码：`0` 通过、`1` 有失败、`2` 连不上、`3` 缺少必需工具（= 设备上的代码不是这批）。

> 下面的 A/B/D2 手工步骤用于**定位失败原因**（脚本只告诉你哪一条不过）。

## A. 二进制文件收发（`file_put` / `file_get`）

| 勾 | 步骤 | 判据 |
|---|---|---|
| ☐ | 推一张真实图片（200–300 KB） | `file_put(path="C:\\temp\\a.png", content_b64=…)` 返回 `ok=true`，带 `sha256` 与 `bytes` |
| ☐ | 拉回来对账 | `file_get(path=…)` 的 `sha256` 与上一步**逐字符相同**，`bytes` 相同 |
| ☐ | 推 5 MB 文件 | 返回 `ok=false, reason="file_too_large"`，**磁盘上没有生成该文件**（`bytes` 给出实际大小） |
| ☐ | 推到 junction/symlink 目录 | 返回 `ok=false, reason="symlink_not_allowed"`，`real_path` 指出命中段 |

> 证据：贴两次 `sha256` 与 `bytes`。若 sha 不同，先把两个文件都留着，别覆盖。

---

## B. 富文本剪贴板（`clipboard_set_html`）

| 勾 | 步骤 | 判据 |
|---|---|---|
| ☐ | 写一段带 `<h2>` 的 HTML | 返回 `ok=true, verified=true`，`readback` 字段给出比对方（`bytes_equal`/`fragment_equal`/`invariants_only`） |
| ☐ | 看落地格式 | 返回的 `formats` **只有** `["HTML Format"]`（`only_html_format=true`）；出现 `CF_UNICODETEXT` 等即算不符 |
| ☐ | 粘进公众号正文编辑器 | 正文非空白字数 / 稿源 ≥ 95%；无 `\ufffd`；H2 `border-left` = 4px；相邻 `<p>` 间距 ≈ 20px（`gapsSummary.median`=20、`max`=34） |
| ☐ | 多标签 profile 的 eval | `eval_in_profile` **必须带** `url_part`（或用 `target_id`），否则 `page_ambiguous`；带上后应命中该页 |
| ☐ | 负向：另一个进程正占着剪贴板 | `attempts=1` 时返回 `ok=false, reason="clipboard_busy"`；`attempts=2` 时第二轮成功且 `attempts=2` |

> 证据：`formats` 列表原样贴出 + 粘贴后 `verify-draft` 的 JSON（含 `scriptVersion`）。
> 样式三项（borderLeft / gaps / markers）只用于 diff，**不进工具判据**。

---

## C. devtools（可选能力；启用后跑）

确认（默认已开）：`list_capabilities()` 里 devtools 应为 `enabled`；若被本机 `.fleet/config.toml` 关掉，去掉该覆盖并重启 server。

```bash
python3 scripts/smoke_devtools.py --url http://<host>:8766/mcp --profile ~/.fleet/<op-id>
# 可选：再验一条 target_id 管线（规则 2 回退分支真正依赖的就是它）
python3 scripts/smoke_devtools.py --url http://<host>:8766/mcp --profile ~/.fleet/<op-id> --target-id-check
# 可选：自动验冻结分支（需先开一个 about:blank；脚本只碰它，结束必解冻）
python3 scripts/smoke_devtools.py --url http://<host>:8766/mcp --profile ~/.fleet/<op-id> --freeze-check
# --profile 不要加引号（脚本会剥，但加了容易把引号带进路径）；脚本会自动挑 list_tabs 里的第一个 http 页去 eval
```

| 勾 | 判据（脚本已覆盖） |
|---|---|
| ☐ | 退出码 0；能力 `enabled`、`cdp_port` 存活且带 `probe_ms`、`list_tabs` **1s 内**返回、`eval` 可读、超限报 `result_too_large` 且**不带** `value`、`activate_tab` 后目标 `visible` |
| ☐ | 冻结分支：**先确定性地冻结**一个临时标签（见下「如何确定性地触发冻结」），再 `eval_in_profile(activate=False)` → 必须 `ok=false, activated=false, reason="frozen_background_tab"`。只切后台**不算**（后台≠冻结，见 B1 判据修正） |
| ☐ | （手动）同场景默认参数 → `ok=true, activated=true` 且返回值正确 |

---

## D. 原生 UI 稳定性（UIA）

| 勾 | 步骤 | 判据 |
|---|---|---|
| ☐ | 打开一个 Electron/Chromium 桌面应用（如微信 PC 客户端），`dump_ui()` | 要么正常返回，要么在 ~8s 内返回 `{ok:false, reason:"uia_timeout"}`；**不能超过 10s 还没回** |
| ☐ | 同一窗口 `find_elements(query="订阅")` | 若应用是「一字一节点」，返回里应出现 `merged:true` 的元素，且 `name` 是完整词 |
| ☐ | `tap_element(query="订阅")` | 点在「订阅」这两个字上（返回带 `clicked_text_span`），而不是整句中点 |
| ☐ | 控制台窗口 `dump_ui()` | 立即返回 `console_window` 拒绝，不挂住 |

---

## D2. 批量动作（`run_actions`）

| 勾 | 步骤 | 判据 |
|---|---|---|
| ☐ | 三段串：`clipboard_set_html` → `press_key ctrl+v` → `sleep_ms 300` | `ok=true`，`completed=3`，每步 `status:"ok"` 且带 `elapsed_ms` |
| ☐ | 故意在第 2 步写个非法工具名 | 返回 `ok=false, reason="invalid_steps"`，**第 1 步也没执行**（剪贴板/页面没变化）——这是"整体校验"的判据 |
| ☐ | 第 1 步放一个必然 `ok:false` 的调用（如 `tap_element` 查不存在的文字），`stop_on_error=true` | `failed_at=0`，第 2/3 步 `status:"skipped"`，且确实没执行 |
| ☐ | 同样场景传 `stop_on_error=false` | 后续步照常执行，各自有自己的 `status` |
| ☐ | 步间间隔 | 传 `delay_ms=200`，三步总耗时 ≥ 400ms |

> 证据：把 `steps[]` 数组原样贴出（含 `status`/`elapsed_ms`/`reason`）。

## E. 回归底线（确认没把老功能弄坏）

| 勾 | 项 | 判据 |
|---|---|---|
| ☐ | 租约 | `python3 scripts/smoke_lease.py --url http://<host>:8766/mcp` 应 12/12。**实测最好成绩 11/12**（2026-11-27，唯一 FAIL 是续租判据用 `idle==0`，已在 `b3770a9` 改成比较 `last_used_at`；修后**尚未重跑**到 12/12） |
| ☐ | 截图/点击 | `take_screenshot` + `tap_element(query=…)` 正常 |
| ☐ | human_dom | `human_dom_status()` 正常返回；`human_dom_fill` 一次成功（带 profile） |
| ☐ | 会话稳定 | 连续操作 10 分钟后 `get_status()` 仍可调，`~/.agent-fleet/session-audit.log` 无异常增长 |

---


---


---

## 验收的「最小可交付」

时间有限时，按这个顺序做，前面的做完就可以先回执：

| 优先级 | 项目 | 为什么它排前面 |
|---|---|---|
| **P0** | `smoke_ops --probe` + `smoke_ops` 全量 | 一次覆盖 12 条判据里的大部分；`--probe` 零副作用，随时可跑 |
| **P0** | B1（后台标签语义） | 这是 `eval_in_profile` 最容易被误解的行为，必须验 |
| **P0** | B3（UIA 卡死回归） | 只验"有没有在 10s 内返回"，一条命令 |
| P1 | B4（中文逐字节点） | 取决于该应用是不是逐字节点，可能 N/A |
| P2 | B2（剪贴板粘贴保真） | 已在 v3 首次实测：结构/乱码/段距 **通过**；`border-left` 与字数比因"稿源无 style、草稿非空"**未测**——下次用「带 border-left 的稿源 + 空草稿」四项一次量全 |


---

## 第二轮真机读数（2026-11-27，`31cd40e`）

> 出处：`agent:device-operator-lead` 第二次验收；基线 **`31cd40e`**（他拉到时的 tip），
> 设备 `test-win11` / profile `~/.fleet/publisher`，8766 旧码未动，用 worktree 起 8767 同码实例。
> **注意**：他验的这个提交**早于**三项修复（`6e01184` 加 `url_part`/`target_id` 与判据修正、
> `bdd95d7` 兼容 MCP SDK 1.x/2.x），所以下面标「已修」的两条是**上一版就修掉了**，
> 不是遗留缺陷；另外两条（`list_windows` 裸异常、同标题窗口歧义）由 `73dc997` 修掉。

| 项 | 读数 | 定性 |
|---|---|---|
| devtools enabled / `cdp_port` | 4 tools；port=51392 | ✅ |
| `list_tabs` | 33 tabs / 313ms | ✅ |
| `activate_tab` + 可见性 | 目标页变 visible | ✅ |
| `eval_in_profile` | `page_ambiguous` | ❌ 契约缺口 → **`6e01184` 已加 `url_part`/`target_id`** |
| 超限拒绝 | 先撞 `page_ambiguous`，未到 `result_too_large` | ❌ 同上（修后应可真验到） |
| `list_windows`（smoke） | 562ms 正常返回，被脚本判 FAIL | ❌ **判据 bug** → `6e01184` 修 |
| B1 后台标签 | `activate_tab` → `PAGE_AMBIGUOUS(candidates:2)`；`eval_in_profile` → `page_ambiguous(candidates:10)` | ❌ **契约缺口**（`url_part`/`target_id` 已补）；但「后台标签 ⇒ 冻结」这个前提在现场**不成立**，见下 |
| B2 剪贴板写入 | `bytes:303, attempts:1, verified:true, formats:["HTML Format"], only_html_format:true` | ✅ 前半通过；后半（读正文核对样式）被上面的 eval 问题挡住 |
| B3 UIA 卡死 | StarBeam(Electron) 前台 → `dump_ui(max_depth=4)` **3609ms**，`uia_budget_s:8.0` | ✅ 有界返回 |
| B4 中文逐字节点 | 设备无微信 PC 端；StarBeam 的 UIA 树 depth4 全空 Pane，`find_elements("订阅")` → `count:0`, `glyph_merge.applied:true` | ⛔ **环境不具备**（N/A） |
| 异常① | 一次 `list_windows` **11984ms** + 裸 `OSError [Errno 22] Invalid argument` | ❌ → **`73dc997` 兜住非超时异常**。⚠️ 我先前推断「必然是旧码 8766」，被对方用 `start_process` 记录的命令行**证伪**：那次打的是 8767（新码）。**已在第四轮（v3）定论**：`dump_ui` 的 8s 预算客户端实测 9797ms ⇒「预算 ≈ 10s 墙钟」，11.98s 属正常量级；且 `dump_ui` 当时不打日志（`c7862fd` 已补）|
| 异常② | `find_elements(window_title="StarBeam")` 两窗口时抛裸异常 `There are 2 elements that match the criteria` | ❌ 既有 bug → **`73dc997` 起返回 `reason:"ambiguous_window"` + candidates** |
| 交叉证据 | 裸客户端打旧码 8766 的 `list_windows` → `Output validation error: 'result' is a required property` | 佐证旧码该工具在严格客户端下本来就是坏的 |

**现场收拾**：对方已 `git worktree remove`、kill 8767、release 租约；证据留在
`C:\Users\qjl\af-p0p1-evidence\`，实验记录在 `device-operator/labs/2026-11-28-win-p0p1-acceptance/README.md`。

**他的自我批评（值得记）**：11984ms 那次没记下前台窗口与连的是哪台 server，因此无法定性——
下次同类现象要同时记「连的 host:port + 前台窗口 + 是否锁屏」。

**结论**：没有实现 bug 的硬证据；两条是判据/契约问题（均已修），一条是既有 bug（已结构化），
一条是环境不具备。


---

## 第三轮：A 组复验通过（2026-11-27，`d39b3d1`）

> 出处：`agent:device-operator-lead` 按新 tip 复验，side-car 8767，profile `~/.fleet/publisher`
> （**34 个标签页**的运营 profile，不是干净 profile）。这是他第一次给出"全绿"的 A 组结论。

| 脚本 | 结果 | 关键读数 |
|---|---|---|
| `smoke_ops` | ✅ **exit=0，12/12** | `list_windows returned 15 item(s) in 389ms`；`run_actions rejects whole batch up-front: rejected before running; 15 tools allowed` |
| `smoke_devtools` | ✅ **exit=0，7/7** | `eval_in_profile read: visibilityState='visible' size_bytes=9`；`oversize rejected, not truncated: size_bytes=4098 (>1024)`；`activate_tab` 后标签可见 |

**这两条正是前两轮的 FAIL**：`list_windows` 的 `{"result":[...]}` 判据、`eval_in_profile` 的多标签选页。
现在在 34 标签的真实 profile 上通过——说明修复在真实工况下成立，不是干净环境下的巧合。

### B1 的新读数（并修正判据）

```
eval_in_profile(js="1", url_part="appmsgid=100000037", activate=False)
→ {ok:true, value:1, activated:false, size_bytes:1, elapsed_ms:62}
eval_in_profile(..., 默认参数)
→ {ok:true, value:"visible", activated:true, elapsed_ms:9265}
```

- `url_part` 在 34 标签下**命中唯一页**，`page_ambiguous` 不再出现 —— 这一维通过；
- 但「后台标签 ⇒ `frozen_background_tab`」**不成立**：切后台只是隐藏，Chrome 只在内存压力或
  长时间后台才冻结渲染进程。判据已改为可稳定判定的语义（见「B1 判据修正」一节）；
- 附带观察：`activate=True` 花了 **9265ms**，贴着超时线。已给 `eval_in_profile` 加
  `timings:{connect_ms, activate_ms, eval_ms}`，下次可直接定位是哪一段慢。

### `target_id` 回退路径怎么验（真机不现实，离线可证）

真机上要自然出现"所有 http 标签 URL 都重复"几乎不可能（他 36 个标签里只有 5 组重复、仍有大量唯一 URL）。
所以这条路径的验证方式改为**离线构造 + 单测**：

```python
from capabilities.devtools._devtools import normalize_tab
from smoke_devtools import choose_target

tabs = [normalize_tab({"id": "A", "url": "https://x/dup", "title": "1"}),
        normalize_tab({"id": "B", "url": "https://x/dup", "title": "2"})]
assert choose_target(tabs) == ("", "A")      # 全部重复 ⇒ 退回 target_id
```

`scripts/tests/test_smoke_devtools.py::test_choose_target_falls_back_to_target_id_when_all_urls_duplicate`
就是这个断言。**历史教训**：最初夹具手写成 `{"id": …}`，与"读错字段"的实现互相印证，
把死代码测成了活的；现在夹具一律由真实 `normalize_tab` 生成，形状漂移会被立刻发现。


---

## B2 复验夹具（补 `border-left` 与字数比两项，一次跑完）

> v3 的成绩：结构完整、无乱码、段距 24px 三项通过。剩下两项没测，原因是**现场条件**：
> 稿源没带 `border-left`；草稿里原有 15 字，字数比不可比。下面把这两个条件都造好。

**前置**：草稿正文**全选删除**（空草稿），并确认光标在正文里。

**稿源（已算好字数，直接抄）**

```python
clipboard_set_html(content=(
    "<h2 style='border-left:4px solid #07c;padding-left:8px'>B2 复验标题</h2>"
    "<p>第一段：结构校验</p><p>第二段：间距校验</p>"
))
```

纯文本字符数：**23**（含标题与两段，其中 1 个空格）。**实测编辑器不计空格 ⇒ 读数 22**。

**期望读数**

| 项 | 期望 | 说明 |
|---|---|---|
| `h2` 数量 | 1 | 标题被识别为 H2 |
| `h2[0].bl` | **4px** | `border-left` 保真（v3 那次是 0px，因为稿源没写） |
| `pCount` | 2 | 两个段落 |
| `gaps[0]` | 20–34px | 段间距（v3 实测 24px） |
| `\ufffd` | 0 | 无乱码 |
| `len` / `nb` | **23**（或 22） | 空草稿 ⇒ 字数比这次**可比** |

**判据写法（避免又出现"无有效读数"）**：粘之前先 `eval_in_profile` 读一次空草稿的
`len`（应为 0）；粘完再读一次，断言 `after - before == 22`（实测：23 个字符含 1 个空格，编辑器不计空格）。这样即使编辑器
有隐藏字符，差值仍然可信。

**收尾**：`press_key("ctrl+z")` 撤销，回读确认草稿为空。**不要点发表/群发。**

**夹具已离线自检过**（不是"看着像能跑"）：

```
build_cf_html(夹具)         → 307 bytes；StartHTML=105、StartFragment=117、EndFragment=275
extract_fragment(...)       → 与原文完全一致
readback_ok(written, same)  → (True, "bytes_equal")
```

所以在真机上若出现"写进去的东西不对"，那是**编辑器/粘贴链路**的问题，不是夹具本身坏了——
这条区分能省掉一轮排查。


### 仍未闭环

- ~~`list_windows` 11984ms 与"8s 预算为何没收住"~~ → **已在第四轮（v3）定论**：`dump_ui` 的 8s 预算
  客户端实测 **9797ms**（"预算 ≈ 10s 墙钟"），11.98s 属正常量级；且 `dump_ui` 当时不打日志
  （`c7862fd` 已补，判据从此对称）。
- ~~B2 后半尚未执行~~ → **第四轮（v3）已首次实测**：结构/乱码/段距三项通过；`border-left` 与
  字数差值因现场条件未测，夹具已备好（见「B2 复验夹具」）。

## B 组最小执行脚本（复制即可跑，约 6 分钟）

> 这四条脚本覆盖不到（需要"制造状态"或输入类操作），但工具调用可以照抄。
> 下面 `P` = 你正在用的 profile 串（与 `human_browser_open` 用的**同一个**值）。

### 如何确定性地触发冻结（两条都行，任选其一）

**为什么需要**：切后台只是隐藏，Chrome 只在内存压力或长时间后台才冻结渲染进程。
所以"后台 ⇒ frozen"这条负向判据在现场跑不出来，必须**主动**冻结。

**方法 A · chrome://discards（零代码，手工）**

1. 地址栏打开 `chrome://discards`；
2. 找到目标标签那一行（按 URL 认），点右侧 `Freeze`；
3. 回到标签页应看到"已冻结"提示，然后跑 `eval_in_profile(..., activate=False)`。

**方法 B · CDP 直接改生命周期（可脚本化）**

在浏览器级 CDP 连接上对该 tab 的 session 发：

```json
{"method": "Page.setWebLifecycleState", "params": {"state": "frozen"}}
```

解冻用 `{"state": "active"}`。用我们自己的 `_cdp` 原语即可：

```python
import sys
sys.path.insert(0, "platforms/common")
sys.path.insert(0, "platforms/common/capabilities/devtools")
import _cdp
from _devtools import resolve_udd            # profile 串 → user-data-dir 绝对路径

udd = resolve_udd(profile)                    # 与 human_browser_open 用的是同一个 profile 串
sock, port = _cdp.connect_browser(udd, 3.0)   # 浏览器级连接
pages, _reason = _cdp.page_targets(port)
page = next(p for p in pages if "about:blank" in (p.get("url") or ""))
page_sock = _cdp.ws_connect(page["webSocketDebuggerUrl"], timeout=3.0)
_cdp.call(page_sock, 1, "Page.setWebLifecycleState", {"state": "frozen"}, timeout=3.0)
_cdp.close_quietly(page_sock)
_cdp.close_quietly(sock)
```

> 注意：方法 B 会让**当前标签**进入冻结态，操作员用真实 profile 时请只在临时标签
> （`about:blank`）上做，做完 `{"state": "active"}` 解冻。

### B1 判据修正（真机实测后）

原先写的是「`activate=False` 打后台标签必须返回 `frozen_background_tab`」。真机实测（34 标签的运营 profile）：

```
eval_in_profile(js="1", url_part="appmsgid=100000037", activate=False)
→ {ok:true, value:1, activated:false, size_bytes:1, elapsed_ms:62}
```

**后台 ≠ 冻结**：切到后台只是隐藏，Chrome 只在内存压力或长时间后台才冻渲染进程。所以原判据依赖一个
当前环境不会自然出现的前提，无法跑绿。改成可稳定判定的那部分语义：

| 断言 | 期望 |
|---|---|
| 不抢焦点 | `activated:false` |
| 结果二选一 | 要么 `ok:true` 且 `value` 存在（页面未冻结），要么 `ok:false` + `reason:"frozen_background_tab"`（真的冻结了） |

想真正验证"冻结"这条分支，需先在 `chrome://discards` 手动 Freeze 该标签再跑——属于额外加深项，不作为验收门槛。

### B1 · 后台标签语义（2 分钟）

```
1) human_browser_open(url="about:blank", profile=P, activate=True)
2) 按下面「如何确定性地触发冻结」把 about:blank 这个标签冻上
3) list_tabs(profile=P)                    → 记下 about:blank 的 url 片段（记为 U1）
4) devtools.eval_in_profile(profile=P, js="1", url_part=U1, activate=False)
   期望：{ok:false, activated:false, reason:"frozen_background_tab"}    ← 这一条才验"冻结"
5) devtools.eval_in_profile(profile=P, js="1", url_part=U1)          # 默认 activate=True
   期望：{ok:true, activated:true, value:1}                              ← 自动解冻并求值
6) 收尾：解冻/关掉 about:blank 标签
```

判据：第 4 步 **必须同时**满足 `ok=false` 且 `reason=frozen_background_tab`（不接受只判 `ok=false`）；
第 5 步 `activated=true` 且 `value=1`。

### B2 · 剪贴板保真（2 分钟）

```
1) clipboard_set_html(content="<h2 style=\"border-left:4px solid #07c\">测试标题</h2><p>第一段</p><p>第二段</p>")
   期望：ok=true、verified=true、formats=["HTML Format"]
2) 打开公众号草稿编辑器正文，press_key("ctrl+v")
3) eval_in_profile(profile=P, url_part="<编辑器页 url 片段>", js="<verify_js>")
   期望读数：正文字数 = 稿源字数；h2Count = 1；无 \ufffd；H2 的 borderLeft=4px；相邻 <p> 间距≈20px
```

判据：`formats` **恰好** `["HTML Format"]`；字数/标题数一致；样式三项（borderLeft / 段间距 / 无乱码）符合。
**做完删掉临时草稿。**

### B3 · UIA 卡死回归（1 分钟）

```
1) 打开微信 PC 客户端（或任一 Electron 应用）并让它在前台
2) dump_ui()          → 记耗时
   期望：要么 ok=true，要么 ok=false + reason="uia_timeout"；**总耗时 ≤ 10s**
3) list_windows()     → 期望很快返回（list，不是 dict）
```

判据：**只看"有没有在 10s 内返回"**，返回什么都行。

### B4 · 中文「一字一节点」（1 分钟）

```
1) 在同一个 Electron 应用里，find_elements(query="设置")   → 期望能看到 merged:true 的候选
2) tap_element(query="设置")（如果它确实是个可点元素）
   期望：返回带 clicked_text_span，落点在"设置"两个字上
```

判据：`merged:true` 出现；`tap_element` 的 `clicked_text_span` 文本等于查询词。
若该应用不是逐字节点（中文合并不会触发），这条记 `N/A` 并注明应用名。

### 回执只要这三行

```
B1 = pass/fail（reason=?）   B2 = pass/fail（字数=? 样式=?）
B3 = pass/fail（dump_ui 耗时=?ms）   B4 = pass/fail/N-A（应用名=?）
```

## 首轮真机读数（2026-11-27，第一轮）

> 出处：`agent:device-operator-lead` 在真机上跑的**第一轮**结果；基线 commit `31cd40e`，
> 执行方式为 `git worktree` + 同码实例跑在 `127.0.0.1:8767`（8766 旧码未动）。
> 以下是他回传的原始读数，未经我改写；标注「判据 bug」的两条已在 `6e01184` 修复。

| 项 | 读数 | 结论 |
|---|---|---|
| 5 个新工具注册 | 全部在 `core.tools` | ✅ |
| 二进制往返 | sha256 一致 | ✅ |
| 76 列折行 base64 | 被接受 | ✅ |
| 5 MiB 超限 | `file_too_large` 且未落盘 | ✅ |
| 剪贴板 | `formats=["HTML Format"]`、回读通过、`attempts` 正确 | ✅ |
| `wait_for` 预算 | 327ms（预算 300ms） | ✅ 预算被执行 |
| `run_actions` | 顺序执行 + 非法整批预校验 | ✅ |
| `dump_ui` | **6218ms** 返回 | ✅ 有界（预算 8s），未卡死 |
| `find_elements` | 1483ms | ✅ |
| `list_tabs` | 33 tabs / 313ms | ✅ |
| `activate_tab` | 目标页变 visible | ✅ |
| `list_windows` | 562ms 返回，被脚本判 FAIL | ❌ **判据 bug**（FastMCP 把 `list[dict]` 包成 `{"result":[…]}`），已修 |
| `eval_in_profile` | `page_ambiguous`（该 profile 33 个标签页） | ❌ **设计缺口**，已加 `url_part`/`target_id` |
| `--profile` 带引号 | `port_file_missing` | ❌ **文档 bug**（PowerShell 把引号传进路径），脚本已剥引号、文档已改 |

**设备租约旁证**：同期 8766 被 `line-t1-779` 持有（idle 54s、auto_release ≈546s），
他的设备调用被 `device_leased` 拒绝——这是强制租约的**预期行为**，不是缺陷。

**当时尚未验证**：B 组（后台标签冻结、剪贴板粘贴保真、UIA 卡死回归、中文元素
`merged`/`clicked_text_span`）——它们需要输入类操作，必须等设备空闲。
**后续进度（见下文第二/三/四轮）**：B3 已通过；B1 的选页维度已通过、冻结分支待定；
B2 后半已在 v3 实测三项通过（`border-left` 与字数比因现场条件未测）；B4 环境不具备（N/A）。


---


---


---

## 基线演进（对方每次验证的是哪个提交，以及之后改了什么）

> 这条链是为了解决一个反复出现的沟通成本：**"你验的是哪个 commit"**。
> 每次给对方的基线都记在这里；他自己也能对照"我验完之后又变了什么、要不要重跑"。

| 基线 | 谁验的 | A 组结果 | 之后到下一个基线改了什么 |
|---|---|---|---|
| `31cd40e` | device-operator 第一轮 | 5/7 + 11/12 | `6e01184` 修判据（`{"result":[…]}`）、加 `url_part`/`target_id`、剥 `--profile` 引号 |
| `d39b3d1` | device-operator 第二轮（含 B 组） | 12/12 + 7/7 ✅ | `73dc997` `list_windows` 兜异常 + `ambiguous_window`；`846ed7b` 文档更正 |
| `846ed7b` | 我提出的稳定基线（未单独验证） | — | 见下表 |
| **`693a47d`** | 当前 tip | 待验 | — |

### `846ed7b` 之后改了什么（按"会不会影响 A 组判据"分类）

**会影响行为、建议重跑 A 组**：

| 提交 | 改动 | 影响面 |
|---|---|---|
| `a373886` | `eval_in_profile` 返回 `timings{connect_ms, activate_ms, eval_ms}` | 只增字段，判据不受影响 |
| `4905ed7` | `list_windows` 超 5s 打印慢调用日志 | 只增日志 |
| `08a5d20` + `174522b` | `wait_for(text)` 单次探测预算 8s → 4s | `wait_for` 时序变化（防假阴性） |
| `031cde7` | `wait_for` 新增 `probe_failed` reason | 判据需知道有两种 reason |
| `0495ac4` | `_cdp.call()` 超时真正生效 | CDP 调用不会再多等 5s |
| `693a47d` | `connect_browser` 预算下传 | 连接更守时（可能缩短 evals） |

**纯文档**：`33d65cd`（性能基线）、`8c948a4`（冻结方法）、`4ebda47`（docstring）。

**结论**：`wait_for` 的两条改动（8s→4s、新增 `probe_failed`）与 CDP 两条超时修复是真正的行为变化；
`smoke_ops` 的 12 项判据里只有 `wait_for honours budget` 一项与它相关，其余不受影响。

## 性能基线（2026-11-27，`test-win11`，散落各轮回执的读数汇总）

> ⚠️ 这不是 benchmark harness 的产物：每条都是**一次**真机调用的观测，机器同时有别的
> agent 在用（租约频繁易手）。用途只有一个——以后有人说"变慢了"，能拿这张表对照，
> 而不是凭感觉。数值随机器负载、前台窗口类型、profile 标签数变化。

| 原语 | 读数 | 当时条件 | 出处 |
|---|---|---|---|
| `dump_ui` | **3609ms** | StarBeam(Electron) 前台，`max_depth=4`，`uia_budget_s=8.0` | 第二轮 B3 |
| `dump_ui` | 6218ms | 第一轮，前台应用未记录 | 首轮读数 |
| `find_elements` | **1483ms** | 第一轮，token 查询 | 首轮读数 |
| `list_windows` | **389ms** | 15 个可见窗口 | 第三轮 smoke_ops |
| `list_windows` | 562ms | 同批另一次 | 首轮读数 |
| `list_tabs` | **313ms** | 33 个标签页（并发探测，总预算 300ms） | 首轮读数 |
| `eval_in_profile(activate=False)` | **62ms** | 34 标签 profile，`url_part` 命中唯一页 | 第三轮 B1a |
| `eval_in_profile(activate=True)` | 9265ms | 同上页面；**单次观测**，疑似激活阶段慢（已加 `timings` 分解） | 第三轮 B1b |
| `clipboard_set_html` | 一次成功 | 303 字节，`attempts=1`，回读字节相等 | 第二轮 B2 |
| `wait_for(kind=text)` | 327ms | 预算 300ms，条件很快成立 | 首轮读数 |
| `activate_tab` | 一次成功 | 34 标签下按 `url_part` 命中 | 第三轮 |

**阈值速查**（这些是代码里真实存在的可调项，不是随口写的）：

| 环境变量 / 常量 | 默认 | 作用 |
|---|---|---|
| `FLEET_UIA_TIMEOUT` / `UIA_TIMEOUT_S` | 8s | Windows UIA 遍历/枚举的硬预算；超时返回已收集部分 |
| `FLEET_UIA_SLOW_LOG` / `UIA_SLOW_LOG_S` | 5s | 超过即打印"完成了但很慢"，用于区分服务端慢与客户端开销 |
| `FLEET_AX_TIMEOUT` / `AX_TIMEOUT_S` | 8s | macOS AX 遍历预算 |
| `ACTIVATE_TIMEOUT` | 3s | CDP `Target.activateTarget` 单项超时 |
| `EVAL_TIMEOUT` | 见代码 | `Runtime.evaluate` 单项超时 |
| `_batch.MAX_STEPS` | 25 | 单批步数上限 |
| `_wait.MAX_TIMEOUT_S` | 60s | `wait_for` 预算的硬上限（默认 10s） |
| `_fsops.MAX_TRANSFER_BYTES` | 4 MiB | 原始字节上限（base64 后 ~5.6 MiB），超限 `file_too_large` |


---


---

## 第四轮（v3）：B2 后半首次实测 + 11984ms 定论（2026-11-27，`d417e97`）

> 出处：`agent:device-operator-lead`，基线 `d417e97`（`846ed7b` 是其祖先），
> side-car 8767，profile `~/.fleet/publisher`（**36 个标签页**）。这次 server stderr 落盘
> （`server_8767.log`），不再丢日志。

### A 组

| 脚本 | 结果 | 备注 |
|---|---|---|
| `smoke_ops` | ✅ **12/12** | `dump_ui` **9797ms** 返回 `uia_timeout`（有界，不是卡死）；`list_windows` 15 items / 530ms |
| `smoke_devtools` | ❌ 3/6 | `eval_in_profile` / oversize / `activate_tab` 全报 `page_ambiguous` —— **不是工具回归**，见下 |

**3/6 的真因（我方判据 bug）**：脚本取"第一个 http 页的完整 url"当 `url_part`，而该 profile 的
36 个标签里 `https://www.zhihu.com/creator/manage/creation/all` 出现 **2 次**（`_v3_tabs.json` 显示
共 5 组重复，toutiao/graphic/publish 各 3 次）⇒ `match_pages` 命中 2 条 ⇒ ambiguous。
**修法（`3ec4b00`）**：`choose_target()` 优先取唯一出现的 url，全部重复时退回 `target_id`；
`activate_tab` 也补了 `target_id`。**该修复尚待真机复验**（对方已同意用这 5 组重复做靶子）。

### B2 后半：富文本粘贴保真（首次实测）

```
clipboard_set_html → {ok:true, bytes:369, attempts:1, verified:true,
                      formats:["HTML Format"], only_html_format:true}
粘进 appmsgid=100000037 正文（ctrl+v）后 eval 读数：
  {src:59, nb:78, ufffd:0, h2:[{t:"验收标题：剪贴板保真", bl:"0px"}], pCount:2, gaps:[24], len:84}
收尾：ctrl+z 撤销 → {len:20, h2:0, p:0}，草稿恢复原样；**未点发表**
```

| 判据 | 读数 | 结论 |
|---|---|---|
| 结构完整（H2 + 2×`<p>`） | `h2=1, pCount=2` | ✅ |
| 无乱码 | `� = 0` | ✅ |
| 相邻段落间距 | `gaps:[24]` px（文档区间 20–34） | ✅ |
| `border-left` 保真 | `bl:"0px"` | ⚠️ **未测**：稿源本身没写 `style="border-left:…"`，要测得换稿源 |
| 字数比 | `src:59 / nb:78` | ⚠️ **无有效读数**：草稿原有 15 字，`nb` 是"原有+新粘"合计；要空草稿或全选覆盖才可比 |

### 激活耗时（同一 profile，10 分钟内）

```
eval(activate=True) → cdp_timeout 3327ms
activate_tab        → cdp_timeout 3077ms
activate_tab        → ok 296ms
activate_tab        → ok 297ms
```

⇒ **浏览器忙时 3s 会超时、空闲时 300ms 就够**。已据此加"失败重试一次"（`3ec4b00`），
并把语义写进 playbook：激活失败按**"可以继续但没焦点"**处理，不判死整条链路。

### 11984ms：定论（撤回我此前的"未解"）

对方两条旁证：

1. `dump_ui` 超时**此前不打日志**（只有 `list_windows` 打）⇒ 我那句"日志里两行都没有 ⇒ 正常返回"
   对 `dump_ui` **不成立**（已在 `c7862fd` 给它补上留痕，判据从此对称）；
2. 同一轮 `dump_ui` 的 **8s 预算客户端实测 9797ms** ⇒ **"8s 预算 ≈ 10s 墙钟"**（收尾/客户端开销）。

⇒ **11.98s 落在"预算 + 收尾"的正常量级，不是预算失效**。此条从"未解异常"改为**已解释**。

### 仍未闭环

- `choose_target` 的 `target_id` 回退路径：**代码已就位，真机待验**（对方 2 分钟可跑）；
- `border-left` 保真与字数比：需"带 style 的稿源 + 空草稿"，对方已同意下次一并量；
- B4（中文逐字节点）：设备无微信 PC 端，N/A。

## 合并前合规自查（可复跑，30 秒）

```bash
# 1) DCO：分支内每个提交都要有 Signed-off-by（CONTRIBUTING.md 硬约束）
base=origin/main; total=0; bad=0
for c in $(git rev-list "$base"..HEAD); do
  total=$((total+1))
  git log -1 --format=%B "$c" | grep -q "^Signed-off-by: " \
    || { bad=$((bad+1)); echo "missing: $(git log -1 --format='%h %s' "$c")"; }
done
echo "commits=$total missing_dco=$bad"

# 2) 与 main 的关系（0 behind 才没有冲突风险）
git fetch origin --quiet && git rev-list --left-right --count origin/main...HEAD

# 3) 三道文档/蓝图门禁
python3 scripts/gen_docs.py --check
./scripts/gen-blueprint-map.sh --check
./scripts/gen-blueprint-interface.sh --check && ./scripts/check-blueprint-refs.sh --check
```

**4) 生成器幂等**（`--check` 只验数字，`--write` 才能证明文档与生成器**完全一致**）：

```bash
python3 scripts/gen_docs.py --write     # 应打印 "No change — ... already up-to-date"
./scripts/gen-blueprint-map.sh          # 重写后 git status 必须为空
./scripts/gen-blueprint-interface.sh
git status --porcelain docs/            # 空 = 零漂移
```

**2026-11-27 末实测**：`commits=124 missing_dco=0`；`0 124`（main 仍 `386814c`，无冲突）；
三道门禁全绿；**生成器幂等**（`gen_docs --write` 报 no change、蓝图重写后 `git status` 为空）。CI 里 `python-tests` 是 `continue-on-error`、`gen_docs` 与 `platforms/**` 测试
**不进 CI**，所以这三项必须本地跑。



---

## 第五轮（v4）：`smoke_devtools` 7/7 全绿（2026-11-27，`c7862fd`）

> 出处：`agent:device-operator-lead`，36 标签的运营 profile，`exit=0`。

| 检查 | 读数 |
|---|---|
| devtools capability | enabled，4 tools |
| `cdp_port` | port=51392，`Chrome/158.0.8127.36`，probe 30ms |
| `list_tabs` | **36 tabs / 328ms**（33 个 unknown：并发探测预算内没赶上） |
| `eval_in_profile` | `visibilityState='visible'`，9 bytes |
| 超限拒绝 | 4098B > 1024 被拒且**不截断** |
| `activate_tab` | 命中 `zhuanlan.zhihu.com/p/…/edit`（**唯一 url**） |
| activate 后可见 | 是 |

⇒ 之前两条 FAIL（`page_ambiguous`）消失。**但要注意它验的是哪条规则**：

| 规则 | 状态 |
|---|---|
| 规则 1：优先取**只出现一次**的 http url | ✅ **真机已验证**（7/7，36 标签，命中的是唯一 url） |
| 规则 2：所有 http url 都重复时回退 `target_id` | ⚠️ **未在真机验过**；且 `c7862fd` 上这条是**死代码**（读 `tab["id"]`，而契约是 `target_id`）——已在 `2b52c89` 修正，并有单测 + 对方离线构造数据双证（全重复 4 条 → 退回 target_id）。真机要验需构造"所有 URL 重复"的 profile，属可选加深项 |

**对方主动撤回了自己上一轮的说法**（"`_v3_tabs.json` 会自动走 target_id"）——那份数据有大量唯一 url，根本到不了回退分支。这种自我纠正值得记下来：**只验了规则 1，就不要说规则 2 已验证**。


---

## 第六轮（v5）：`--target-id-check` 8/8 —— target_id 管线真机通过（2026-11-27，`96626b8`）

> 出处：`agent:device-operator-lead`，36 标签运营 profile。新增的那一项：

```
PASS  eval_in_profile via target_id: target_id=8019134FCD10842B8F0866FCE62B6DE9 value=1 | target=id:8019134F…
```

**意义**：规则 2（全全重复时回退 `target_id`）的真正风险不在"能否选中"，而在**下游
`target_id` 管线能否跑通**。现在真机直传 `target_id` 调 `eval_in_profile` 拿到 `value=1`，
这条管线成立（不再只靠单测）。

| 规则 / 管线 | 状态 |
|---|---|
| 规则 1：优先取唯一 url | ✅ 真机已验证（v4，7/7） |
| **`target_id` 管线（下游）** | ✅ **真机已验证（v5，8/8）** |
| 规则 2：全 url 重复时 `choose_target` 的返回 | ⚠️ 代码已修（`2b52c89`）+ 离线构造数据覆盖；**未真机验**（需构造全重 profile，属可选加深项） |

### 附：`list_tabs` 四组读数与"unknown ∝ duration"规律

| tabs | unknown | duration_ms | 备注 |
|---|---|---|---|
| 34 | 28 | 313 | 预算内多数探完 |
| 36 | 36 | 391 | 预算打满 |
| 36 | 33 | 328 | — |
| 36 | 36 | 483 | 预算打满的一侧 |

规律：**unknown 数与 `duration_ms` 正相关**——耗时越长说明探测越没赶上预算。
这比单看"unknown 比例"更有解释力：`unknown 多 + duration ≈ probe_budget_ms` 就是"预算内没探完"，
而不是"标签是坏的"。

### 附：这台机器上 server 启动要 2–4 分钟（不是卡死）

对方实测：8767 起服务约 **3 分钟**（python 被其它工作饿着），而跑一次 smoke 只要 5 秒。
所以：

- `git pull` 后重启 server 时，**别把"3 分钟没有响应"当成起不来**；
- 现场排障请让 server 的 stdout/stderr **落盘**（他这轮起服务写了 `server_8767_v5.log`），
  靠会话缓冲会丢日志。


---

## 第七轮（v6）：B2 四项一次量全 —— 全绿（2026-11-27，`8dfdb8f`）

> 用本文档「B2 复验夹具」的专用稿源跑的。全选正文 + `ctrl+v` 后读数：

```
clipboard_set_html → {ok:true, bytes:307, attempts:1, verified:true,
                      formats:["HTML Format"], only_html_format:true}
粘贴后 → {len:27, nb:22, ufffd:0, h2:[{t:"B2 复验标题", bl:"4px"}],
          pCount:2, gaps:[24], txt:"B2 复验标题 / 第一段：结构校验 / 第二段：间距校验"}
```

| 判据 | 读数 | 结论 |
|---|---|---|
| h2 数量 | 1 | ✅ |
| **`border-left`** | **4px** | ✅（v3 那次 0px 是稿源没写 style，这次补上了） |
| pCount | 2 | ✅ |
| 相邻段距 | 24px（区间 20–34） | ✅ |
| 乱码 | `\ufffd = 0` | ✅ |
| 字数 | **22 / 22 = 100%** | ✅ **且 `nb=22` 正是"编辑器忽略空格"的取值** |

**收尾**：`ctrl+z` → `{len:20, h2:0, p:0}`，草稿恢复原样，**未点发表**。

⇒ **B2 整条记 PASS**，不再有"未测/无有效读数"。

### 把之前的"23 或 22"收敛为 22

夹具纯文本是 23 字（含 1 个空格），编辑器不计空格 ⇒ `nb=22`。所以判据应写成
**差值 == 22**（本文档原写"23 或 22"，现按实测收敛）。

### 附：`--freeze-check` 没跑成（环境不具备，不是脚本问题）

该 profile 里没有 `about:blank`，脚本按设计记 skipped。对方尝试用原始 CDP
`Target.createTarget(about:blank)` 临时建一个，但 3s 预算下超时（浏览器正忙）：
`{reason:"cdp_timeout", message:"Target.createTarget timed out"}`——**没建成就没留任何标签**。
此项保持**可选加深项**。

### 附：激活重试的真实边界（现场读数印证设计）

```
activate_tab → 6703ms 双次超时（= 3s + 0.2s + 3s）
activate_tab → 172ms 成功（紧接着下一条命令）
```

⇒ 重试覆盖的是**短时抖动**；对"浏览器忙几秒"这种窗口，调用方的最佳处置仍是**降级成
`activate=false` 只读**，而不是等它成功。对方当天两次都是这么绕过去的（先只读拿到状态，
等窗口出现再动 UI）。这条与 playbook 里「激活失败 = 可以继续但没焦点」的写法一致。

## 冻结分支（`frozen_background_tab`）：已有野外观测，但仍非脚本强制触发

2026-11-27 对方在跑头条轮询时**意外**拿到了这个 reason：

```
{"ok": false, "activated": false, "reason": "frozen_background_tab",
 "error": "Runtime.evaluate timed out"}
```

场景：读取一个**长期待在后台**的草稿箱标签（不是刚切后台的），`activate=True` 后恢复正常。

⇒ 这条把 `frozen_background_tab` 从"代码里有"变成"**野外观测到**"，并澄清了触发条件：

| 说法 | 对不对 |
|---|---|
| 切到后台 ⇒ 冻结 | ❌ 刚切后台仍可求值（真机多次实测） |
| 后台停留足够久 / 内存压力 ⇒ 冻结 | ✅ 这次的野外观测 |

**但它仍是"意外拿到"而不是"我们能按需复现"**：脚本化的 `--freeze-check`（`Page.setWebLifecycleState`）
因该 profile 无 `about:blank` 未跑成。所以 B1 冻结分支的状态是：
**有野外观测证据、无脚本复现**——比"未验证"强，比"已验证可复现"弱，按这个口径引用。

## 判据自检：**"把实现改错，这条断言会不会红？"**

2026-11-27 这一天出现过三次误判，共同点是**判据与实现同源**——两边一起错，于是全绿：

| 事件 | 判据错在哪 |
|---|---|
| `list_windows` 被判 FAIL（562ms 正常返回） | 判据只认裸 `list` 或带 `ok` 的 dict，实现返回 `{"result": …}`；反过来，若实现真挂了却恰好返回 dict，它也会 PASS |
| `choose_target` 回退分支是死代码，测试全绿 | 夹具手写 `{"id": …}`，与"读 `id`"的错误实现互相印证 |
| playbook §5 读到标题长度（20 而非正文 1343） | 实现没错、页面也没错，但**判据量的不是它想量的那个东西** |

所以审阅时不必逐行读实现，只问这一句：

> **把这个判据对应的实现改成错的，这条断言会不会红？**
>
> 不会红的那条，就是"判据与实现同源"——今天这三种 bug 属于同一类。

**两档分开写**（"有测试"不等于"判据有效"——变异验证的动作是：把实现改错 → 跑 → 看它红 → 改回来）：

### 第一档：**真做过变异验证**（改坏 → 红 → 改回，提交信息里有记录）

共 **28 个提交**在做修复/加测试时做过反向验证，每条都在提交信息里写了
"把 X 改成 Y → 只红对应那条 → 恢复后全绿"。按 commit 列表（`git log --grep=反向验证`）：

| commit | 内容（截断） |
|---|---|
| `219f4e9` | test(lease): 进程内断言「设备调用会刷新 last_used_at」 |
| `9b17f34` | feat(smoke): --freeze-check 把 B1 的冻结分支变成可自动验的一项 |
| `ae52270` | test: 把 wait_for / run_actions 纳入 canonical 公约（conformance 才 |
| `efbc277` | chore(test): 自定义豁免标记不再伪装成 ruff 的 noqa 指令 |
| `5bcc907` | test(devtools): 钉住 activate_tab(PAGE_AMBIGUOUS) 与 eval_in_pr |
| `4c7a20b` | test: 新增"夹具保真度"元测试（CDP 错误必须带 message） |
| `ec52ca0` | fix(devtools): frozen_background_tab 不再把"链路故障"误判成"标签冻结" |
| `a6fb2ef` | fix(devtools): 激活重试只在真超时时发生，连接坏了不重试 |
| `2f0ae40` | test(devtools): 把 tab 的键集合钉成契约（防字段漂移静默 None） |
| `2b52c89` | fix(smoke): choose_target 回退分支读错字段（target_id vs id），等于死代码 |
| `f486f20` | test: wait_for 的三种结果在协议层如实（timeout / probe_failed / *_gone） |
| `7ea8b7b` | test: run_actions 走完整 MCP 往返（顺序执行 + 白名单拒绝） |
| `d7f25d3` | test: 集成测试补两条真实 MCP 往返（发现接口 / 结构化错误不死） |
| `bf617d5` | test(win): 真跑验证 dump_ui 的「超时即返回 + 留痕」两个性质 |
| `ee403bf` | test: 运行时 core 工具数契约扩到四平台（win 49 / mac 45 / android 33 / ios |
| `eb78cff` | test: 四平台运行时都包含 Universal Tool Set（架构文档的"✓ all"第一次被验证） |
| `4c3fbfb` | test(win): 用桩模块在 Linux 上真跑 Windows server 的判定逻辑 |
| `ce70273` | test: 用运行时 `list_capabilities` 核对移动端工具数（android 33 / ios 32） |
| `693a47d` | fix(cdp): connect_browser 的预算没传给 probe 与握手（可能多花 5s） |
| `0495ac4` | fix(cdp): call() 的超时没落到 socket 上，可能阻塞满 5s 甚至永久 |
| `4905ed7` | feat(win): list_windows 慢调用留痕，让 11984ms 这类现象可归因 |
| `706ff71` | test(mobile): android/ios 静态契约——ctx 注入 / *_gone / 批量白名单 |
| `e2265da` | test(mac): 给 mac server 的兜底接线加静态契约（AX 预算 / *_gone / 批量白名单） |
| `de4ed60` | test(win): 给"Linux 上跑不了"的 Windows 兜底逻辑加静态接线测试 |
| `09e6964` | test(docs): CHANGELOG 结构门禁（[Unreleased] 下同类小节只能一个） |
| `3792706` | test(docs): 工具数门禁扩到平台 README 与 setup guide |
| `aedb6fa` | fix(clipboard,file_put): 重试间隔真的生效 + base64 容忍折行 |
| `d6a5fdb` | fix(win,mac): 补 DevtoolsCapability 导入 + 加能力接线门禁 |

### 第二档：**仅有针对性单测**（断言存在、逻辑上覆盖该分支，但**没有**真把实现改错过）

例如 `payload_of` 的四条归一化契约、`probe_multi` 的 CLI 校验、`pick_target_id`、
`fixture` 元测试自身的豁免标记等。它们的价值是"锁住当前行为"，**不能**声称"判据已被证明有效"。

> 写 PR 时的用词：第一档可以写"已做变异验证"；第二档只能写"有针对性单测"；
> 两档都不能写"已验证实现正确"——那只由真机读数（L1–L3）承担。

**尚未做变异验证的条目**（写 PR 时不要声称"已验证"）：
- `frozen_background_tab` 的 L1 野外观测（无法按需触发，故无从"改错"）；
- 规则 2「全重复时选中」的 L0（只有离线构造数据）。

## 引用注意事项（给写 PR / 读证据的人）

1. **`§第七轮`的 §5 JS 读数来自"内容较满"的真实草稿**（1343 字，`roots.length=2`）：
   它证明的是**不会把标题当正文**，**不等于**空草稿场景也成立——空草稿是靠 B2 夹具验的（22/22）。
2. **11984ms 那条的结论是"已解释"，不是"有日志证明"**：依据是 `dump_ui` 的 8s 预算客户端实测
   **9797ms**（"预算 ≈ 10s 墙钟"）。那次 `list_windows` 的 stderr **已经丢了**，
   不要写成"日志里看到/没看到某行"作为证据。

## 引用注意事项（给写 PR / 读证据的人）

1. **§5 JS 的 1343 字读数是"内容较满"的真实草稿**（那次 `roots.length=2`）：它证明的是
   **不会把标题当正文**，**不等于**空草稿场景也成立——空草稿是 B2 夹具验的（22/22）。
   且该写法有**已知未验证边界**：页面上若挂了额外 ProseMirror（弹层/裁剪对话框），
   `last` 可能选错；防御做法已写进 playbook §5（`editorLayout=="clean"` 才可信 + §5.1 显式根）。
2. **11984ms 的结论是"已解释"，不是"日志证明"**：依据是 `dump_ui` 的 8s 预算客户端实测
   **9797ms**（"预算 ≈ 10s 墙钟"）。那次 `list_windows` 的 stderr **已经丢失**，
   不要写成"日志里看到/没看到某行"。

## 验证覆盖矩阵（2026-11-27 末，四平台可执行测试落地后）

> 这张表回答一个很实际的问题：**"这条逻辑到底被什么验证过？"**
> 四端 server 现在都能在 Linux 上 import（Windows/macOS 用桩替换 OS 依赖、Android/iOS 用
> 假 adb），所以"只有真机才知道"的范围已经明显缩小——但缩小不等于消除，见最后一列。

| 平台 | 运行时行为测试 | 静态契约（AST） | 真机验证 |
|---|---|---|---|
| Windows | ✅ `test_win_server_runtime.py`（7 条） | ✅ `test_win_server_guards.py`（5 条） | ✅ **A 组 12/12 全绿**（34 标签运营 profile） |
| macOS | ✅ `test_mac_server_runtime.py`（7 条） | ✅ `test_mac_server_guards.py`（7 条） | ❌ 无 |
| Android | ✅ `test_android_runtime.py`（12 条） | ✅ `test_mobile_server_guards.py` | ❌ 无 |
| iOS | ✅ 同上（2 条 iOS 专属） | ✅ 同上 | ❌ 无 |

**总量快照（2026-11-27 末）**：

| 套件 | 数量 | 备注 |
|---|---|---|
| `platforms/common/tests` | **506** | 含 30 条 vision（需 cv2+rapidocr） |
| `platforms/tests` | **129** | 平台/协议层契约，含 15 条夹具保真元测试等 |
| `scripts/tests` | **105** | 验收脚本与门禁 |
| `cli` | **164** | — |
| `platforms/*/server/tests` | **98**（+4 skipped） | windows 13+2 / macos 9+1 / android 63 / ios 13（Linux 靠桩跑；**四端必须逐端单独跑**——每端目录都叫 `tests`，合跑会因同名包冲突） |
| **合计** | **≈1002 通过 / 4 跳过** | 四端自带测试此前在 Linux 上根本跑不了 |

**跨平台契约**：`test_universal_tool_set.py`（21 个 universal 工具 × 4 平台 + 工具名唯一）、
`test_tool_schema_contract.py`（描述/参数说明/编排原语参数 × 4 平台）、
`test_runtime_tool_counts.py`（core 桶计数 × 4 平台）、
`test_devtools_doc_contract.py`（devtools 工具面 × 三处调用方文档）。

**协议层集成测试**（`test_lease_integration.py`，本地真起一个 MCP server + 官方 client）：

| 覆盖 | 断言要点 |
|---|---|
| 租约状态机 | A `acquire` → B 被拒（`current_holder=A`）→ B 调 core 工具得 `device_leased` → A 可用 → `release` 后新 session 立即可用 |
| 发现接口 | `list_capabilities` 经协议往返后结构正确、core 含 `list_capabilities` / `wait_for` |
| 结构化错误 | `wait_for(kind="bogus")` 返回 `invalid_kind`+`allowed_kinds`，**同一 session 后续调用仍正常** |
| 批量动作 | 两步 `tap` 顺序执行（`completed=2`）；`file_get` 被白名单拒（`invalid_steps`） |
| 等待语义 | `timeout`（`attempts≥2`）/ `probe_failed` / `text_gone` 三种 reason 在协议层如实 |

> 这套测试的由来：租约、批量、等待语义此前**只有真机才知道**。用桩把 Windows server 的
> OS 依赖替换后，可以在 CI 上真起 MCP server 验协议行为——它们不替代真机，但把
> "只有真机才能发现"的范围又缩小了一块。顺带发现一个真坑：直接 `mcp.run()` 会绕过
> `main()` 里挂的租约中间件（已记入 `AGENTS.md` §7 第 13 条）。

**运行时测试能证明什么、不能证明什么**：

- ✅ 能：判定逻辑（`timeout` vs `probe_failed`、`*_gone` 取反、批空白名单与短路）、
  预算是否真被传下去、注册面是否完整且无重复、文档所述参数是否真的存在；
- ❌ 不能：UIA/AX/WDA/adb 的真实行为、坐标正确性、真实窗口与 Electron 树的形态、
  冻结语义、剪贴板在真实应用里的保真度。

**因此仍未闭环的真机项**（截至 v3 之后）：

| 项 | 现状 | 下一步 |
|---|---|---|
| `border-left` 保真 | v3 稿源没带 style ⇒ 未测 | 用带 `style="border-left:4px …"` 的稿源 + **空草稿**，四项一次量全 |
| 字数比 | v3 草稿原有 15 字 ⇒ 无有效读数 | 同上 |
| B1 冻结分支 | 「后台≠冻结」已澄清；冻结需主动触发 | `chrome://discards` 手动 Freeze，或 CDP `Page.setWebLifecycleState` |
| `choose_target` 的 `target_id` 回退 | 规则 1 已真机验（v4 7/7）；规则 2 代码已修（`2b52c89`，此前读错字段是死代码），单测+离线构造已证 | 真机需"所有 URL 重复"的 profile，属可选加深项 |
| macOS / Android / iOS 端到端 | 运行时与协议层已有测试，**无真机记录** | 首次真机验证（与目标场景无直接关系，优先级最低） |

## `--freeze-check` 的边界（避免误用）

| 项 | 说明 |
|---|---|
| 碰哪些标签 | **只碰 `url == "about:blank"`** 的那一个；没有就记 `skipped` 并提示先开一个 |
| 会不会留残留 | 不会：`finally` 里无条件 `Page.setWebLifecycleState {state:"active"}` 解冻 |
| 在哪跑 | **必须在设备本机**（CDP 端口是设备上的 `127.0.0.1`）；连不上会明确报"连不上浏览器" |
| 判失败的情形 | 页面仍能求值（冻结没生效，不接受"切后台"冒充）、about:blank 消失、冻结调用本身报错 |
| 判 skipped 的情形 | 没有 about:blank 标签 |


## 失败归因速查（smoke 报了 FAIL 时先查这里）

> 目的是把「FAIL」在三秒内分成三类：**判据 bug（我方脚本）／实现 bug（我方代码）／环境问题（设备侧）**。
> 分类不同，处理人也不同——判据 bug 我改脚本，实现 bug 我改代码，环境问题请设备侧处理。

| FAIL 项 | 先看什么 | 大概率归因 |
|---|---|---|
| `required tools registered` | 报错里 `missing tools` 列了哪些、`got N live tools` 是多少 | 全缺 + 有 devtools ⇒ **设备跑的是旧码**（环境），不是缺陷 |
| `binary round-trip (sha256)` | `file_put` 的 sha 与 `file_get` 的 sha 是否一致 | 一个对一个是 impl；两个都错是 put 侧 impl；`ok=false` 且 reason 明确 ⇒ 先看 reason |
| `line-wrapped base64 accepted` | 报 `invalid_base64` ⇒ **实现 bug**（空白未剥离）；`ok=false` 其它 reason ⇒ 看 reason | 判据无歧义，`invalid_base64` 一定是实现问题 |
| `oversize rejected` | `reason` 是否为 `file_too_large`、`bytes` 是否 = 5 MiB+1 | reason 对但 bytes 错 ⇒ impl；reason 是 `page_ambiguous` 之类 ⇒ 判据传参问题 |
| `rich HTML clipboard + read-back` | `formats` 列表、`readback` 值 | `formats` 多出 CF_UNICODETEXT ⇒ 实现/系统合成；`verified=false` ⇒ 回读判据或落字问题 |
| `clipboard retry path reports attempts` | `attempts` 是否在 1..2 | 越界 ⇒ impl；`clipboard_busy` ⇒ 环境（有别的进程占剪贴板） |
| `wait_for honours budget` | `elapsed_ms` | 远小于预算 ⇒ impl（预算未被执行）；恰好超时 ⇒ 正常 |
| `run_actions executes in order` | 哪一步 `status` 不是 ok | 单步失败 ⇒ 看该步 reason（多半是环境，如前台不是目标窗口） |
| `run_actions rejects whole batch up-front` | 是否 `invalid_steps` + 无 steps | 有 steps ⇒ impl（先跑了再拒） |
| `dump_ui / list_windows / find_elements returns within budget` | 耗时数字 | 耗时 < 预算+余量却判 FAIL ⇒ **判据 bug**（形状不认识）；耗时超限 ⇒ impl（预算没生效） |
| `devtools capability enabled` | `status` 字段 | `disabled` ⇒ 配置被覆盖（环境）；`not registered` ⇒ 旧码（环境） |
| `cdp_port` | `reason` | `port_file_missing` ⇒ 没开浏览器（环境）；`version_probe_failed` + `port_file_age_ms` 很大 ⇒ 陈旧端口（环境） |
| `eval_in_profile read` | `reason` | `page_ambiguous` ⇒ 未传 `url_part`（判据/调用方式）；`frozen_background_tab` ⇒ 后台标签（预期）；`cdp_timeout` ⇒ 实现或页面卡死 |
| `activate_tab` | `PAGE_AMBIGUOUS` + 候选数 | 候选 >1 ⇒ 给的 `url_part` 不够独特（调用方式），不是缺陷 |

**通用原则**：先看 `reason` 字段再下结论——这批工具的失败都带稳定 reason，**"failed" 不是结论**。

## 报告模板（直接贴给 agent-fleet 侧）

```text
分支/commit:
设备:            win-device / win-device-qjl     profile:
A 文件收发:      ✅/❌  sha 一致? 超限是否未落盘?
B 剪贴板:        ✅/❌  formats=?  readback=?  粘贴后字数/样式读数:
C devtools:      ✅/❌  脚本退出码=?  手动两条负向:
D UIA:           ✅/❌  dump_ui 耗时=?ms  merged 命中?  clicked_text_span=
E 回归:          ✅/❌  lease 12/12?  human_dom?
其它异常:        （贴原始返回，不要转述）
```
