// 用【真实 content.js 源码】验 visibleText 逐项 trim, 防 `||` 短路回归(AgentHub #100 轮29 标题 blocker)。
// 真编辑体 innerText 常是纯空白 "\n"(truthy 字符串), 若对整条 || 链最后统一 trim 会在 innerText 处短路,
// 永远读不到 data-placeholder。字符串断言测不出这个, 必须真跑 JS。运行: node tests/test_content_js_visibletext.mjs
import { readFileSync } from "fs";
import vm from "vm";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const here = dirname(fileURLToPath(import.meta.url));
let src = readFileSync(join(here, "../capabilities/human_dom/extension/content.js"), "utf8");
// 模拟 prepare_extension 的占位替换, 让浏览器脚本可在 vm 里 eval(否则 __AF_PORT__ 未声明会 ReferenceError)。
src = src.replace(/__AF_PORT__/g, "8779").replace(/"__AF_PROFILE_ID__"/g, '"t"');

const ctx = {
  WebSocket: function () { this.send = () => {}; },  // 装载即 connect(), stub 掉真连接
  document: { hidden: false, addEventListener: () => {}, querySelectorAll: () => [] },
  location: { href: "about:blank" }, setTimeout: () => {}, window: {},
  screenX: 0, screenY: 0, innerWidth: 0, innerHeight: 0, outerWidth: 0, outerHeight: 0,
  devicePixelRatio: 1, scrollX: 0, scrollY: 0,
};
vm.createContext(ctx);
vm.runInContext(src, ctx);  // 顶层 function 声明挂到 ctx 上 -> ctx.visibleText 可调

const mk = (p) => ({ innerText: p.it, value: p.val, getAttribute: (k) => (k in p ? p[k] : null) });
let failed = 0;
const check = (got, want, msg) => {
  if (got !== want) { console.error(`FAIL: ${msg} — 得到 ${JSON.stringify(got)} 期望 ${JSON.stringify(want)}`); failed++; }
};
// ★ 真实 ProseMirror 标题: innerText 为 "\n"(truthy), 占位只在 data-placeholder。这是轮29 的具体 blocker。
check(ctx.visibleText(mk({ it: "\n", "data-placeholder": "请在这里输入标题" })), "请在这里输入标题",
  'innerText="\\n" 应回落 data-placeholder');
check(ctx.visibleText(mk({ it: "   ", "aria-placeholder": "副标题占位" })), "副标题占位",
  "纯空格 innerText 应回落 aria-placeholder");
check(ctx.visibleText(mk({ it: "落字验证E2E" })), "落字验证E2E", "已填文本取 innerText");
check(ctx.visibleText(mk({ it: "", val: "x" })), "x", "空 innerText 回落 value");
check(ctx.visibleText(mk({ it: "  真实文本  " })), "真实文本", "innerText 两侧空白被 trim");

if (failed) { console.error(`${failed} 条失败`); process.exit(1); }
console.log("content.js visibleText 逐项 trim 测试全过(5/5)");
