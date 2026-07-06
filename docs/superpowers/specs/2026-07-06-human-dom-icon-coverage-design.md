# 设计：human_dom 扩覆盖（R4）——补全可及名计算，把带可及名的图标入口从「vision 兜底」拉回 DOM 精确定位

> 状态：设计稿（待 architect 审 + 用户 spec 评审后转 writing-plans）· 2026-07-06
> 需求方：AgentHub（`docs/superpowers/specs/2026-07-06-device-op-precision-requirements-for-agent-fleet.md`，R4）
> 落地方：agent-fleet（device 工具 owner）
> 关联：`docs/internal/design/2026-06-24-human-dom-perception-capability.md`（human_dom 现状）、`docs/superpowers/specs/2026-07-06-vision-coordinate-calibration-design.md`（R1，已实现）、commit 59fe476（data-placeholder / 回读 修法先例）
> 原则：从需求来、回需求中去；改动**回归安全优先**（延续 59fe476 的「只加 fallback、不动既有链」纪律）。
> 范围：本 spec 只做 R4。R4 的「DOM 优先」行为编排规范归 agenthub charter（不在本仓）。

---

## 一、需求与现状（含一个必须先对齐的 premise）

### 1.1 需求原话（R4）

> human_dom 是浏览器里最精确的路径（拿到即精确元素），但覆盖缺口逼 vision 兜底。R4 误点的公众号编辑器入口（文章/视频图标、编辑器入口）应能 DOM 定位。延续 data-placeholder / 回读 那条修法，扩 content.js 可见文本抽取 / 候选检测，覆盖误点热点入口，让它们 `human_dom_locate` 命中。

### 1.2 现状取证（先读源码）

human_dom = per-profile Chrome 扩展的只读 content script（`platforms/common/capabilities/human_dom/extension/content.js`），扫 DOM → 返回视口相对 rect → `_geom.py` 映射到屏幕 tap 空间（与 core tap 同空间，R1 已验坐标对齐）。四个工具 `human_dom_locate/tap/fill/status`（`_human_dom.py`）。

**现在怎么抽可定位元素**（`content.js:10-37`）：
- **可及名来源** `visibleText(el)`（`:10-15`）：逐项 trim 取第一个非空——`innerText, value, aria-label, placeholder, data-placeholder, aria-placeholder, title`。**只读元素自身属性**。
- **候选池** `matchAll`（`:21-22`）：`a,button,input,textarea,[role],[onclick],[contenteditable]`。
- **无文本即丢**：`if(!txt && !css) continue`（`:25`）。
- **css 逃生口**：传显式 `css` 选择器时按选择器取、且不因无文本丢弃（`:21,25,26`）。
- **未命中诊断**：返回 `dom_candidates = visibleSample(8)`（`:38-39,50`），从 `a,button,[role],input,textarea` 采样 visibleText。

### 1.3 三个确切缺口（为什么图标入口误点）

公众号工具栏图标入口（文章/视频/图片/音频、编辑器入口）多为 `div[role=button]` 形态（`SKILL.md:36-42`、`CHANGELOG.md:35`），而 `[role]` **已在池里**。所以误点不是「不在池」，而是**取不到可及名被丢**：

1. **不算「后代 / 引用的可及名」（最可能的真缺口）**：`<div role="button"><img alt="视频"></div>`——div 自身 `innerText` 空、无 `aria-label` → `visibleText` 返回 `""` → 被 `:25` 丢弃。标签其实在**后代 img 的 alt**里。同理 `aria-labelledby`（指向别处元素文本）、嵌套 SVG `<title>`、后代 `[aria-label]` 都不解析。
2. **裸图标容器不进池**：无 `role`、无内联 `onclick` 属性的 `<div>/<span>/<i>` 图标（事件用 `addEventListener` 绑，DOM 上看不到 `onclick`）进不了池。
3. **纯视觉图标（零可及名）**：纯 CSS 背景图 icon，DOM 里没有任何可读文本/标签。

### 1.4 premise + R4 为何对症 #100（用户 2026-07-06 确认；R1 同款取证反转风险，写进 spec 供评审）

> **R4（文本/DOM 抽取）只能救缺口①②——「有可及名/文字源但没被算出来」的入口；对缺口③「纯视觉零可及名」无能为力，那是 R3(元素检测+SoM)/R5(反应式) 的 territory。**

