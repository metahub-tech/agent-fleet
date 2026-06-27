# human_dom 按 profile 维度路由 + 桥端口可配 设计

> 状态：设计稿（待评审）｜日期：2026-06-26｜关联：[[2026-06-24-human-dom-perception-capability]]、AgentHub #197

## 1. 需求与场景（从这里来）

### 1.1 起因
human_dom 的桥（content script ↔ server 的本地 WS）当前**按「active tab」路由**：server 收到 `human_dom_locate` 后，把请求派给**第一个 `document.hidden==false`（可见）且连接最早的** content script。这在「同一个 server 下有多个浏览器 profile 同时开着可见页面」时**会派错 tab**。

### 1.2 真实场景（为什么必须改）
- **单 operator 多 profile**：一个 Claude 开了 5 个 profile（如 5 个不同账号的浏览器），每个都有可见页面。调 `human_dom_locate` 时，桥只认「谁可见 + 谁先连」，**不认「我要操作哪个 profile」** → 派到错的浏览器、写错账号。
- **关键认知（实测）**：`active` 跟的是页面可见性 `document.hidden`，只在「窗口内切 tab」或「最小化窗口」时变；**点击/聚焦另一个窗口、窗口被遮挡都不会**让对方 tab 变 hidden。所以多个可见窗口下，`active` 同时为真的有多个，桥按连接顺序取第一个——**点了哪个窗口都不影响**。#197 验证时只能靠「最小化发布员默认窗口」让它 hidden 才不串线，印证了这点。
- **多 operator 共用一台机**（Claude + openclaw）：同理，更乱。

### 1.3 目标
1. **按 profile（浏览器）维度提供 DOM 能力**：`human_dom_*` 指定操作哪个 profile，桥确定性地路由到该 profile 的（前台）tab，不再全局猜。
2. **支持一台机多个 server**（本期 openclaw 暂定独立 server）：桥端口可配，两套 server 互不抢端口。
3. **默认日常 Chrome（profile 留空）照常可用**，且与专用 profile 不串线。
4. 向后兼容现有默认 profile 安装。

### 1.4 非目标
- 不解决「两个 operator 同时驱动同一块物理屏」——OS 级 tap/type 仍是一块屏，仍需轮流。本设计只保证**路由不串线**。
- 不做 profile 自动发现 UI（注入用安装时烤入，见 §4.1）。

---

## 2. 现状（改之前）

- `_bridge.py DomBridge`：`_clients=[{ws,tab_id,url,active}]`（**无 profile 字段**）；`_active()` 取第一个 `active==true`；`locate()` 派给它。
- `content.js`：连 `ws://127.0.0.1:${PORT}/dom-bridge`（`PORT=__AF_HUMAN_DOM_PORT__||8779`）；auth 帧发 `{type:"auth",token,tab_id,url,active}`（**无 profile**）。
- `run_bridge_loopback(..., port=8779)`：win/mac 调用处**写死 8779**。
- `human_dom_locate/tap/fill(query,css[,nth])`：**无 profile 参数**。
- 扩展安装：per-profile Load-unpacked（Chrome 137+ 禁用 `--load-extension`，见 [[2026-06-24-human-dom-perception-capability]]）。

---

## 3. 设计总览

两条改动，合起来支撑「多 server × 多 profile」：

- **A. 按 profile 路由**（核心 correctness 修复）：content script 上报自己的 `profile_id`；`human_dom_*` 加 `profile` 参数；桥按 `profile_id` 分组、在该组内取 active tab 派发。
- **B. 桥端口可配**（支撑多 server）：桥端口从 `--port` 派生（默认 `+13`，保持 8766→8779 不变），可 `--dom-bridge-port` 覆盖。

扩展每个 profile 的副本在**安装时烤入两样**：`PORT`（连哪个 server 的桥）+ `PROFILE_ID`（自己是哪个 profile）。

```
Claude ──human_dom_locate(profile=X)──▶ server(:8766 桥:8779)
                                          │ 按 profile_id==id(X) 选该 profile 的 active tab
                                          ▼
                            profile X 的扩展(content script，烤了 PORT=8779/PROFILE_ID=id(X))
                                          │ 只读 DOM → 视口坐标
                                          ▼
                        server 换算屏幕坐标 ──▶ Claude

openclaw ──human_dom_locate(profile=Y)──▶ 独立 server(:8767 桥:8780)  ← 端口隔离，互不抢
```

---

## 4. 组件设计

