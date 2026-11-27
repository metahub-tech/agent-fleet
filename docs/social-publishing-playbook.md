# 社媒发布操作手册（给 agent 的端到端配方）

> **读者**：在真机上跑「公众号 / 知乎 / 抖音」发布的 agent（含 `agent:device-operator-lead`）。
> **目的**：把「用哪些原语、按什么顺序、失败怎么降级」固定下来，减少临场试错。
> 判据纪律沿用 `AGENTS.md` §6：**结论要带读数，负向测试要断言原因**。
> 相关能力：`human_browser`（真账号浏览器）、`human_dom`（只读 DOM 定位，opt-in）、
> `devtools`（CDP 直连，win/mac 默认开启）、`clipboard_set_html` / `run_actions` / `wait_for`（win core）。

---

## 0. 一图流程

```
human_browser_open(profile=P, activate=True)
   └─ devtools.list_tabs(P) ── 目标页 background/frozen？→ activate_tab(P, url_part)
        └─ 填标题   : human_dom_fill(query="请在这里输入标题", text=..., profile=P)
        └─ 填正文   : clipboard_set_html(html) → press_key("ctrl+v") → wait_for(text=…)
        └─ 传图     : file_put(path, b64) → 触发上传 → 文件对话框（§4）
        └─ 校验     : eval_in_profile(P, verify_js, url_part=<目标页 url 子串>)（0 token、可断言）
        └─ 提交前   : hover_preview(x,y) 或不提交，交人确认
```

---

## 1. 前置（每台设备一次）

| 项 | 检查 | 不满足怎么办 |
|---|---|---|
| 真账号 profile | `human_browser_open(url, profile="~/.fleet/<op-id>")` 用的是**同一个** profile 串 | 固定一个 profile，跨 run 复用登录；漏传会落到日常 Chrome |
| human_dom 就绪 | `list_capabilities()` → `human_dom.status == "enabled"` | 建 `~/.fleet/human-dom-ready` 并重启 server；扩展由 `human_browser_open` 自动装 |
| devtools 就绪 | `list_capabilities()` → `devtools.status == "enabled"` | 默认开启；若被 `.fleet/config.toml` 关掉则去掉覆盖 |
| 会话租约 | `acquire(holder_name=…)` | 有别的 agent 占着会拿到 `device_leased`，别硬闯 |

---

## 2. 打开与定位（快、不猜）

```text
human_browser_open(url="https://mp.weixin.qq.com/…", profile=P, activate=True)
devtools.cdp_port(profile=P)        → ok=true / reason 分支（别缓存端口）
devtools.list_tabs(profile=P)       → 目标 tab 的 visibility
devtools.activate_tab(profile=P, url_part="…")   → 多命中会报 PAGE_AMBIGUOUS，别硬选
```

- `visibility == "unknown"` 不代表冻结，只代表探针超预算；**先 activate 再 eval**。
- 页面内容不在 UIA 树里 → `find_elements` 找不到网页元素是正常的，走 human_dom / devtools。

---

## 3. 填标题 / 填正文

**标题**（标准表单字段）：`human_dom_fill(query="请在这里输入标题", text=标题, profile=P)`
→ 返回 `{ok, verified, resolved_profile}`；`verified=false` 时**不要**继续，先 `human_dom_locate` 看实际元素。

**正文（富文本，必须保样式）**：

```text
clipboard_set_html(content=html)     → ok=true 且 readback 通过；formats 应只有 ["HTML Format"]
press_key("ctrl+v")                  → 或放进 run_actions
wait_for(kind="text", target="<正文首段的一小段文字>", timeout_ms=8000)
```

- **不要**用 `type_text` 粘长正文：纯文本会丢 `border-left`、段间距、内联样式。
- `clipboard_set_html` 是**全局剪贴板**：写完到粘贴之间别让别的 agent 写剪贴板；也别同时 `paste_text`。
- 回读失败（`ok=false`）时**不要粘**，重试一次再降级到 `human_dom_fill`。

**一次调用完成**（减少往返与状态漂移）：

```json
run_actions(steps=[
  {"tool": "clipboard_set_html", "args": {"content": "<html>"}},
  {"tool": "press_key", "args": {"keys": "ctrl+v"}, "sleep_ms": 300},
  {"tool": "wait_for", "args": {"kind": "text", "target": "正文首段片段", "timeout_ms": 8000}}
], stop_on_error=true)
```

> `run_actions` **整体校验**：任何一步拼错则一步都不跑；失败短路并把后续步标 `skipped`。
> 注意：批量里的 `wait_for` 超时会返回 `ok:false`，按 `stop_on_error`（默认 true）**短路整批**；
> 想让超时后继续跑后面的步，传 `stop_on_error=false`。

