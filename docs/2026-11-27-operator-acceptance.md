# 设备侧验收清单（社媒操作优化 · 2026-11-27）

> **读者**：在 Windows 设备上跑真机的 operator（`agent:device-operator-lead` 或人为代跑）。
> **目的**：把这一批改动从"代码写完"推进到"真机可验收"。每项都写了**判据**，判据不通过就贴证据，
> 不要用"看起来正常"代替读数（判据纪律见 `AGENTS.md` §6）。
> **只读优先**：A/B/E 组不改变现场；C/D 组会动剪贴板与临时文件，按自己的节奏跑。

---

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
# --profile 不要加引号（脚本会剥，但加了容易把引号带进路径）；脚本会自动挑 list_tabs 里的第一个 http 页去 eval
```

| 勾 | 判据（脚本已覆盖） |
|---|---|
| ☐ | 退出码 0；能力 `enabled`、`cdp_port` 存活且带 `probe_ms`、`list_tabs` **1s 内**返回、`eval` 可读、超限报 `result_too_large` 且**不带** `value`、`activate_tab` 后目标 `visible` |
| ☐ | （手动）开两个标签，把目标页切后台 → `eval_in_profile(activate=False)` 必须 `ok=false, activated=false, reason="frozen_background_tab"` |
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
| ☐ | 租约 | `python3 scripts/smoke_lease.py --url http://<host>:8766/mcp` 12/12 通过 |
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
| P2 | B2（剪贴板粘贴保真） | 需要在真账号编辑器里操作，最费时；可延后到下次 |


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
| 异常① | 一次 `list_windows` **11984ms** + 裸 `OSError [Errno 22] Invalid argument` | ❌ → **`73dc997` 兜住非超时异常**。⚠️ 我先前推断「必然是旧码 8766」，被对方用 `start_process` 记录的命令行**证伪**：那次打的是 8767（新码）。所以「8s 预算却没在 8s 收住」仍是**未解**问题——需要服务端日志里那行 `[uia] list_windows ...` 才能定死 |
| 异常② | `find_elements(window_title="StarBeam")` 两窗口时抛裸异常 `There are 2 elements that match the criteria` | ❌ 既有 bug → **`73dc997` 起返回 `reason:"ambiguous_window"` + candidates** |
| 交叉证据 | 裸客户端打旧码 8766 的 `list_windows` → `Output validation error: 'result' is a required property` | 佐证旧码该工具在严格客户端下本来就是坏的 |

**现场收拾**：对方已 `git worktree remove`、kill 8767、release 租约；证据留在
`C:\Users\qjl\af-p0p1-evidence\`，实验记录在 `device-operator/labs/2026-11-28-win-p0p1-acceptance/README.md`。

**他的自我批评（值得记）**：11984ms 那次没记下前台窗口与连的是哪台 server，因此无法定性——
下次同类现象要同时记「连的 host:port + 前台窗口 + 是否锁屏」。

**结论**：没有实现 bug 的硬证据；两条是判据/契约问题（均已修），一条是既有 bug（已结构化），
一条是环境不具备。

## B 组最小执行脚本（复制即可跑，约 6 分钟）

> 这四条脚本覆盖不到（需要"制造状态"或输入类操作），但工具调用可以照抄。
> 下面 `P` = 你正在用的 profile 串（与 `human_browser_open` 用的**同一个**值）。

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
2) human_browser_open(url="https://example.com", profile=P, activate=True)   # 现在有两个标签
3) list_tabs(profile=P)                    → 记下 about:blank 的 url 片段（记为 U1）
4) devtools.eval_in_profile(profile=P, js="1", url_part=U1, activate=False)
   期望：{ok:false, activated:false, reason:"frozen_background_tab"}
5) devtools.eval_in_profile(profile=P, js="1", url_part=U1)          # 默认 activate=True
   期望：{ok:true, activated:true, value:1}
6) 收尾：手动关掉 about:blank 标签
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

**尚未验证**：B 组（后台标签 `frozen_background_tab`、剪贴板粘贴保真、UIA 卡死回归、
中文元素 `merged`/`clicked_text_span`）——它们需要输入类操作，必须等设备空闲。


---

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