### 4.1 profile 身份注入（方案 a：安装时烤入 per-profile 扩展副本）
**问题**：content script 拿不到自己所在的 Chrome profile（Chrome 不向页面暴露 profile 身份）。
**解法**：扩展是 per-profile 安装的；安装某 profile 时**就知道**是哪个 profile，于是把 `PROFILE_ID` 烤进那一份扩展的 content.js。

- 扩展目录改为「模板 + 生成」：
  - `extension/content.js` 里两个占位常量：`const PORT = __AF_PORT__;`、`const PROFILE_ID = "__AF_PROFILE_ID__";`。
  - 新增 setup 函数 `prepare_extension(out_dir, bridge_port, profile_id)`：把模板拷到 `out_dir`、把 `__AF_PORT__`→端口、`__AF_PROFILE_ID__`→profile_id、再写一份 `meta.json {profile_id, bridge_port}`（给 `human_dom_status` 用，§4.5a），产出该 profile 专属扩展目录，再 Load-unpacked。
- 每 profile 一个扩展目录（如 `~/.fleet/human-dom-ext/<profile_id>/`）。代价：多目录；收益：确定、零运行时依赖、与 Chrome137+ Load-unpacked 一致。
- **旧装法兼容**：旧扩展没有这些占位/没 PROFILE_ID → 不发 `profile_id`，由桥侧按缺省视为 `"default"`（§4.8），不靠 content.js 兜底。

### 4.2 profile 标识规范化（install 与 locate 必须用同一套）——算法写死
定义共享纯函数 `human_dom_profile_id(profile_str) -> str`（放 `capabilities/human_dom/_ident.py`，被 install + human_dom 工具共用）。**不能直接用 `_resolve_profile` 的 key**（key 形如 `/abs/udd::Default`，含 `::`、`/`、绝对路径——既不能当文件系统目录名(win 非法字符)，两端规范化也易对不上）。算法写死为「可读前缀 + 短散列」、**文件系统安全**：

```
def human_dom_profile_id(profile_str):
    s = (profile_str or "").strip()
    if not s: return "default"
    udd, pdir, _key = _resolve_profile(s)          # 复用同一解析，吸收 ""/路径/dir@Name 差异
    canon = f"{os.path.realpath(os.path.expanduser(udd))}::{pdir or ''}"  # 规范化基准
    h = hashlib.sha1(canon.encode()).hexdigest()[:8]
    slug = re.sub(r'[^a-z0-9]+','-', os.path.basename(udd).lower()).strip('-')[:24] or "p"
    return f"{slug}-{h}"                            # 如 wechat-pub-3f9a1c2b；纯 [a-z0-9-]，可当目录名
```
- 输出**纯 `[a-z0-9-]`**：既做 `profile_id`、又直接做扩展目录名 `~/.fleet/human-dom-ext/<profile_id>/`，win/mac 都合法。
- **以 `_resolve_profile` 的解析结果为基准**（不是原始串）：`~/.fleet/x`、`/abs/.../x`、`x@Default` 等只要 `_resolve_profile` 解到同一 udd/pdir 就得同一 id，吸收入参格式差异。
- **铁律**：安装某 profile 烤入的 `PROFILE_ID` == `human_dom_profile_id(开这个 profile 用的同一 profile 串)`。调用方对三处（`human_browser_open` / 安装 / `human_dom_locate`）传同一 profile 串即对上；不一致表现为 `no_tab_for_profile`（§6）。

### 4.3 content.js
- auth 帧加 `profile_id`：`{type:"auth", token, profile_id, tab_id, url, active}`。
- 其余不变（仍只读、仍 visibilitychange 重报 active）。

### 4.4 桥 `_bridge.py`
- `register(ws, profile_id, tab_id, url, active)`：client 增 `profile_id` 字段。
- `_active(profile_id)`：在 `c["profile_id"]==profile_id` 的 client 里取第一个 `active==true`，无 active 则取该组第一个；该 profile 无任何 client → `None`。
- `locate(query, css, profile_id, ...)`：等到该 profile 有 client、派给其 active tab；超时/无该 profile 的 client → 抛 `NoProfileTab`（区别于通用超时）。

