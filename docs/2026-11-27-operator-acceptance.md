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

---

## A0. 一键跑（覆盖 A / B / D2 的脚本判据）

```bash
python3 scripts/smoke_ops.py --url http://<host>:8766/mcp --json
```

脚本会做：工具注册检查 / 二进制往返 sha（含 **76 列折行 base64** —— 标准编码器常见输出）/
超限不落盘 / 富文本剪贴板（格式列表只有 `HTML Format` + 回读通过 + **`attempts` 重试路径**）/
`wait_for` 预算是否被执行 / `run_actions` 顺序执行与**整批预校验**。**副作用**：会覆盖设备剪贴板，并在 `C:\Windows\Temp` 写一个临时文件；
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
| ☐ | 负向：另一个进程正占着剪贴板 | `attempts=1` 时返回 `ok=false, reason="clipboard_busy"`；`attempts=2` 时第二轮成功且 `attempts=2` |

> 证据：`formats` 列表原样贴出 + 粘贴后 `verify-draft` 的 JSON（含 `scriptVersion`）。
> 样式三项（borderLeft / gaps / markers）只用于 diff，**不进工具判据**。

---

## C. devtools（可选能力；启用后跑）

确认（默认已开）：`list_capabilities()` 里 devtools 应为 `enabled`；若被本机 `.fleet/config.toml` 关掉，去掉该覆盖并重启 server。

```bash
python3 scripts/smoke_devtools.py --url http://<host>:8766/mcp --profile "~/.fleet/<op-id>"
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
