// 验 content.js 焦点上报: 首帧不丢 profile_id/tab_id/url(delta-BLOCKING-1)、report() 带 focused、
// focus/blur/visibilitychange 三事件都触发上报、切应用(hidden=false 但 hasFocus=false)时 focused 翻 false。
// 运行: node tests/test_content_js_focus_report.mjs
import { readFileSync } from "fs";
import vm from "vm";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const here = dirname(fileURLToPath(import.meta.url));
let src = readFileSync(join(here, "../capabilities/human_dom/extension/content.js"), "utf8");
src = src.replace(/__AF_PORT__/g, "8779").replace(/"__AF_PROFILE_ID__"/g, '"op-x"');

let sent = [];                 // 捕获所有 ws.send 的 JSON
const winHandlers = {};        // 捕获 window.addEventListener
const docHandlers = {};        // 捕获 document.addEventListener
let hasFocusVal = true, hiddenVal = false;

const ctx = {
  WebSocket: function () { ctx.__last_ws = this; this.readyState = 1; this.send = (s) => sent.push(JSON.parse(s)); },
  document: {
    get hidden() { return hiddenVal; },
    hasFocus: () => hasFocusVal,
    addEventListener: (ev, fn) => { docHandlers[ev] = fn; },
    querySelectorAll: () => [],
  },
  location: { href: "https://mp.weixin.qq.com/x" },
  setTimeout: () => {},
  window: { addEventListener: (ev, fn) => { winHandlers[ev] = fn; } },
  screenX: 0, screenY: 0, innerWidth: 0, innerHeight: 0, outerWidth: 0, outerHeight: 0,
  devicePixelRatio: 1, scrollX: 0, scrollY: 0,
};
vm.createContext(ctx);
vm.runInContext(src, ctx);
ctx.__last_ws.onopen();        // 手动触发首帧(stub 不自动触发 onopen)

let failed = 0;
const check = (cond, msg) => { if (!cond) { console.error(`FAIL: ${msg}`); failed++; } };

// 首帧(auth): 必须保留 profile_id/tab_id/url + 带 focused
const auth = sent.find((m) => m.type === "auth");
check(auth && auth.profile_id === "op-x", "首帧保留 profile_id(不被折进窄 payload)");
check(auth && auth.tab_id != null && auth.url === "https://mp.weixin.qq.com/x", "首帧保留 tab_id/url");
check(auth && auth.focused === true, "首帧带 focused=true(初始 hasFocus)");

// window focus/blur/visibilitychange 三事件都注册了
check(typeof winHandlers.focus === "function", "注册了 window focus");
check(typeof winHandlers.blur === "function", "注册了 window blur");
check(typeof docHandlers.visibilitychange === "function", "注册了 visibilitychange");

// 切到别的应用: hidden 仍 false, hasFocus 翻 false → blur 事件上报 focused=false
sent = []; hasFocusVal = false;
winHandlers.blur();
const upd = sent[sent.length - 1];
check(upd && upd.type === "active" && upd.focused === false && upd.active === true,
  "切应用: 更新帧 focused=false 而 active(=!hidden) 仍 true(§6.4 取证分叉)");

if (failed) { console.error(`${failed} 条失败`); process.exit(1); }
console.log("content.js 焦点上报测试全过");