### 4.5 human_dom 工具 `_human_dom.py` + `_locate.py`
- `human_dom_locate(query, css="", max_results=10, profile="")`、`human_dom_tap(query, nth=0, css="", profile="")`、`human_dom_fill(query, text, css="", profile="")`。
- 内部 `pid = human_dom_profile_id(profile)`，传给 `resolve_locate(bridge, ..., profile_id=pid)`。
- `resolve_locate`：透传 profile_id；无该 profile 的 tab → `{"ok":False,"reason":"no_tab_for_profile","profile":pid,"suggest":"该 profile 可能(a)没起浏览器/没导航到目标页，或(b)没装 human_dom 扩展(每个 profile 要单独装，见 using-human-dom)；先确认，或用 vision_locate 兜底"}`。
- **M3 诊断性**：全局 marker `~/.fleet/human-dom-ready` 只表示"本机装过"，**不代表某个 profile 装了**。本期加 per-profile 安装状态（§4.5a），suggest 文案 + status 工具一起把"该 profile 没装扩展"诊断清楚。

### 4.5a per-profile 安装状态（Q1：本期）
要能**显式判断某个 profile 装没装扩展**（管理 10 个 profile 时必需）。两个维度：
- **静态（装没装，不依赖开页面）**：`prepare_extension` 给每 profile 生成 `~/.fleet/human-dom-ext/<profile_id>/` 目录，内含烤好的 content.js + 一份 `meta.json {profile_id, bridge_port}`。**目录存在 = 该 profile 装过**；`bridge_port` 记它归哪个 server（端口）。
- **运行时（当前连没连桥）**：桥的 `_clients` 带 `profile_id` → server 知道当前哪些 profile 的 content script 连着（= 装好且有 http 页面开着）。
- **新工具 `human_dom_status() -> {profiles:[{profile_id, installed, bridge_port, connected, tab_url?}]}`**：
  - 扫 `~/.fleet/human-dom-ext/*/meta.json` 里 `bridge_port == 本 server 桥端口` 的（= 归本 server 的 profile）→ `installed=true`；
  - 与桥当前连着的 profile_id 求交 → `connected=true`；
  - 让 agent/用户一眼看清「哪些 profile 装了、连着、归本 server」。
- 注：本 server 只列归自己（端口匹配）的 profile；跨 server 的扩展看不到（按端口隔离，Q4-B）。

### 4.6 桥端口可配 `_bridge.py` + server 接线
**S1 控制流（必须先理顺）**：现状 `main()` 里**先** `run_bridge_loopback(..., port=8779)`（写死）、**再** `_server_runtime.serve(mcp, ...)`，而 `serve()` 内部自己 `parse_server_args()`、不把 args 暴露给 caller → **按 args 取桥端口的链路是断的**。改法：
- `_server_runtime` 暴露 `parse_server_args()`，且 `serve(mcp, *, args=None, ...)` 接受**已解析的 args**（None 时才自己 parse，保持兼容）。
- win/mac `main()` 改为：`args = parse_server_args()` → `bridge_port = resolve_bridge_port(args)` → `run_bridge_loopback(..., port=bridge_port)` → `serve(mcp, args=args, ...)`。
- argparse 加可选 `--dom-bridge-port`。

**桥端口在「server 启动时」一次定死并持久化（关键：扩展安装读这个持久值，不在扩展侧探端口）**：
`resolve_bridge_port(args)` 顺序——
1. `--dom-bridge-port` 显式给 → 用它；
2. 否则读持久文件 `~/.fleet/dom-bridge-<mcp_port>.port`，若其中端口**当前可绑** → 用它（**跨重启稳定**：已烤好的扩展继续对得上）；
3. 否则试 `mcp_port + 13`，可绑 → 用它（dev `8766→8779` 维持不变、兼容现有扩展）；
4. **仍被占用 → 从 `mcp_port+13` 起向后扫**（+14、+15…）到第一个可绑端口；
5. 把最终选定端口**写回 `~/.fleet/dom-bridge-<mcp_port>.port`** 并日志打印。
- **为什么在启动时扫、而不在扩展安装时扫**：端口必须和扩展烤死的 PORT 一致；启动时定死并持久 → **后续所有扩展安装都读这个持久值来烤**，server 与扩展永远一致。
- **扩展安装取端口**：`prepare_extension(...)` 的 `bridge_port` 由安装流程从 `~/.fleet/dom-bridge-<mcp_port>.port` 读取（或查运行中 server 的 `human_dom_status`，见 §4.5a），不让人工填、不在扩展侧猜。
- 同机多 server（如 dev :8766 与 openclaw :8767）各自按上面解析：8766→8779、8767→8780（撞了自动向后扫），各写各的持久文件，互不干扰。

