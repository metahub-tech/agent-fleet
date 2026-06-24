// 只读铁律: 绝不 .click()/.value=/派发事件/改 DOM。端口/token 由 install 脚本注入占位常量。
const PORT = (window.__AF_HUMAN_DOM_PORT__ || 8779), TOKEN = (window.__AF_HUMAN_DOM_TOKEN__ || "");
function geom(){return {screenX, screenY, innerW:innerWidth, innerH:innerHeight,
  outerW:outerWidth, outerH:outerHeight, dpr:devicePixelRatio, scrollX, scrollY};}
function visibleText(el){const t=(el.innerText||el.value||el.getAttribute("aria-label")||
  el.getAttribute("placeholder")||el.getAttribute("title")||"").trim(); return t;}
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
        visible:true, clickable:!el.disabled, _exact: txt.toLowerCase()===q});
    }
  }
  out.sort((a,b)=>(b._exact-a._exact)); return out.slice(0,max);
}
function visibleSample(n){return [...document.querySelectorAll('a,button,[role],input,textarea')]
  .map(visibleText).filter(Boolean).slice(0,n);}
let ws = null;
function connect(){
  ws = new WebSocket(`ws://127.0.0.1:${PORT}/dom-bridge`);
  ws.onopen = ()=> ws.send(JSON.stringify({type:"auth", token:TOKEN, tab_id:String(Date.now()),
    url:location.href, active:!document.hidden}));
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