**R4 为何直接治 #100 的观测失败（机理）**：#100 那次误点的本质是**相邻入口靠得近 + agent 用 vision 猜坐标/近点误中邻居**（把「视频」点成了「文章」）。而公众号后台「新建内容」的入口（文章/图片/视频/音频）通常**带可见文字标签**（「文章」「视频」…）——human_dom 按各自文字标签**精确定位到该元素中心**，正好消歧相邻入口、不靠猜坐标。这正是 R4 要补的：把「按标签精确取元素」这条路打通，替掉「vision 近点猜」。

**用户已确认的工作假设**：后台入口带可见文字标签、非纯图标 → 缺口①②（有文字/可及名源没被算出来）大概率占大头，R4 对症。**但仓里没有真实后台入口图标 DOM fixture**。已知的只是**编辑器标题/正文那个 surface**=顶层 `div.ProseMirror`、标题 `data-placeholder="请在这里输入标题"`、**非 iframe**（59fe476 证）——**注意这是编辑器 surface 的证据，不能外推到「后台『新建内容』入口图标」这个不同 surface**：入口图标的 DOM 结构、可及名形态、以及**是否在 iframe 里**全部未取证。故仍需真机取证证实（§5.2）。

**取证反转闸（R1 同款，四类反转条件）**：`accessibleName` 简化算法 + 有界扩池 + 诊断这套**普适正确、不依赖 premise**（无论①②③都不做错事、不引回归）；但取证若发现下列任一，**回报用户、调整方向**（如 R1 否掉除法层那样，取证说话）：
- **③纯视觉零可及名占大头** → 把 R3(元素检测+SoM) 提前，不硬做 R4；
- **入口图标在 iframe 里**（manifest 无 `all_frames`、content script 只注顶层 frame）→ R4 对该 surface **整体看不到、完全失效**（比③更彻底）；这需 `all_frames:true` + 每子 frame 各建桥注册的**独立工作**（另起 spec），不塞进本 R4。

### 1.5 需求一句话（重述后）

> **给 content.js 一个更完整的「可及名计算」`accessibleName(el)`（覆盖后代 img-alt / aria-labelledby / SVG title 等被漏算的可及名来源），并有界扩池纳入带可及名的图标容器，把「有可及名但当前取不到」的图标入口从 vision 兜底拉回 human_dom 精确定位；纯视觉零可及名的图标诚实划归 R3/R5。** 全程只读、坐标/桥/契约不动、既有 `visibleText` 行为零回归。

### 1.6 成功判据（验收对着这些）

- 一个带可及名的图标入口（如 `<div role=button><img alt=视频>` 或 `<a aria-label=插入图片>`）能被 `human_dom_locate("视频")` 命中、返回可点中的屏幕坐标。
- 既有行为零回归：标题 `data-placeholder`、正文 `contenteditable` 填充、真编辑体优先排序（59fe476）全部保持。
- 纯视觉零可及名图标：未命中时诊断 `dom_candidates` 能反映「附近有哪些带可及名候选」，让上层可判断并降级 vision/R3（诚实边界）。
- 主文字路径（RapidOCR 那条 vision）0-token 不变（R4 不碰 vision）。

---

## 二、目标 / 非目标

### 目标
- G1（追 §1.3-①）：content.js 实现 `accessibleName(el)`——在既有 `visibleText` 链**返回空时**追加算：aria-labelledby 解析、自身 alt、后代 `img[alt]`/`[aria-label]`/SVG `<title>`/`[title]`。**既有链顺序与结果不变**（回归安全）。
- G2（追 §1.3-②）：**有界扩池**——纳入带可及名源的容器（`[aria-label],[title],[aria-labelledby],img[alt]`），不做全 `div/span` 盲扫。
- G3（追 §1.6 诊断）：`visibleSample` 用 `accessibleName` + 覆盖新选择器，未命中时吐带可及名的候选，助取证 + 助上层降级判断。
- G4：真机取证实际 DOM 定稿规则 + node-vm 单测（`accessibleName` 各源 + `matchAll` 级）。

