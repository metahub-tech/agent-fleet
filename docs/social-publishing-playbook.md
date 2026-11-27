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


## 0.5 平台 × 原语适配矩阵（这份 SOP 到底覆盖了什么）

> 本文的**具体步骤**是按「**公众号网页**版（`mp.weixin.qq.com`）」写的——那是拿到最多真机验收的路径。
> 知乎也有端到端记录（见 §0.6）；真正没有记录的是**抖音**，所以抖音只给"该用哪套原语"，不写死步骤。

| 平台 | 形态 | 该用哪一端 | 该用哪套原语 | 真机验证 |
|---|---|---|---|---|
| 微信公众号 | **网页**（`mp.weixin.qq.com`） | `win-device` / `mac-device` + 浏览器 | `human_browser_open` → `human_dom_locate/fill/tap` + `clipboard_set_html` 粘正文 + `devtools.eval_in_profile(url_part/target_id)` 校验 | ✅ A 组 12/12、devtools 7/7、B2 四项全绿、§5 JS 真机跑过 |
| 知乎 | 网页（创作中心，Draft.js） | 同上 | 同公众号；保存提示 **20–40s** 才出现 ⇒ 等 45s 再判 | ✅ 端到端 11 步 9 成功、7 项机器复验全绿、正文 1240/1240（对方 lab，见 §0.6） |
| 头条 | 网页（`profile_v4`） | 同上 | 同公众号，但**必须验草稿是否落库**（见 §0.6） | ⚠️ 有读数：**草稿不落库** |
| 抖音（创作服务平台） | 网页 | 同上 | 同公众号 | ❌ **无记录** |
| 抖音（App） | 移动端 | `android-device` / `ios-device` | `dump_ui` / `find_elements` / `tap_element` / `wait_for`；输入用 `type_text`（Android 仅 ASCII） | ❌ 无（移动端只有桩级测试） |

> ⚠️ **公众号是网页，不是 PC 客户端**：微信 PC 客户端是聊天端，只在 B3（UIA 卡死回归）里出现过。
> 这决定了原语选择——网页内容**不在 UIA 树里**，`find_elements`/`tap_element` 对网页元素一律无效，
> 必须走 `human_dom` / `devtools` / `vision`（§3、§4 的修正就是这个原因）。

## 0.6 平台差异（带读数，来源见每条）

> 这是三个平台在**"草稿会不会被保存"**和**"富文本会不会被改写"**上的实测差异——
> 直接决定"填完能不能走"。读数来自对方 labs，我未直接读取其文件，按回执转录。

| 平台 | 草稿持久化 | 富文本改写 | 等待窗口 |
|---|---|---|---|
| 公众号 | **落库**：底部出现「已保存」 | 保留内联样式（`border-left` 实测 4px） | 保存很快 |
| 知乎 | **落库**：保存提示 **20–40s** 才出现 | 未记录改写 | **等 45s** 再判定，15s 会误判超时 |
| 头条 | **不落库**：页脚一直「草稿保存中...」，草稿箱「共 0 条内容」，**刷新即丢**（标题+正文全无） | **h2 → h1**（`class=pgc-h-forward-slash`）、内联样式被清洗，改由平台主题接管 | 无（等多久都不会落库） |

**头条这条最要紧**：按公众号配方"填完就走"会**静默丢稿**。

**不要给头条写"等 N 秒就算失败"的时间阈值**——形状不对：

| 平台 | 保存信号 | 时间阈值的后果 |
|---|---|---|
| 公众号 | 底部「已保存」**秒级**出现 | — |
| 知乎 | 保存提示 **20–40s** 才出现（实测）⇒ 等待窗口 45s | 小于 40s 会假阴性 |
| 头条 | 页脚**一直**「草稿保存中...」，等到 8s / 80s 都一样 | 等更久永远不会把失败等成成功 ⇒ 只会制造假阴/假阳 |

⇒ 正确判据是**终态判据**，三步缺一不可：

```
1) 等 45s（推导上界，见下）
2) eval 读「草稿箱条数」 → 必须 > 0
3) 若为 0：刷新该测试标签 → 标题与正文仍在？
   仍然为空 ⇒ 判「该平台不落库」，不要继续等
```

- **45s 是推导值，不是实测值**：取知乎实测保存上界（20–40s）的 1.1 倍，同时覆盖公众号的秒级保存；
  对头条它只是"给足机会"，**不是失败阈值**。
- **页脚文案不能当判据**（"草稿保存中..."在头条永不变化；它甚至可能是永不更新的 UI）。
- 头条实测（对方 lab）：粘完 `chars=125` 与平台底部「共 125 字」一致；等 8s 页脚未变、
  草稿箱「共 0 条内容」；刷新测试标签后标题与正文**全部丢失**。

