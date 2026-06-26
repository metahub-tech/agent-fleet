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
  - 新增 setup 函数 `prepare_extension(out_dir, bridge_port, profile_id)`：把模板拷到 `out_dir`、把 `__AF_PORT__`→端口、`__AF_PROFILE_ID__`→profile_id，产出该 profile 专属扩展目录，再 Load-unpacked。
- 每 profile 一个扩展目录（如 `~/.fleet/human-dom-ext/<profile_id>/`）。代价：多目录；收益：确定、零运行时依赖、与 Chrome137+ Load-unpacked 一致。
- **旧装法兼容**：旧扩展没有这些占位/没 PROFILE_ID → 不发 `profile_id`，由桥侧按缺省视为 `"default"`（§4.8），不靠 content.js 兜底。

### 4.2 profile 标识规范化（install 与 locate 必须用同一套）
定义共享纯函数 `human_dom_profile_id(profile_str) -> str`（放 `capabilities/human_dom/_ident.py`，被 install + human_dom 工具共用）：
- `""`（默认日常 Chrome）→ `"default"`；
- 非空 → 规范化（`expanduser`、去空白、统一分隔符）后的稳定串（与 `human_browser_open(profile=...)` 同一入参得同一 id）。
- **铁律**：安装某 profile 烤入的 `PROFILE_ID` == `human_dom_profile_id(开这个 profile 时传给 human_browser_open 的 profile 串)`。调用方对三处（`human_browser_open` / 安装 / `human_dom_locate`）**用同一个 profile 串**即可对上。

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
- `resolve_locate`：透传 profile_id；无该 profile 的 tab → `{"ok":False,"reason":"no_tab_for_profile","profile":pid,"suggest":"先 human_browser_open(profile=…) 起该 profile 并装好 human_dom 扩展；或 vision_locate"}`。

### 4.6 桥端口可配 `_bridge.py` + server 接线
- `run_bridge_loopback(bridge, host, port)` 已支持传 port；改 win/mac 接线处：`bridge_port = args.dom_bridge_port or (args.port + 13)`，调用 `run_bridge_loopback(..., port=bridge_port)`。
- win/mac server 的 argparse 加可选 `--dom-bridge-port`（缺省走 `--port+13`）。
- 派生约定：`8766→8779`（dev 不变，兼容现有默认 profile 扩展）、`8767→8780`（openclaw）。日志打印实际 bridge 端口。

### 4.7 默认日常 Chrome（profile 留空）——重点考虑
- `human_browser_open(profile="")` = 默认日常 Chrome（`open -a`/直起），其 human_dom **同样按 profile 路由**，`profile_id="default"`。
- 默认 profile 的扩展由 **`install-human-dom-extension.sh`** 装入：脚本改为先 `prepare_extension(out_dir, bridge_port=<该机 server 派生端口>, profile_id="default")` 再引导 Load-unpacked 那个 out_dir。
- `human_dom_locate(profile="")` → `human_dom_profile_id("")="default"` → 路由到默认 profile 的 active tab（用户日常浏览器里当前前台那个 tab）。
- 默认 profile 与专用 profile 同时装了 human_dom：`profile=""`→默认、`profile="~/.fleet/X"`→专用，**不串线**。

### 4.8 向后兼容与迁移
- **旧扩展（没烤 PROFILE_ID）**：auth 不带 `profile_id` → 桥按缺省视为 `"default"`（让现存「默认 profile 安装」继续配 `profile=""` 用）。
- **旧调用（不传 profile）**：`profile` 默认 `""` → `"default"`。即「不传 profile」语义 = 操作默认日常 Chrome。**注意**：现有操作专用 profile 但没传 profile 的调用方（如发布员 prompt、skill 示例）**必须改成显式传 profile**，否则会路由到 default 找不到目标——skill/prompt 同步更新（见 §7）。
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
- 发布员/pulse prompt（ops 仓）：human_dom 调用补 `profile=<固定值>`（**不在本仓，单独跟 AgentHub/ops 同步**）。

---

## 8. 测试

纯逻辑 Linux 可测：
- `human_dom_profile_id`：`""→"default"`、路径规范化、同入参幂等。
- `DomBridge`：多 client 不同 profile_id；`_active(pid)` 只在该组取；`locate(profile_id)` 派到对组、对其它组不影响；无该 profile → 抛/`no_tab_for_profile`；缺 profile_id 视为 default。
- 桥端口派生：`port+13`、`--dom-bridge-port` 覆盖。
- `prepare_extension`：占位替换正确、manifest 仍合法。
真机（test-win11）：两个 profile 各装带不同 PROFILE_ID 的扩展，`human_dom_locate(profile=A)`/`(profile=B)` 分别命中各自页面、互不串线；默认 profile `profile=""` 命中默认 Chrome。

---

## 9. 本期范围与后续

- **本期**：A（profile 路由）+ B（端口可配）+ 安装/默认 profile/兼容 + skill。openclaw 独立 server 据此（:8767 派生 8780、其 profile 扩展烤 8780）。
- **后续/可选**：profile 安装台账（哪些 profile 装了扩展，避免重复装）；prepare_extension 做成 fleet-cli 子命令。