### 非目标（YAGNI）
- NG1：**不碰 iframe**（`manifest.json:7` 无 `all_frames`，content script 只注顶层 frame；跨源 iframe 需每子 frame 各建桥、是更重的独立工作，另起 spec）。**前提「入口图标在顶层 frame」未取证**——59fe476 只证了编辑器标题 surface 非 iframe，**不能外推**到入口图标这个不同 surface；故此点列为 §1.4/§5.2 的取证反转闸，取证若发现入口在 iframe，R4 对该 surface 失效、需另做 all_frames 工作。
- NG2：**不改坐标映射 / 桥协议 / 四工具契约**（`_geom.py`/`_bridge.py`/`_locate.py` 不动；`accessibleName` 只影响候选的 `text` 字段来源，结构不变）。
- NG3：**不动既有 `visibleText` 链的顺序与结果**（只在其返回空时追加 fallback）——保 data-placeholder/标题/正文填充零回归。
- NG4：**不做纯视觉零可及名图标**（§1.4 缺口③，划归 R3/R5）。
- NG5：**不改 vision**（主文字 0-token 路径不动）。
- NG6：**不做全量 ARIA 可及名算法**（完整算法含 CSS content、隐藏节点规则等，过重）；只取覆盖图标场景的实用子集。

---

## 三、方案对比（3 选 1）

| 方案 | 做法 | 判定 |
|---|---|---|
| **A. 重排/替换 visibleText 链，按完整 ARIA 优先级（labelledby > label > content > title）** | 把 aria-labelledby/label 提到 innerText 前 | ❌ 否决。会**改既有匹配结果**（如某元素 innerText 与 aria-label 不同时命中变化），**回归风险高**——59fe476 血的教训是这条链极易埋 bug。 |
| **B. 既有链不动，返回空时追加 fallback 可及名源 + 有界扩池**（本 spec 选） | `accessibleName` = 既有 `visibleText` 链 →(空则) labelledby/自身 alt/后代标签；池加 `[aria-label],[title],[aria-labelledby],img[alt]` | ✅ **选它**。**零回归**（既有非空结果完全不变，只给「原本返回空被丢」的图标补命中）；有界扩池不污染文本查询；延续 59fe476「只加不改」纪律。 |
| **C. 全 div/span 扫 + 启发式判可点** | 池纳入所有 div/span，按 class/背景图/cursor 猜可点 | ❌ 否决。池爆炸、误命中面大、启发式不确定；与「只读精确定位」定位相悖。纯视觉图标本就该 R3(SoM)。 |

选 B 一句话：R4 的病是「可及名算得不全」，治法是**补全算法 + 只加不改**，不是重排既有链、更不是盲扫全 DOM。

---

## 四、设计（方案 B）

### 4.1 组件一：`accessibleName(el)` —— 既有链不动，追加 fallback（G1）

在 content.js 加 `accessibleName(el)`，`matchAll` 改调它（替换现 `:25` 的 `visibleText(el)`）：

```
accessibleName(el):
  1. name = visibleText(el)              # 既有链, 完全不动: innerText→value→aria-label→
                                         #   placeholder→data-placeholder→aria-placeholder→title
  2. if name: return name                # 既有非空结果原样返回 —— 零回归的关键
  3. # 以下仅当既有链返回空(典型: 纯图标容器)才走, 只增不改:
     a. aria-labelledby: 拆 id 列表 → document.getElementById(id) → 【null-guard: 跳过不存在的 id】
        → 取其 visibleText, 拼接非空
     b. 自身 alt: el.getAttribute("alt")            # el 本身是 <img> 的情形
     c. 后代可及名(取第一个非空, 【限浅层 :scope 直接/近层后代, 防误取深层无关元素的 alt,
        如卡片里嵌套配图的 alt】):
        el.querySelector(':scope > img[alt], :scope > * > img[alt]')?.alt
        el.querySelector(':scope [aria-label]')?.getAttribute("aria-label")  # 浅层
        el.querySelector(':scope svg title, :scope > title')?.textContent
     d. return 拼到的第一个非空, 否则 ""
```
> 后代 querySelector 的确切层级限制在取证（§5.2）拿到真实入口 DOM 后定稿——图标容器通常很浅（首个后代即图标），但要防 `role=button` 包整张卡片时误取深层配图 alt。

- **仍只读**：只读属性 / textContent，绝不 `.click()`/改 DOM（铁律 `content.js:1`）。
- **后代扫有界**：每个池元素最多几次 `querySelector`（取第一个匹配），池本身有界（§4.2），无性能问题。
- **aria-labelledby 优先于后代**（它是显式指定的名，比 name-from-content 更权威）；但整体**都在既有链之后**，不与既有结果竞争。