### 4.7 默认日常 Chrome（profile 留空）——重点考虑
- `human_browser_open(profile="")` = 默认日常 Chrome（`open -a`/直起），其 human_dom **同样按 profile 路由**，`profile_id="default"`。
- 默认 profile 的扩展由安装引导装入：先 `prepare_extension(out_dir="~/.fleet/human-dom-ext/default", bridge_port=<该机 server 派生端口=--port+13>, profile_id="default")` 生成目录，再 Load-unpacked 那个 out_dir。
  - bridge_port 来自该机 server 的 `--port`（脚本/工具读同一派生：`--port+13`，或调用方显式给）。
  - **M1 流程衔接**：`prepare_extension` 是 Python（跨平台）；安装引导负责调它拿到 `out_dir` 后**打印/打开**该目录供用户 Load-unpacked。mac 改 `install-human-dom-extension.sh`、**win 新增 `scripts/install-human-dom-extension.ps1`**（N2，本期范围）；视觉 agent 自助流程（using-human-dom）也改为「先 prepare_extension 再 Load-unpacked 那个 out_dir」。
  - **M1 运维提醒**：Load-unpacked 扩展 ID 由目录绝对路径决定 → **别移动 `~/.fleet/human-dom-ext/`**，移动后扩展会从 Chrome 消失需重装；写进 skill 注意事项。
- `human_dom_locate(profile="")` → `human_dom_profile_id("")="default"` → 路由到默认 profile 的 active tab（用户日常浏览器里当前前台那个 tab）。
- 默认 profile 与专用 profile 同时装了 human_dom：`profile=""`→默认、`profile="~/.fleet/X"`→专用，**不串线**。

### 4.8a 桥并发 / event-loop 模型（S2，借这次一并加固）
现状 `run_bridge_loopback` 用 `asyncio.run(server.serve())` 在**独立守护线程的独立 loop** 跑；而 `human_dom_locate` 在 MCP 主 loop 执行。于是 `bridge.locate()` 跨 loop `ws.send_json()` + `_deliver` 跨线程 `fut.set_result()` 都是**未定义行为**，`_clients` 也无锁。单 profile 下并发少没爆，profile 路由后并发上升，必须加固。

- **决策：桥 loopback listener 跑在 MCP server 的同一 event loop 内**（用 FastMCP 启动钩子/lifespan 把 `server.serve()` 作为 task 起在主 loop），**仍只绑 `127.0.0.1`**（不挂 MCP 的 0.0.0.0 app，保 [[2026-06-24-human-dom-perception-capability]] 定的「loopback-only 不暴露 LAN」）。单 loop → 没有跨 loop 的 ws/future 问题。
- `_clients` 全在该单 loop 内访问；遍历（`_active`）时对列表**取快照**再迭代，避免 unregister 并发改表。
- 若启动钩子接线代价过大，退路：保留独立线程，但 `ws.send_json` 走 `run_coroutine_threadsafe(..., bridge_loop)`、`fut.set_result` 走 `mcp_loop.call_soon_threadsafe`、`_clients` 加 `threading.Lock`。**首选单 loop**。

### 4.8 向后兼容与迁移
- **旧扩展（没烤 PROFILE_ID）**：auth 不带 `profile_id` → 桥按缺省视为 `"default"`（让现存「默认 profile 安装」继续配 `profile=""` 用）。
- **旧调用（不传 profile）**：`profile` 默认 `""` → `"default"`。即「不传 profile」语义 = 操作默认日常 Chrome。
- ⚠️ **M4 安全风险（比"找不到"更严重）**：若**默认 profile 也装了扩展**（既有装法就装在日常 Chrome）且日常 Chrome 开着，旧调用方（本该操作专用 profile 却没传 profile）会 `profile=""`→**悄悄路由到日常 Chrome 的某个 tab、操作错账号**（不是 `no_tab_for_profile`，是"找错了"，更难发现）。对策：
  - **桥绝不 fallback**：请求的 profile 无 client 时直接 `no_tab_for_profile`，**即使 default 有 client 也不回落**（§6）。这能挡住"目标 profile 没起"的情况，但挡不住"调用方把专用误写成默认"。
  - **真正的防线 = 调用方显式传 profile**。因此：**合并前必须同步改完所有真账号调用方的 profile 传参**——尤其 **ops 仓发布员/pulse prompt 的 human_dom 调用补 `profile=<固定值>`**，这是**本变更的硬前提/阻断项**（不是"单独跟进"）。skill 示例同步（§7）。
- 端口派生默认保持 8779（dev），现有默认 profile 扩展（连 8779）不受影响。

---

## 5. 数据流（改后准确版）