**公众号正文根**：页面上有 3 个 `contenteditable`（`[0]` 标题 20 字、`[2]` 正文），
正文 = 最后一个 `.ProseMirror`；且需判 `editorLayout == "clean"`（见 §5、§5.1）。

**为什么网页端要用 `human_browser` 而不是 `agent_browser`**：真账号发布要求零自动化痕迹
（`navigator.webdriver` 等标志），`human_browser` 起的是宿主真实 Chrome；`agent_browser`
是 Playwright 托管浏览器。两者共享 profile 租约：**同一个 profile 串 = 同一份登录**。

**跨平台的共同纪律**（三个平台都适用）：

1. 提交前用 `eval_in_profile` 或 `find_elements` **校验草稿状态**，不要凭"操作成功"就点发布；
2. 任何"发布 / 群发 / 定时"都是不可逆动作 —— 交人确认（`team block --kind human_decision`）；
3. 页面结构变了不要硬重试：先 `take_screenshot` 记录现场，再回报。


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
devtools.activate_tab(profile=P, url_part="…")   → 多命中报 PAGE_AMBIGUOUS（注意：activate_tab 用大写，eval_in_profile 用小写 page_ambiguous），别硬选
```

- `visibility == "unknown"` 不代表冻结，只代表探针超预算。
- **只读断言先 `activate=False`**（`eval_in_profile(js=…, activate=False, url_part=…)`）：
  真机实测浏览器忙时 `activate_tab` 会双次超时 6703ms，而同 profile 的
  `eval(activate=False)` **47–108ms** 就返回了。**只有"要往页面里输入/点击"时才需要 activate。**
- 激活失败按「可以继续但没焦点」降级（见 §6），不要重试到超时再判死整条链路。
- 页面内容不在 UIA 树里 → `find_elements` / `tap_element` 找不到**网页元素**是正常的，
  必须走 human_dom / devtools / vision；UIA 只在**系统对话框**（如文件选择框）那一段有用。

---

## 3. 填标题 / 填正文

**标题**（标准表单字段）：`human_dom_fill(query="请在这里输入标题", text=标题, profile=P)`
→ 返回 `{ok, verified, resolved_profile}`；`verified=false` 时**不要**继续，先 `human_dom_locate` 看实际元素。

**正文（富文本，必须保样式）**：

```text
# 0) 先确认焦点在**正文**（填完标题后焦点还在标题框，直接 ctrl+v 会把 h2 粘进标题！）
devtools.eval_in_profile(profile=P, url_part=…, activate=False,
                         js="document.activeElement?.className || ''")   → 应为正文编辑器
#    不是的话：human_dom_tap(正文区域) 或 tap 坐标，再复查一次

clipboard_set_html(content=html)     → ok=true 且 readback 通过；formats 应只有 ["HTML Format"]
press_key("ctrl+v")                  → 或放进 run_actions
# 粘完用 eval 读 innerText 验证（**不要**用 wait_for(kind="text")，见下）
devtools.eval_in_profile(profile=P, url_part=…, js="…正文根节点.innerText.length…")
```

> ⚠️ **网页编辑器上 `wait_for(kind="text")` 永远不会命中**：它走 UIA，而 Chrome 的网页内容
> 不在 UIA 树里（工具 docstring 已写明，真机实测 `find_elements` 对 Chrome 任何文本都返回
> `count=0`）。粘完正文那句 `wait_for` 必然等到 8s 超时；而 `run_actions` 默认
> `stop_on_error=true`，会把**已经粘成功**的批次判成失败。
> ⇒ 正文确认一律用 `eval_in_profile` 读 `innerText`；若仍想留在批量里，把该步的
> `stop_on_error` 设为 `false`。

- **不要**用 `type_text` 粘长正文：纯文本会丢 `border-left`、段间距、内联样式。
- `clipboard_set_html` 是**全局剪贴板**：写完到粘贴之间别让别的 agent 写剪贴板；也别同时 `paste_text`。
- 回读失败（`ok=false`）时**不要粘**，重试一次再降级到 `human_dom_fill`。

**一次调用完成**（减少往返与状态漂移）：

```json
run_actions(steps=[
  {"tool": "clipboard_set_html", "args": {"content": "<html>"}},
  {"tool": "press_key", "args": {"keys": "ctrl+v"}, "sleep_ms": 300}
], stop_on_error=true)
# 粘完单独调 devtools.eval_in_profile 读 innerText 校验（UIA 在网页上等不到文本）
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
  {"tool": "human_dom_tap", "args": {"query": "上传", "profile": "<同一个 P>"}},
  {"tool": "wait_for", "args": {"kind": "window", "target": "打开", "timeout_ms": 5000}},
  {"tool": "type_text", "args": {"text": "C:\\fleet\\cover.png"}, "sleep_ms": 150},
  {"tool": "press_key", "args": {"keys": "enter"}},
  {"tool": "wait_for", "args": {"kind": "window_gone", "target": "打开", "timeout_ms": 5000}},
  {"tool": "wait_for", "args": {"kind": "window_gone", "target": "打开", "timeout_ms": 5000}}