### 4.2 组件二：有界扩池（G2）

`matchAll` 的默认池（`content.js:22`）从：
```
'a,button,input,textarea,[role],[onclick],[contenteditable]'
```
扩为（**只加带可及名源的选择器**）：
```
'a,button,input,textarea,[role],[onclick],[contenteditable],[aria-label],[aria-labelledby],img[alt]'
```
- 纳入 `<div aria-label="视频">`、`<img alt="视频">`、`<span aria-labelledby=..>` 这类当前漏网的带名图标；**不纳入**无任何可及名源的裸 `div/span`（避免池爆炸 + 文本查询污染）。
- **`[title]` 暂不纳入**（架构审 N：`[title]` 极常见——很多元素带 tooltip title——是四个候选选择器里噪声面最大的一个）；先上 `[aria-label]/[aria-labelledby]/img[alt]`，`[title]` 视取证（§5.2）真实噪声再定是否加。（注：`visibleText:12` 本就读元素**自身** title，故自身带 title 的元素若也在既有池内不受影响；此处只是不为「仅有 title」的额外元素扩池。）
- **去重仅按 DOM 包含关系**（防 `<div role=button><img alt=视频>` 的 div 与 img 双命中）：`a.el.contains(b.el)`（a 是 b 的祖先）**且可及名相同** → 保留外层可点容器、丢内层。**绝不按中心距去重**——#100 病根正是相邻不同入口（视频/文章）靠得近，中心距会误并、恰好重造 R4 要消除的歧义。实现嫌复杂可**直接不去重**（div+img 双候选无实害：同文本、近同心，`tap` 取 `candidates[0]` 指同点）。
- 无文本仍丢（`:25` 逻辑不变）：扩池后元素若 `accessibleName` 仍空（纯视觉），照样被丢——扩池只对「有可及名」生效。

### 4.3 组件三：诊断增强（G3）

`visibleSample`（`content.js:38-39`）改用 `accessibleName` 且选择器与新池对齐，未命中时 `dom_candidates` 能吐出「附近带可及名的图标候选」——既助**取证**（看真实 DOM 里图标的可及名长什么样），也助上层在 R4 未命中时判断「是缺口③纯视觉、该降 vision/R3」。

### 4.4 不改的部分（NG2/NG3）

- `_geom.py` 坐标映射、`_bridge.py` 协议、`_locate.py` 编排、四工具契约、返回结构（候选仍 `{text, role, center, box, visible, clickable, editable}`）——全不动。`accessibleName` 只改 `text` 的来源覆盖面。
- 既有 `visibleText` 函数**保留原样**（`accessibleName` 内部调它），data-placeholder/回读/真编辑体排序（59fe476）零回归。
- css 逃生口不变（agent 仍可传显式选择器兜底；R4 只是减少其必要性）。

### 4.5 部署

content.js 改动 → 模板哈希 `template_hash()` 变（计算在 `human_dom/_setup.py:9-16`）→ 已装 per-profile 副本在下次 `human_browser_open` 时**自动重烤**（重烤判定在 `browser/_human_browser.py:160-166`：`meta.tpl_hash != template_hash()` 即 `prepare_extension` 重烤），消费方无需手动重装。

---

## 五、测试策略

> 测试现实同 R1：`platforms/common/tests` 不进 CI required；content.js 的测试用 **node vm 真跑源码**（现有 `test_content_js_visibletext.mjs` 手法），本地 `node` 可跑、靠 review gate + 真机保证。

### 5.1 node-vm 单测（扩 `test_content_js_visibletext.mjs` 或新 `test_content_js_accessible_name.mjs`）

