# R4 human_dom 扩覆盖 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 human_dom 的 content.js 补更完整的可及名计算 `accessibleName`（既有 `visibleText` 链不动、只加 fallback）+ 有界扩池 + DOM-包含去重 + 诊断增强，把带可及名的公众号编辑器图标入口（文章/视频/图片…）从 vision 兜底拉回 human_dom 按文字标签精确定位，消歧相邻入口。

**Architecture:** 三处 content.js 改动（`accessibleName`、`matchAll` 扩池+去重、`visibleSample` 诊断），**回归安全第一**：`accessibleName` 第 1 步调既有 `visibleText`、非空即返回，新可及名源（labelledby/自身 alt/后代 img-alt/aria-label/svg title）只在其返回空时追加。去重**仅按 DOM 包含关系**（绝不按中心距，否则误并相邻不同图标）。坐标/桥/契约/iframe 不动。

**Tech Stack:** JS（Chrome MV3 content script，只读）；node vm 测试（真跑 content.js 源码，`node` v22 本机可跑）。

**Spec:** `docs/superpowers/specs/2026-07-06-human-dom-icon-coverage-design.md`（architect 已审，2 BLOCKING 已修）。

**测试现实：** content.js 测试用 **node vm 真跑源码**（现有 `test_content_js_visibletext.mjs` 手法），本机 `node` 可跑（非 CI，靠 review gate + 真机）。**vm 测不到「扩池选择器字符串本身正确」**（fake `querySelectorAll` 手喂结果）——那层只有真机/真 DOM 兜（Phase B 取证）。

**premise / 取证反转（写进 spec §1.4，落地必守）：** 这套框架**普适正确、不依赖 premise**。但 Phase B 取证若发现 ①**③纯视觉零可及名占大头** → 回报用户、提前 R3；②**入口图标在 iframe** → content script 无 all_frames 看不到、R4 对该 surface 整体失效 → 回报另做 all_frames，**均不硬做**。

---

## 文件结构

**修改**
- `platforms/common/capabilities/human_dom/extension/content.js`：加 `accessibleName`；`matchAll` 扩池+改调 accessibleName+DOM 包含去重；`visibleSample` 用 accessibleName+先 slice 再 map。

**新建**
- `platforms/common/tests/test_content_js_accessible_name.mjs`：R4 新逻辑的 node-vm 单测（accessibleName 各源+零回归主守卫+matchAll 扩池/去重+诊断）。
- `platforms/common/tests/fixtures/`（Phase B 取证后）：真实入口 DOM 结构，供 matchAll 级测用真实结构。

**不动**：`_geom.py`/`_bridge.py`/`_locate.py`/`_human_dom.py`（四工具契约）、`manifest.json`（不加 all_frames）、既有 `test_content_js_visibletext.mjs`（作既有 visibleText 回归守卫，必须继续过）、vision、坐标映射。

---

## Task 0: 建实现分支

- [ ] **Step 1: 从最新 main 建分支**（R4 独立于未合并的 R1 分支，从 main 起）

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git checkout main && git pull
git checkout -b feat/human-dom-icon-coverage-r4
```

---

## Phase A — content.js 框架（本机 node-vm TDD，普适正确、不依赖取证）

### Task 1: `accessibleName(el)` —— 既有链不动，追加 fallback

**Files:**
- Modify: `platforms/common/capabilities/human_dom/extension/content.js`（在 `visibleText` 之后、`isEditable` 之前插入）
- Test: `platforms/common/tests/test_content_js_accessible_name.mjs`（新建）

- [ ] **Step 1: 写失败测试**

```javascript
// platforms/common/tests/test_content_js_accessible_name.mjs
// 用【真实 content.js 源码】(node vm)验 R4 accessibleName/matchAll/去重/诊断。
// 既有 visibleText 逐项 trim 的回归守卫仍在 test_content_js_visibletext.mjs; 本文件测 R4 新增。
// 运行: node tests/test_content_js_accessible_name.mjs
import { readFileSync } from "fs";
import vm from "vm";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const here = dirname(fileURLToPath(import.meta.url));
let src = readFileSync(join(here, "../capabilities/human_dom/extension/content.js"), "utf8");
src = src.replace(/__AF_PORT__/g, "8779").replace(/"__AF_PROFILE_ID__"/g, '"t"');