1. Claude 调 `human_dom_locate(query, profile=X)`（profile 串与 `human_browser_open` 一致）。
2. 工具算 `pid=human_dom_profile_id(X)`，调 `bridge.locate(..., profile_id=pid)`。
3. 桥在 `profile_id==pid` 的 client 里取 active tab，往其**已建立的 WS** 推 `{op:"locate",...}`。
4. 该 profile 的 content script 只读 DOM → 返回**视口坐标** + geom。
5. server `viewport_to_screen` 换算**屏幕坐标** → 返回 Claude。

（与旧流程唯一区别：第 3 步「按 active tab」改为「按 profile 的 active tab」。）

---

## 6. 错误处理

- 请求的 profile 没有任何 client 连入 → `{ok:False, reason:"no_tab_for_profile", profile, suggest:...}`（不静默回落 active-tab，避免重新引入串线）。
- 该 profile 有 client 但都 hidden（无 active）→ 取该组第一个（与现状一致，组内兜底）。
- 桥未连 / 超时 → 沿用 `bridge_no_active_tab`/`bridge_error`，suggest `vision_locate`。
- profile_id 规范化两端不一致（调用串与安装串不同）→ 表现为 `no_tab_for_profile`；文档强调三处同串。

---

## 7. skill / prompt 同步

- `using-human-dom`：① `human_dom_*` 加 `profile=` 用法，强调**三处同一个 profile 串**（open/装扩展/locate）；② 自助 Load-unpacked 流程改为「先 `prepare_extension` 生成带 PROFILE_ID/PORT 的目录再 Load-unpacked」；③ 多 profile 必须显式传 profile、否则落 default。
- `using-human-browser`：专用 profile 段补「human_dom 要传同一 profile」。
- **发布员/pulse prompt（ops 仓）：human_dom 调用补 `profile=<固定值>`——这是【合并前硬前提】（M4），不是事后跟进**。虽不在本仓，但必须与本变更同批落地（否则真账号有静默误操作风险）；本仓 PR 描述里写明该依赖、合并前确认 ops 侧已改。

---

## 8. 测试

纯逻辑 Linux 可测：
- `human_dom_profile_id`：`""→"default"`、路径规范化、同入参幂等。
- `DomBridge`：多 client 不同 profile_id；`_active(pid)` 只在该组取；`locate(profile_id)` 派到对组、对其它组不影响；无该 profile → 抛/`no_tab_for_profile`；缺 profile_id 视为 default。
- `resolve_bridge_port`：显式覆盖 > 持久值(可绑) > port+13 > 向后扫；持久文件读写；持久值不可绑时回落扫描。
- `prepare_extension`：占位替换正确（PORT/PROFILE_ID）、manifest 仍合法、写 `meta.json{profile_id,bridge_port}`。
- `human_dom_status`：扫 ext 目录(按 bridge_port 过滤本 server) × 桥连接 → installed/connected 正确；跨 server(端口不符)不计入。
真机（test-win11）：两个 profile 各装带不同 PROFILE_ID 的扩展，`human_dom_locate(profile=A)`/`(profile=B)` 分别命中各自页面、互不串线；默认 profile `profile=""` 命中默认 Chrome。

---

## 9. 本期范围与后续

- **本期**：A（profile 路由）+ B（端口启动时确定/向后扫/持久化，§4.6）+ **per-profile 安装状态 + `human_dom_status` 工具（§4.5a，Q1）** + 桥并发加固（§4.8a）+ `prepare_extension`/默认 profile/win `.ps1` 安装引导 + 兼容 + skill + ops prompt 同步（硬前提）。
- **openclaw 独立 server（确认接线）**：openclaw 在 test-win11 起的 server 是 `--port 8767` → 桥派生 **8780**；其操作的每个 profile 装的扩展用 `prepare_extension(bridge_port=8780, profile_id=…)` 生成；与 dev(:8766/8779) 端口隔离、各自 profile 路由。我这套 dev 维持 8766/8779 不动。
- **已知债（本期不改，知会）**：① `~/.fleet/human-dom-ready` marker 在引导打印后即写、不等真装完（N4，旧债，靠 suggest 文案补偿）；② `tab_id=Date.now()` 同毫秒可能重复（N3，当前只按 profile 路由、不影响，注明"tab_id 仅 debug、不保证唯一"）。
- **后续/可选**：`prepare_extension`/`human_dom_status` 做成 fleet-cli 子命令；availability() 改读 per-profile（目前仍用全局 marker）。
