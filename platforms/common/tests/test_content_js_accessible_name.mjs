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
// 59fe476 真实场景: ProseMirror 标题 innerText="\n"、无 aria-label、占位在 data-placeholder
check(ctx.accessibleName(el({ it: "\n", attrs: { "data-placeholder": "请在这里输入标题" } })),
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