const ctx = {
  WebSocket: function () { this.send = () => {}; },
  document: { hidden: false, addEventListener: () => {}, querySelectorAll: () => [], getElementById: () => null },
  location: { href: "about:blank" }, setTimeout: () => {}, window: {},
  screenX: 0, screenY: 0, innerWidth: 0, innerHeight: 0, outerWidth: 0, outerHeight: 0,
  devicePixelRatio: 1, scrollX: 0, scrollY: 0,
};
vm.createContext(ctx);
vm.runInContext(src, ctx);

let failed = 0;
const check = (got, want, msg) => {
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    console.error(`FAIL: ${msg} — 得到 ${JSON.stringify(got)} 期望 ${JSON.stringify(want)}`); failed++;
  }
};

// fake element。attrs: 自身属性; qs(sel)->fake后代|null; rect; contains(o); tag
function el(p = {}) {
  return {
    innerText: p.it, value: p.val, tagName: (p.tag || "div").toUpperCase(),
    isContentEditable: !!p.ce, disabled: !!p.disabled, textContent: p.text,
    getAttribute: (k) => (p.attrs && k in p.attrs ? p.attrs[k] : null),
    querySelector: (sel) => (p.qs ? p.qs(sel) : null),
    getBoundingClientRect: () => p.rect || { left: 0, top: 0, width: 10, height: 10 },
    contains: (o) => (p.contains ? p.contains(o) : false),
  };
}

// --- accessibleName: 零回归主守卫(既有链非空 → 必须 === visibleText, 不吃 fallback) ---
check(ctx.accessibleName(el({ it: "已填正文" })), "已填正文", "既有 innerText 非空 → 原样返回");
check(ctx.accessibleName(el({ it: "\n", attrs: { "data-placeholder": "请在这里输入标题", "aria-label": "别用我" } })),
  "请在这里输入标题", "既有链(data-placeholder)非空 → 不走 fallback, 保 59fe476");
check(ctx.accessibleName(el({ attrs: { "aria-label": "X" }, qs: () => el({ attrs: { alt: "Y" } }) })),
  "X", "既有链 aria-label 命中 → 不取后代");

// --- accessibleName: 新源(既有链返回空才走) ---
check(ctx.accessibleName(el({ attrs: { role: "button" }, qs: (s) => (s.includes("img[alt]") ? el({ attrs: { alt: "视频" } }) : null) })),
  "视频", "空既有链 → 后代 img alt");
check(ctx.accessibleName(el({ tag: "img", attrs: { alt: "文章" } })), "文章", "空既有链 → 自身 alt");
ctx.document.getElementById = (id) => (id === "lbl" ? el({ it: "插入图片" }) : null);
check(ctx.accessibleName(el({ attrs: { "aria-labelledby": "lbl" } })), "插入图片", "labelledby 解析引用元素文本");
ctx.document.getElementById = () => null;
check(ctx.accessibleName(el({ attrs: { "aria-labelledby": "missing" }, qs: (s) => (s.includes("img[alt]") ? el({ attrs: { alt: "音频" } }) : null) })),
  "音频", "labelledby id 不存在 → null-guard 不崩, 回落后代 img alt");
check(ctx.accessibleName(el({ attrs: { role: "button" } })), "", "无任何可及名源 → 空(纯视觉, 留 R3)");

