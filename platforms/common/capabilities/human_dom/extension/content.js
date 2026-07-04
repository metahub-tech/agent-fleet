// 只读铁律: 绝不 .click()/.value=/派发事件/改 DOM。端口/token 由 install 脚本注入占位常量。
const PORT = (__AF_PORT__ || 8779), TOKEN = (window.__AF_HUMAN_DOM_TOKEN__ || "");
const PROFILE_ID = ("__AF_PROFILE_ID__" || "default");
function geom(){return {screenX, screenY, innerW:innerWidth, innerH:innerHeight,
  outerW:outerWidth, outerH:outerHeight, dpr:devicePixelRatio, scrollX, scrollY};}
// R1: 补读 data-placeholder / aria-placeholder —— ProseMirror/CodeMirror 等的占位在这两个属性里
// (真编辑体 innerText 空), 不读就永远 locate 不到(AgentHub #100 公众号标题 blocker)。仍只读、不改 DOM。
// ★ 逐项先 trim 再判真假, 取第一个非空白来源: 真编辑体 innerText 常是纯空白("\n", 是 truthy 字符串),
//   若对整条 || 链最后统一 trim 会在 innerText 处短路、永远读不到 data-placeholder(标题 blocker 不修反漏)。
function visibleText(el){
  const srcs=[el.innerText, el.value, el.getAttribute("aria-label"), el.getAttribute("placeholder"),
    el.getAttribute("data-placeholder"), el.getAttribute("aria-placeholder"), el.getAttribute("title")];
  for(const s of srcs){const t=(s||"").trim(); if(t) return t;}
  return "";
}
// R3: 真可编辑(contenteditable=true / input / textarea)判定, 排在 ce=false 占位 widget 前, 避免
// fill 打在占位壳上(ProseMirror 的占位 div 是 contenteditable=false 的 widget)。
function isEditable(el){return el.isContentEditable ||
  ["input","textarea","select"].includes(el.tagName.toLowerCase());}
function matchAll(query, css, max){
  const pool = css ? [...document.querySelectorAll(css)]
    : [...document.querySelectorAll('a,button,input,textarea,[role],[onclick],[contenteditable]')];
  const q = (query||"").toLowerCase(), out=[];
  for(const el of pool){
    const txt = visibleText(el); if(!txt && !css) continue;
    if(css || txt.toLowerCase().includes(q)){
      const r = el.getBoundingClientRect();
      if(r.width===0||r.height===0) continue;
      out.push({text:txt, role:el.getAttribute("role")||el.tagName.toLowerCase(),
        rectViewport:{left:r.left,top:r.top,width:r.width,height:r.height},
        visible:true, clickable:!el.disabled, editable:isEditable(el),
        _exact: txt.toLowerCase()===q, _editable: isEditable(el)?1:0});
    }
  }
  // R3: 先按【可编辑】排(真编辑体 > 占位 widget), 再按 exact 精确匹配排。
  out.sort((a,b)=>(b._editable-a._editable)||(b._exact-a._exact)); return out.slice(0,max);
}
function visibleSample(n){return [...document.querySelectorAll('a,button,[role],input,textarea')]
  .map(visibleText).filter(Boolean).slice(0,n);}
let ws = null;
function connect(){
  ws = new WebSocket(`ws://127.0.0.1:${PORT}/dom-bridge`);
  ws.onopen = ()=> ws.send(JSON.stringify({type:"auth", token:TOKEN, profile_id:PROFILE_ID,
    tab_id:String(Date.now()), url:location.href, active:!document.hidden}));
  ws.onmessage = (ev)=>{
    const m = JSON.parse(ev.data); if(m.op!=="locate") return;
    const cands = matchAll(m.query, m.css, m.max_results||10);
    ws.send(JSON.stringify(cands.length
      ? {id:m.id, ok:true, candidates:cands, viewport:geom()}
      : {id:m.id, ok:false, dom_candidates:visibleSample(8), viewport:geom()}));
  };
  ws.onclose = ()=> setTimeout(connect, 1000);
}
// 前后台切换时重报 active, 让桥把 locate 派给当前前台 tab(修多 tab 下 active 绑定到旧 tab)
document.addEventListener("visibilitychange", ()=>{
  if(ws && ws.readyState===1) ws.send(JSON.stringify({type:"active", active:!document.hidden}));
});
connect();