- **回归守卫（分两层）**：① 现有 5 条 `visibleText` 断言（`test_content_js_visibletext.mjs:30-36`）保留必须过——守「visibleText 函数体没被改」（必要非充分）；② **新增主守卫**：对既有链非空的 el 断言 `accessibleName(el) === visibleText(el)`（证 step2 短路正确、fallback 不吃既有非空结果）——这才是「未改既有命中」的直接证明。
- **accessibleName 新源**（构造带后代/引用的 fake el）：
  - `<div role=button><img alt=视频></div>` → "视频"（后代 img alt）；
  - `<div aria-labelledby=lbl>` + `#lbl` innerText "插入图片" → "插入图片"（labelledby 解析）；id 不存在时 null-guard 不崩、回落后代；
  - `<img alt=文章>` → "文章"（自身 alt）；
  - 既有链非空时**不走 fallback**（如 `aria-label=X` + 后代 img alt=Y → 返回 X，证优先级/零回归）。
  - fake 需支持 `el.querySelector(sel)` 返回 fake 后代、`document.getElementById(id)` 返回 fake / null——扩现有 vm 上下文（`test_content_js_visibletext.mjs:14-24`）。
- **matchAll 级（补现有测试盲区）**：让 fake `document.querySelectorAll(sel)` 返回带 `getBoundingClientRect`/`getAttribute`/`querySelector` 的合成元素数组，断言：① 扩池纳入 `[aria-label]`/`img[alt]` 图标；② DOM-包含去重不出重复候选、**且不误并相邻不同图标**（喂两个非嵌套的相邻图标，断言两个都在）；③ accessibleName 空的纯视觉元素仍被丢。
- **测不到的死角（诚实标注）**：vm 的 fake `querySelectorAll` 手喂结果，**验不了「扩池选择器字符串本身正确」**（`[aria-label]` 之类 typo vm 测不出）——这层只有真机/真 DOM 兜（§5.2）。

### 5.2 真机取证 + 验收（§1.4 premise 落地）

- **落地第一步·取证**（用户将在下一次 10 轮 E2E 或 R1 Phase C 真机那步、用登录态 session 顺带做）：dump 后台「新建内容」那几个入口（文章/图片/视频/音频）的**实际 DOM** → ① 定稿 `accessibleName` 精确抽取规则（对齐真实标签所在的属性/结构）；② 确认缺口①②占大头（对症）；③ **确认入口图标在顶层 frame、不在 iframe**（human_dom 只注顶层 frame，入口若在 iframe 则 R4 对该 surface 整体失效）。dump 出的结构补进仓内 fixture（`platforms/common/tests/fixtures/`），让 matchAll 级单测用**真实结构**而非纯合成。**取证反转（任一即回报用户调方向，不硬做）**：③纯视觉占大头 → 提前 R3；入口在 iframe → R4 对该 surface 失效、需另做 all_frames 工作。
- **验收**：取证确认的图标入口 `human_dom_locate` 命中、`human_dom_tap` 点中正确图标（**不误点邻居**，正对 #100 的相邻误点）；标题/正文既有场景回归不破。

### 5.3 质量门禁（charter）
架构审（本 spec）→ 实现后 code-reviewer 审 → 真机取证+验收 → 过了才合并 + tag。

---

## 六、验收判据（逐条可核）

1. 带可及名图标（后代 img-alt / aria-labelledby / 自身 alt）能 `human_dom_locate` 命中并返回可点坐标。
2. **零回归（限定义）**：指「既有**非空命中**的 text/role/坐标不变 + 可编辑**填充流**（fill 取可编辑优先的 `candidates[0]`）不变」——`accessibleName` 只在既有链返回空时追加，既有非空结果字节级不变。**注意 locate/tap 的候选集会扩**（新增图标候选是预期增益）：某新图标若可及名精确等于 query，可能因 `_exact` 上浮改变 tap/locate 的 `candidates[0]`——这是 R4 的目的（纳入并优先该图标），**非回归**。零回归**主证**=新增的 `accessibleName` 短路断言 + matchAll 级断言（§5.1）；既有 5 条 `visibleText` mjs 断言只守「visibleText 函数体没被改」，必要非充分。
3. 有界扩池只纳入带可及名源元素；纯视觉零可及名元素仍被丢（不污染文本查询）；**DOM-包含去重**无重复候选、**且不误并相邻不同图标**（绝不按中心距）。
4. 诊断 `dom_candidates` 反映附近带可及名候选（助取证/降级）。
5. 坐标/桥/契约/iframe 不动；vision 主文字路径不碰。
6. **premise 取证结论**回报：缺口①②/③ 占比 + **入口是否在 iframe**，据以确认 R4 对症 / 建议提前 R3 / 或 iframe 需另做 all_frames 工作。

---

## 七、决策记录（每条追回需求）