---

## 4. 传图（`upload_file_dialog` 暂无原语 —— 文档兜底）

**为什么不加专用工具**：文件选择对话框是系统窗口，结构随 Windows 版本/语言变；先用
`wait_for` + `run_actions` 组合即可，等真机上证明不稳再考虑做原语。

```json
run_actions(steps=[
  {"tool": "file_put", "args": {"path": "C:\\fleet\\cover.png", "content_b64": "<b64>"}},
  {"tool": "tap_element", "args": {"query": "上传", "window_title": "公众号"}},
  {"tool": "wait_for", "args": {"kind": "window", "target": "打开", "timeout_ms": 5000}},
  {"tool": "type_text", "args": {"text": "C:\\fleet\\cover.png"}, "sleep_ms": 150},
  {"tool": "press_key", "args": {"keys": "enter"}},
  {"tool": "wait_for", "args": {"kind": "window_gone", "target": "打开", "timeout_ms": 5000}},
  {"tool": "wait_for", "args": {"kind": "text", "target": "封面", "timeout_ms": 10000}}
])
```

要点与坑：

- 对话框标题随语言不同（中文「打开」/ 英文 "Open"）；先用 `wait_for(kind="window", target="打开")` 确认它真的起来了，再输入。
- **路径必须完整**（含盘符）；部分对话框不接受纯文件名。
- 中文路径建议用 `paste_text` 而不是 `type_text`（避免输入法/编码问题）。
- 输入后按 `enter`，然后**必须**用 `wait_for(kind="window_gone", target="打开")` 确认对话框真的关掉——
  没关就去点下一步，点击会打在对话框上（`*_gone` 变体在四个平台都支持）。
- 上传后**必须**用 `wait_for(kind="text", …)` 或 `eval_in_profile` 确认缩略图出现，别只看「操作成功」。

---

## 5. 提交前校验（0 token、可断言）

用 `devtools.eval_in_profile` 跑一段只读 JS，把读数带回来（对应 device-operator 的 `verify-draft`）。

> **真账号 profile 常有几十个标签页**（实测 33 个）：必须带 `url_part=`（取自 `list_tabs` 的 url 子串）
> 或 `target_id=`，否则返回 `page_ambiguous`——这是刻意不猜，不是故障。

```javascript
(() => ({
  chars: document.querySelector('[contenteditable]')?.innerText.trim().length ?? 0,
  h2Count: document.querySelectorAll('[contenteditable] h2').length,
  imgCount: document.querySelectorAll('[contenteditable] img').length,
  markers: {
    mojibake: /\uFFFD/.test(document.body.innerText),
  },
}))()
```

判据（与对方基线一致）：`chars` 与稿源一致、`h2Count` 匹配、`imgCount` 匹配、`markers.mojibake=false`。
**样式三项**（`h2[].borderLeft`、段间距、封面 `background-image`）只用于 diff，不进工具契约。

---

## 6. 失败降级表

| 现象 | 判定 | 下一步 |
|---|---|---|
| `reason: "uia_timeout"` | 无障碍提供者忙/挂 | 重试一次；仍失败则 `take_screenshot` + 坐标 |
| `find_elements` 查不到中文 | 「一字一节点」 | 已自动合并（看 `merged:true`）；仍无 → `vision_locate` |
| `clipboard_set_html` `readback_failed` | 剪贴板内容没保住 | **不要粘**；重试一次；再降级 `human_dom_fill` |
| `eval_in_profile` `frozen_background_tab` | 后台 tab 冻结 | `activate_tab` 后重试 |
| `eval_in_profile` `page_ambiguous` | 多 tab 且未指定目标页 | 从 `list_tabs` 取目标页 url 子串，带 `url_part=` 重试 |
| `wait_for` `timeout` | 条件没在预算内成立 | 截图看实际状态；别原地重试超过 2 次 |
| `device_leased` | 别的 session 持有设备 | 等 `auto_release_in_seconds` 或找持有者释放 |
| 平台风控/验证码 | — | **停手**，交人（`team block --kind human_decision`） |

---

## 7. 节奏与风控（真账号操作纪律）

- 同一账号**不要**高频批量发布；动作之间留真实间隔（秒级，不是毫秒级）。
- 一旦出现滑块/验证码/异常登录提示：**立即停止自动化**并上报，不要尝试绕过。
- 只在自有设备、自有或已授权账号上使用；发布前如需人工确认，用 `hover_preview` 把落点给人看。