# 缩略图另用 devtools.eval_in_profile 读（见下）
])
```

要点与坑：

- **「上传」按钮是网页元素，`tap_element`/`find_elements` 找不到它**（UIA 只看得见 Chrome 窗口，
  看不见网页 DOM）。用 `human_dom_tap(query=…)`、`vision_tap` 或坐标；UIA 只在**系统文件对话框**
  那一段才生效（所以下面 `wait_for(kind="window", target="打开")` 是对的）。
- 对话框标题随语言不同（中文「打开」/ 英文 "Open"）；先用 `wait_for(kind="window", target="打开")` 确认它真的起来了，再输入。
- **路径必须完整**（含盘符）；部分对话框不接受纯文件名。
- 中文路径建议用 `paste_text` 而不是 `type_text`（避免输入法/编码问题）。
- 输入后按 `enter`，然后**必须**用 `wait_for(kind="window_gone", target="打开")` 确认对话框真的关掉——
  没关就去点下一步，点击会打在对话框上（`*_gone` 变体在四个平台都支持）。
- 上传后**必须**用 `eval_in_profile`（读 `img` 数量或 `background-image`）确认缩略图出现——
  网页内容上 `wait_for(kind="text")` 等不到（同 §3）。

---

## 5. 提交前校验（0 token、可断言）

用 `devtools.eval_in_profile` 跑一段只读 JS，把读数带回来（对应 device-operator 的 `verify-draft`）。

> **真账号 profile 常有几十个标签页**（实测 33 个）：必须带 `url_part=`（取自 `list_tabs` 的 url 子串）
> 或 `target_id=`，否则返回 `page_ambiguous`——这是刻意不猜，不是故障。

```javascript
(() => {
  // ⚠️ 公众号编辑页有 **3 个 contenteditable**（实测）：
  //   [0] .ProseMirror len=20   ← 装的是**标题**（与 #title 的值一致）
  //   [1] original_primary_tips_inp len=0
  //   [2] .ProseMirror len=1343 ← 这才是**正文**
  // `querySelector('[contenteditable]')` 返回第一个 ⇒ 会把标题长度当正文字数。
  // 取**最后一个** `.ProseMirror`（或换成你自己确认过的正文根选择器）。
  const roots = [...document.querySelectorAll('.ProseMirror')];
  const rootLens = roots.map((r) => (r.innerText || '').length);
  // 取"最后一个"只在页面上只有编辑器本身（标题 + 正文 = 2 个根）时成立；
  // 弹层/裁剪对话框里也可能挂 ProseMirror，排在正文之后就会选错。
  const editorLayout = roots.length === 2 ? 'clean' : 'unexpected';
  const body = roots.length ? roots[roots.length - 1] : null;
  const text = (body?.innerText || '');
  const h2 = body ? body.querySelector('h2') : null;
  return ({
  // chars 含块间换行/空白（真机实测：raw=1346 / trim=1343 / nonblank=1240）
  // ⇒ **判据用 charsNonBlank**，chars 只用于显示与前后差值。
  editorRoots: roots.length,
  editorLayout,
  rootLens,
  chars: text.trim().length,
  charsNonBlank: text.replace(/\s/g, '').length,
  h2Count: body ? body.querySelectorAll('h2').length : 0,
  imgCount: body ? body.querySelectorAll('img').length : 0,
  // 用 computed 而不是 .style：编辑器若把 border 挪进 class，.style 会是空串而 computed 仍有值
  h2BorderLeft: h2 ? getComputedStyle(h2).borderLeftWidth : '',
  gaps: (() => {
    const ps = body ? [...body.querySelectorAll('p')] : [];
    return ps.slice(1).map((p, i) =>
      Math.round(p.getBoundingClientRect().top - ps[i].getBoundingClientRect().bottom));
  })(),
  markers: {
    mojibake: /\uFFFD/.test(document.body.innerText),
  },
  });
})()
```

判据（与对方基线一致）：

| 字段 | 判据 | 注意 |
|---|---|---|
| **`charsNonBlank`** | 与稿源的**非空白字符数**一致 | 夹具是 22；**不要**用 `chars`（含块间换行，夹具会给 27） |
| `chars` | 只用于显示与"粘前/粘后差值" | 真机实测同一稿：raw 1346 / trim 1343 / nonblank 1240 |
| `h2Count` / `imgCount` | 与稿源匹配 | ✅ |
| `h2BorderLeft` | 期望 `4px` | 用 `getComputedStyle` 取（内联或 class 都成立） |
| `markers.mojibake` | `false` | ✅ |
| `gaps` | **仅 B2 夹具**可用 20–34px | 真实稿子里见过 78（标题后/大段间）与 12（列表项间）——对任意草稿应"与稿源结构逐段比对"或只看"`>0` 且稳定" |

> **`editorLayout` 必须为 `clean`（`editorRoots === 2`）才算可信**：若页面挂了额外 ProseMirror
> （插入视频/模板弹层、图片裁剪对话框里的富文本），它可能排在正文之后 ⇒ `last` 会选错；
> 遇到 `unexpected` 时用下面 §5.1 显式指定正文根。

> 这套 JS 已在真机 1343 字草稿上原样跑过：`chars=1343, h2Count=7, imgCount=2, h2BorderLeft=4px, mojibake=false`
> —— **取最后一个 `.ProseMirror` 这条修复真机成立**（标题是 20 字，没被误读）。

> **别拿页面底部的「正文字数」计数器当判据**：它是编辑器自己的统计口径，与 `innerText` 长度
> 不一致（真机见过 15 vs 20）。用**粘前/粘后的 `charsNonBlank` 差值**。
**样式三项**（`h2[].borderLeft`、段间距、封面 `background-image`）只用于 diff，不进工具契约。

### §5.1 显式正文根（`editorLayout == "unexpected"` 时用）

```javascript
// 用你自己在真实页面上确认过的正文根替换下面的启发式；
// 示例：正文是"标题之外那个文本明显更长的 ProseMirror"
(() => {
  const roots = [...document.querySelectorAll('.ProseMirror')];
  const body = roots.filter((r) => (r.innerText || '').trim().length > 200).pop() || null;
  return { ok: !!body, chars: (body?.innerText || '').trim().length };
})()
```

---

## 6. 失败降级表

| 现象 | 判定 | 下一步 |
|---|---|---|
| `reason: "uia_timeout"` | 无障碍提供者忙/挂 | 重试一次；仍失败则 `take_screenshot` + 坐标 |
| `find_elements` 查不到中文 | 「一字一节点」 | 已自动合并（看 `merged:true`）；仍无 → `vision_locate` |
| `clipboard_set_html` `readback_failed` | 剪贴板内容没保住 | **不要粘**；重试一次；再降级 `human_dom_fill` |
| 激活超时（`cdp_timeout`，约 3s 后重试一次） | 浏览器忙（真机实测：忙时 3.1–3.3s 超时，闲时 296ms） | **按"可以继续但没焦点"处理**：只读 `eval_in_profile(activate=False, url_part=…)` 仍可用；粘贴/输入类动作必须先用 `wait_for(kind="foreground")` 或 `list_tabs` 重新确认前台，再继续。**不要**因为一次激活失败就判定整条链路失败（最坏 3+0.2+3≈6.2s） |
| `eval_in_profile` `frozen_background_tab` | 后台 tab 冻结 | `activate_tab` 后重试 |
| `eval_in_profile` `page_ambiguous` | 多 tab 且未指定目标页 | 从 `list_tabs` 取目标页 url 子串，带 `url_part=` 重试 |
| `wait_for` `probe_failed` | **一次都没探成**（探测本身报错，条件从未被评估） | 调大探测预算（`FLEET_WAIT_PROBE_BUDGET`）或看 `last_error`；**别**当成"条件不成立"去重试 |
| `wait_for` `timeout` | 条件没在预算内成立 | 截图看实际状态；别原地重试超过 2 次。**注意**：`text` 探测若单次超预算（默认 4s，`FLEET_WAIT_PROBE_BUDGET`）也会表现为 timeout —— 重窗口可先把预算调大再等，或改用 `kind="window"` |
| `device_leased` | 别的 session 持有设备 | 等 `auto_release_in_seconds` 或找持有者释放 |
| 平台风控/验证码 | — | **停手**，交人（`team block --kind human_decision`） |

---

## 7. 节奏与风控（真账号操作纪律）

- 同一账号**不要**高频批量发布；动作之间留真实间隔（秒级，不是毫秒级）。
- 一旦出现滑块/验证码/异常登录提示：**立即停止自动化**并上报，不要尝试绕过。
- 只在自有设备、自有或已授权账号上使用；发布前如需人工确认，用 `hover_preview` 把落点给人看。