| 决策 | 选择 | 追回的需求 / 依据 |
|---|---|---|
| 改法纪律 | 既有 visibleText 链不动, 只加 fallback | §1.3/§4.1；59fe476「这条链极易埋 bug」的教训, 回归安全第一 |
| 可及名算法 | 实用子集(labelledby/自身 alt/后代 img-alt/aria-label/svg title), 非全量 ARIA | §1.3-①；NG6 全量过重 |
| 扩池 | 有界(只加带可及名源选择器), 非全 div 扫 | §1.3-②；方案 C 池爆炸 |
| iframe | 不碰(NG1); 入口是否在 iframe **未取证**, 列为反转闸 | §1.4 第4类反转闸；59fe476 只证编辑器 surface 非 iframe, 不外推到入口图标 |
| 纯视觉图标 | 划归 R3/R5, 不在 R4 | §1.4 premise；R4 是文本/DOM 抽取, 治不了零可及名 |
| 去重 | 仅按 DOM 包含关系(祖先/contains)或不去重; 绝不按中心距 | 架构审 BLOCKING：中心距会误并 #100 要消歧的相邻不同图标 |
| premise | 写进 spec + 落地首步真机取证 | §1.4；R1 同款「先取证再定性」, 防把③误当①② |
| 契约/坐标 | 不动 | NG2；R4 只扩 text 来源覆盖面 |

---

## 八、落地位置与文件清单（给 writing-plans）

**修改**
- `platforms/common/capabilities/human_dom/extension/content.js`：① 加 `accessibleName(el)`（既有 `visibleText` 不动、其后追加 fallback）；② `matchAll` 改调 `accessibleName` + 扩池选择器（`[aria-label]/[aria-labelledby]/img[alt]`，`[title]` 暂缓）+ **DOM-包含去重**（非中心距）；③ `visibleSample` 改用 `accessibleName` + 对齐选择器（**先 slice 再 map**，避免 not-found 诊断路径对全量样本跑带后代 querySelector 的 accessibleName）。

**无需改（确认即可）**
- `human_dom/_setup.py`（`template_hash` 计算）+ `browser/_human_browser.py:160-166`（重烤判定 `tpl_hash != template_hash()`）：content.js 一改哈希变、下次 `human_browser_open` 自动重烤，不改逻辑。

**新建 / 扩测**
- `platforms/common/tests/test_content_js_visibletext.mjs`（扩）或新 `test_content_js_accessible_name.mjs`：accessibleName 各源 + 零回归主守卫（`accessibleName===visibleText` on 既有非空）+ matchAll 级（合成 document，含去重不误并相邻图标）。
- `platforms/common/tests/fixtures/`（取证后）：真实入口 DOM 结构，让 matchAll 级测用真实结构。

**不动**：`_geom.py`、`_bridge.py`、`_locate.py`、`_human_dom.py`（四工具契约）、manifest（不加 all_frames）、vision、坐标映射。

---

## 附：给 writing-plans 的实现注意
- **零回归红线**：`accessibleName` 第 1 步必须是原样 `visibleText(el)`、非空即返回；新源只在其空时追加。先跑既有 5 条 mjs 断言证不回归，再加新断言。
- **只读铁律**：新代码只读属性/textContent，绝不 `.click()`/改 DOM（`content.js:1`）。
- **后代扫有界**：每元素 querySelector 取第一个匹配即止 + 限浅层（`:scope` 直接/近层，防误取深层无关 alt）；池已有界。
- **去重**：**仅按 DOM 包含关系**（`a.el.contains(b.el)` 且可及名相同 → 保留外层可点容器），或干脆不去重；**绝不按中心距**（会误并 #100 要消歧的相邻不同图标）。
- **labelledby null-guard**：`document.getElementById` 可能返回 null，跳过不存在的 id、不崩。
- **取证优先（四类反转闸）**：实现首步用**真实后台入口 DOM**（非编辑器标题 surface）定稿规则、证 premise；取证若发现 ③纯视觉占大头 → 回报建议提前 R3；入口在 iframe → R4 对该 surface 失效、回报另做 all_frames，均不硬做。
- **部署**：content.js 一改，`template_hash` 变 → `browser/_human_browser.py:160-166` 判 `tpl_hash` 不符触发已装副本重烤，消费方免手动重装。