if (failed) { console.error(`${failed} 条失败`); process.exit(1); }
console.log("R4 accessibleName 测试全过");
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && node tests/test_content_js_accessible_name.mjs`
Expected: 抛错 `TypeError: ctx.accessibleName is not a function`（accessibleName 未定义）

- [ ] **Step 3: 写最小实现**（在 `content.js` 的 `visibleText` 函数 `:15` 之后、`isEditable` `:16` 之前插入）

```javascript
// R4: 更完整的可及名 —— 既有 visibleText 链【完全不动】, 仅在其返回空时追加 fallback:
//   aria-labelledby → 自身 alt → 浅层后代(img[alt]/[aria-label]/svg title)。把带可及名的图标入口
//   (如 <div role=button><img alt=视频>)从 vision 兜底拉回 DOM 定位。仍只读, 绝不改 DOM。
//   顺序: 既有链非空即返回(零回归关键), 空才走新源; labelledby 优先于后代(显式名更权威)。
//   后代限浅层(1-2 层)防深层无关配图 alt; 确切层级 Phase B 取证真实 DOM 后定稿。
function accessibleName(el){
  const own = visibleText(el);
  if(own) return own;                                    // 既有非空结果原样返回
  const lb = el.getAttribute("aria-labelledby");
  if(lb){
    const t = lb.split(/\s+/).map(id=>{const r=document.getElementById(id); return r?visibleText(r):"";})
      .filter(Boolean).join(" ").trim();                 // getElementById 可能 null → 跳过
    if(t) return t;
  }
  const alt = (el.getAttribute("alt")||"").trim();       // el 本身是 <img>
  if(alt) return alt;
  const img = el.querySelector(":scope > img[alt], :scope > * > img[alt]");
  if(img){const t=(img.getAttribute("alt")||"").trim(); if(t) return t;}
  const al = el.querySelector(":scope > [aria-label], :scope > * > [aria-label]");
  if(al){const t=(al.getAttribute("aria-label")||"").trim(); if(t) return t;}
  const sv = el.querySelector(":scope svg title");
  if(sv){const t=(sv.textContent||"").trim(); if(t) return t;}
  return "";
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd platforms/common && node tests/test_content_js_accessible_name.mjs`
Expected: `R4 accessibleName 测试全过`（退出码 0）

- [ ] **Step 5: 跑既有回归守卫确认零回归**

Run: `node tests/test_content_js_visibletext.mjs`
Expected: `content.js visibleText 逐项 trim 测试全过(5/5)`（既有 visibleText 未被破坏）

- [ ] **Step 6: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/common/capabilities/human_dom/extension/content.js platforms/common/tests/test_content_js_accessible_name.mjs
git commit -m "feat(human-dom-r4): accessibleName 补 labelledby/自身alt/后代img-alt 可及名(既有链不动, 零回归)"
```

---

### Task 2: `matchAll` 扩池 + 改调 accessibleName + DOM-包含去重

**Files:**
- Modify: `platforms/common/capabilities/human_dom/extension/content.js:20-37`（`matchAll`）
- Test: 追加到 `platforms/common/tests/test_content_js_accessible_name.mjs`

- [ ] **Step 1: 追加失败测试**（在 Task 1 测试文件的 `if (failed)` 收尾**之前**插入）

```javascript
// --- matchAll: 扩池 + DOM-包含去重(绝不按中心距) ---
const imgVideo = el({ tag: "img", attrs: { alt: "视频" }, rect: { left: 5, top: 0, width: 8, height: 8 } });
const divVideo = el({ attrs: { role: "button" }, rect: { left: 0, top: 0, width: 20, height: 20 },
  qs: (s) => (s.includes("img[alt]") ? imgVideo : null), contains: (o) => o === imgVideo });
const divArticle = el({ attrs: { "aria-label": "文章" }, rect: { left: 100, top: 0, width: 20, height: 20 } });
const divPurely = el({ attrs: { role: "button" }, rect: { left: 200, top: 0, width: 20, height: 20 } }); // 无可及名
ctx.document.querySelectorAll = () => [divVideo, imgVideo, divArticle, divPurely];

const rVideo = ctx.matchAll("视频", "", 10);
check(rVideo.length, 1, "视频: div+img 双命中 → DOM 包含去重只留外层(1 个)");
check(rVideo[0].role, "button", "去重保留外层可点容器 div, 丢内层 img");
check("el" in rVideo[0], false, "去重用的临时 el 字段不入契约");

const rArticle = ctx.matchAll("文章", "", 10);
check(rArticle.length, 1, "文章: 扩池纳入 [aria-label] 裸 div");
check(rArticle[0].text, "文章", "aria-label 作可及名");

const texts = ctx.matchAll("", "", 10).map((c) => c.text).sort();
check(texts, ["文章", "视频"], "相邻不同图标(视频/文章)都在(不误并), 纯视觉 div 被丢, 无重复");
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && node tests/test_content_js_accessible_name.mjs`
Expected: FAIL（现 `matchAll` 用 `visibleText`+旧池+无去重：`rVideo.length` 得 2（div+img 未去重）或 `divArticle` 不在池 → 断言不符）

- [ ] **Step 3: 写实现**（把 `content.js:20-37` 的 `matchAll` 整体替换为）

```javascript
function matchAll(query, css, max){
  const pool = css ? [...document.querySelectorAll(css)]
    : [...document.querySelectorAll('a,button,input,textarea,[role],[onclick],[contenteditable],[aria-label],[aria-labelledby],img[alt]')];
  const q = (query||"").toLowerCase(), raw=[];
  for(const el of pool){
    const txt = accessibleName(el); if(!txt && !css) continue;
    if(css || txt.toLowerCase().includes(q)){
      const r = el.getBoundingClientRect();
      if(r.width===0||r.height===0) continue;
      raw.push({el, text:txt, role:el.getAttribute("role")||el.tagName.toLowerCase(),
        rectViewport:{left:r.left,top:r.top,width:r.width,height:r.height},
        visible:true, clickable:!el.disabled, editable:isEditable(el),
        _exact: txt.toLowerCase()===q, _editable: isEditable(el)?1:0});
    }
  }
  // R4: DOM-包含去重 —— 同可及名且被【同名 DOM 祖先】包含的候选丢掉, 只留外层可点容器
  //     (防 <div role=button><img alt=视频> 的 div 与 img 双命中)。【绝不按中心距】: 会误并相邻不同图标。
  const out = raw.filter((c)=> !raw.some((o)=> o!==c && o.text===c.text && o.el!==c.el && o.el.contains(c.el)));
  out.forEach(c=>{ delete c.el; });                       // el 仅用于去重, 不入契约
  // R3: 先按【可编辑】排(真编辑体 > 占位 widget), 再按 exact 精确匹配排。
  out.sort((a,b)=>(b._editable-a._editable)||(b._exact-a._exact)); return out.slice(0,max);
}
```

- [ ] **Step 4: 跑测试确认通过 + 回归守卫**

Run: `cd platforms/common && node tests/test_content_js_accessible_name.mjs && node tests/test_content_js_visibletext.mjs`
Expected: `R4 accessibleName 测试全过` + `content.js visibleText 逐项 trim 测试全过(5/5)`

- [ ] **Step 5: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/common/capabilities/human_dom/extension/content.js platforms/common/tests/test_content_js_accessible_name.mjs
git commit -m "feat(human-dom-r4): matchAll 有界扩池([aria-label]/[aria-labelledby]/img[alt])+DOM 包含去重(非中心距)"
```

---

### Task 3: `visibleSample` 诊断用 accessibleName + 先 slice 再 map

**Files:**
- Modify: `platforms/common/capabilities/human_dom/extension/content.js:38-39`（`visibleSample`）
- Test: 追加到 `platforms/common/tests/test_content_js_accessible_name.mjs`

- [ ] **Step 1: 追加失败测试**（在 `if (failed)` 收尾之前插入）

```javascript
// --- visibleSample: 诊断用 accessibleName, 纯视觉无名被 filter ---
ctx.document.querySelectorAll = () => [divVideo, divArticle, divPurely];
check(ctx.visibleSample(8).sort(), ["文章", "视频"], "诊断样本用 accessibleName, 纯视觉无名被 filter 掉");
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd platforms/common && node tests/test_content_js_accessible_name.mjs`
Expected: FAIL（现 `visibleSample` 用 `visibleText`：divVideo 的可及名在后代 img，`visibleText` 取不到 → 样本缺「视频」，断言不符）

- [ ] **Step 3: 写实现**（把 `content.js:38-39` 的 `visibleSample` 替换为）

```javascript
function visibleSample(n){return [...document.querySelectorAll('a,button,[role],input,textarea,[aria-label],img[alt]')]
  .slice(0,40).map(accessibleName).filter(Boolean).slice(0,n);}
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `cd platforms/common && node tests/test_content_js_accessible_name.mjs && node tests/test_content_js_visibletext.mjs`
Expected: 两个都全过

- [ ] **Step 5: 提交**

```bash
cd /home/worker/claude-test/claude-remote/af-pm
git add platforms/common/capabilities/human_dom/extension/content.js platforms/common/tests/test_content_js_accessible_name.mjs
git commit -m "feat(human-dom-r4): visibleSample 诊断改用 accessibleName(先 slice 再 map 省算)"
```

---

## Phase B — 真机取证（用户协助，四类反转闸的落地确认）

> **GATE**：Phase A 框架**普适正确、已本机测过**。Phase B 用真实 DOM **确认 premise + 定稿细节 + 加真实 fixture**，须用户登录态 session（用户已表示可在下一次 10 轮 E2E 或 R1 Phase C 顺带做）。

### Task 4: dump 后台入口 DOM + 四类确认

- [ ] **Step 1**（用户协助，登录态公众号后台）：在「新建内容」页对文章/图片/视频/音频入口，`human_dom_locate("视频")` 等 + 看诊断 `dom_candidates`，或直接 dump 那几个入口的实际 DOM（outerHTML/属性/嵌套结构）。
- [ ] **Step 2: 四类确认**（对着 spec §1.4/§5.2 反转闸）：
  - ① 入口标签所在的属性/结构（自身文字？aria-label？后代 img-alt？labelledby？）→ **定稿 accessibleName 后代层级**（现默认 1-2 层，据真实结构调 `:scope` 选择器）。
  - ② 确认缺口①②占大头（R4 对症）——命中率。
  - ③ **确认入口在顶层 frame、不在 iframe**（human_dom 只注顶层；入口若在 iframe → R4 对该 surface 整体失效）。
  - **反转**：若③纯视觉占大头 → 回报用户提前 R3；若入口在 iframe → 回报另做 all_frames。均**不硬做**。
- [ ] **Step 3: 补真实 fixture**（若结构与合成默认不同）：把 dump 的结构写进 `platforms/common/tests/fixtures/`，在 `test_content_js_accessible_name.mjs` 加一条用真实结构的 matchAll 断言；若需调 accessibleName 选择器则改 content.js 并复跑两个 mjs 测试。
- [ ] **Step 4: 提交**（若有 fixture/调整）

```bash
git add platforms/common/tests/fixtures/ platforms/common/capabilities/human_dom/extension/content.js platforms/common/tests/test_content_js_accessible_name.mjs
git commit -m "test(human-dom-r4): 补后台入口真实 DOM fixture + 据取证定稿 accessibleName 层级"
```

---

## Phase C — 真机验收（用户在场）

### Task 5: 端到端验收

- [ ] **Step 1**：登录态后台，`human_dom_locate("视频")`/`("文章")` **命中正确入口**、返回可点屏幕坐标；`human_dom_tap` **点中正确图标、不误点邻居**（正对 #100 相邻误点）。
- [ ] **Step 2: 回归**：标题 `data-placeholder`（`human_dom_locate("请在这里输入标题")`）、正文 `human_dom_fill(css='[contenteditable]', query='占位符', text=...)` 仍正常（既有场景不破）。
- [ ] **Step 3**：扩展副本自动重烤已生效（改 content.js → `tpl_hash` 变 → `human_browser_open` 自动重烤，`browser/_human_browser.py:160-166`）——真机确认命中的是新 content.js。
- [ ] **Step 4**：记录验收结论回用户（命中率、消歧效果、①②/③/iframe 结论）。

---

## 质量门禁与收口（charter）

- [ ] **code-reviewer 审**：Phase A 落完，派 code-reviewer 审 diff（重点：accessibleName 只加不改既有链、去重按包含非中心距、只读铁律、契约不动）。发现问题先修复复验。
- [ ] **真机取证+验收通过**（Task 4/5，用户协助/在场）。
- [ ] **合并 + tag**：审过 + 真机过 → squash-merge PR → 打 `v0.8.x-alpha` annotated tag → GitHub Release(prerelease=true)。**合并/发版前与用户确认**（charter 不可逆/外发条款）。

---

## Self-Review（写完计划的自查）

- **Spec 覆盖**：accessibleName(§4.1)→Task 1；有界扩池+DOM 包含去重(§4.2)→Task 2；诊断(§4.3)→Task 3；取证四类反转(§1.4/§5.2)→Task 4；真机验收+回归(§六)→Task 5；零回归主守卫(§5.1)→Task 1 Step1 的 `accessibleName===visibleText` 断言 + 每 Task 复跑既有 mjs；iframe/坐标/契约不动(NG)→不动清单。✓
- **占位扫描**：无 TBD。Phase B/C 依赖用户登录态 session（已在 GATE 说明），非空泛占位；fixtures 是取证后真实产物。
- **命名一致**：`accessibleName(el)`、`matchAll(query,css,max)`、`visibleSample(n)`、去重字段 `el`（临时、返回前 delete）、扩池选择器串全计划一致；既有 `visibleText`/`isEditable` 不改名。
