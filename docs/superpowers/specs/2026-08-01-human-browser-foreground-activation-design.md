# 设计：human_browser 前台激活收口——治「每次 open 抢前台吞输入」(StarBeam #188)

> 状态：设计稿（待 architect 契约级审 + 需求方 spec 评审后转 writing-plans）· 2026-08-01
> 需求方：StarBeam / AgentHub（真实用户报障 StarBeam issue #188，该批唯一有真实使用困扰记录的一条）
> 落地方：agent-fleet（device 工具 owner）
> 原则：从需求来、回需求中去；改法以「翻默认 + 加显式开关」为主，blast radius 收到最小；跨仓口径（本仓 API 语义 ↔ AgentHub 成员说明书）必须同步锁死。
> 范围：P0 = human_browser_open 加 `activate` 开关 + **复用路径默认不再重激活**（直接治 #188，仅专用 profile 路径可确定性修）+ **新增 `human_dom_focused` 扩展带外前台检查**（`document.hasFocus()`，取代截图目测作首选、打破"复核前先激活"循环，§4.4/§6.4）+ **同步仓内两份 skill 文档口径**（防数据错发回归，§七）；P1 = 冷启动非激活最大化（best-effort）+ mac 后台打开。**已知不修**：Windows 无 profile/默认 Chrome 路径的单例转发重激活（§6.3，改用专用 profile 规避）。E4/句柄级输入投递（根治）后置、本期不做。

---

## 一、需求与场景（从需求来）

### 1.1 用户报障（StarBeam #188）

数字团队在**用户主力机**上执行任务时，`human_browser_open` **每次调用**都把 Chrome 窗口激活到前台，抢走用户焦点，**吞掉用户当时正在别处输入的内容**。这是该批问题里唯一有真实使用困扰记录的一条——其余问题让人不爽，这条让人**不敢在主力机上跑**，直接伤 agent-fleet「本地执行基座」的产品定位。

### 1.2 为什么频率高到「不敢用」

操作员 agent 把 `human_browser_open` 当「翻页/刷新」反复调（一个任务十几次，见 `_human_browser.py:172` 幂等复用注释的场景）。原实现**每次调用（含廉价的幂等复用路径）都重新最大化窗口 = 重新激活到前台**，于是每调一次抢一次焦点，撞上用户在别处打字。

### 1.3 需求一句话

> **human_browser_open 默认不再抢前台（尤其复用路径零重激活）；只有调用方在「即将在浏览器里动手」时显式 `activate=True` 才拉到前台。配套定义调用方约定（哪些操作前必须确保前台是目标浏览器），并与 AgentHub 成员说明书口径锁死，避免「后台窗口上敲键盘→输入打进别的应用」的新故障（比抢焦点更糟，是数据错发）。**

---

## 二、根因取证（对现行 `main` / v0.8.13-alpha 源码逐处核对）

三条独立机制（两层历史遗留 §2.1/§2.2 + 一层本轮新识别 §2.2b），均已对源码确认（AgentHub 侧取证属实，仅行号有轻微漂移）：

### 2.1 冷启动新窗抢前台（两平台，一次性）

- `_FIRST_RUN_FLAGS` 含 `--start-maximized`（`_human_browser.py:82`）。
- 起真 Chrome 的三处 `subprocess.Popen`：`:373`（默认日常 profile）/`:396`（专用 profile 冷启）/`:433`（装扩展失败降级）。新进程新窗天然拿前台。
- mac 默认路径 `open -a "Google Chrome"`（`:368`）同样激活 App。
- 性质：**每个 profile 每会话一次**，属可容忍的一次性观感，非 #188 主痛。

### 2.2 【元凶】复用路径每次重激活（Windows 专属）

- 复用（warm）路径 `:403` 无条件调 `_maybe_maximize(self._maximize_fn, udd)`，注释写着 `# 复用只做 focus/最大化`。
- `_maybe_maximize` → 注入的 `maximize_fn` → `win_input.py:178` `user32.ShowWindow(h, SW_MAXIMIZE)`；`SW_MAXIMIZE == SW_SHOWMAXIMIZED == 3`（`:120`），Win32 文档语义为「**激活**窗口并最大化」。
- **`maximize_fn` 只有 Windows server 注入**（`win_device_mcp.py:1027` `maximize_fn=maximize_chrome_window_for_udd`）；mac/linux 注入 `None` → `_maybe_maximize` 空转。
- 结论：**复用时每次重激活抢前台 = Windows 专属**。mac 复用路径本就 no-op、不抢；mac 只在 §2.1 冷启动激活一次。#188 的「每次 open 抢一次」即此层。

### 2.2b 【第三条机制·architect 补】default/no-profile 路径 Chrome 单例转发重激活（Windows，每次调用，`activate` 开关管不到）

- 无 profile 路径 `:373` `subprocess.Popen([chrome, url])`：默认 Chrome 已在跑时，这次 Popen 被 Chrome 自身 `ProcessSingleton`（隐藏窗口 + `WM_COPYDATA` IPC）转发给已有实例，**已有实例每次都会自行 `SetForegroundWindow` 把窗口带到前台**——这是 **Chrome 自己的行为，与 `_maybe_maximize`/`foreground_fn` 无关，我方 `activate` 开关对它是空转、无法从启动层抑制**。
- 性质：**每次调用都重激活**（≠ §2.1 每会话一次性残留），症状等同 #188 本身。SKILL 把「不传 profile = 日常 Chrome，一次性交互用」列为合法用法（`using-human-browser/SKILL.md:24`），若 #188 报障里含裸调用，本修不触达该路径。
- mac 同构分支 `:368` `open -a` 可用 `-g` 压掉（§6.2），**Windows 无对应手段**（Chrome 单例强制前台，无 flag 可关）。故两平台此路径**不对称**、需诚实列为已知未闭环缺口（§6.3/§八），并给规避建议：**需后台/不打扰运行的 operator 必须用专用 profile**（独立 `--user-data-dir` 实例，不走用户日常 Chrome 的单例转发、由 `foreground_fn` 受控），这与 SKILL「recurring operator 用固定专用 profile」既有指引一致。

### 2.3 供 API 分类用的落地方式取证（安全关键）

| 工具 | 落地机制（源码） | 是否碰前台 |
|---|---|---|
| `human_dom_tap` | locate 后 **OS 级 tap**（`_human_dom.py:178`，docstring「OS 级点击」） | ✅ |
| `human_dom_fill` | locate → OS tap 聚焦 → **OS 级 fill＝全选+剪贴板粘贴**（`_do_fill:43-44`） | ✅（最危险：错窗＝覆盖/误发） |
| `human_dom_locate`/`human_dom_status` | 走 CDP/扩展桥**读 DOM**，不截图不输入（`:160-167`/`:190`） | ❌ 带外 |
| `vision_tap` | vision_locate → OS tap | ✅ |
| `take_screenshot`/`vision_locate` | 读屏像素 | ⚠️ 要目标窗可见，但不写入 |

### 2.4 旁证：openclaw 落盘不是 human_browser（需求方补充项的定位）

`grep -rn "openclaw" platforms/**/*.py` **零命中**；human_browser 的 user-data-dir 由 `_resolve_profile` 决定（`isolated` 默认目录或调用方传入路径，`_browser_lease.py:61-70`），**永不含 `openclaw`**。故 `<profileDir>/browser/openclaw/user-data` 的真实 Chrome 落盘**确定不由 human_browser 起**，属 openclaw 宿主自带 browser 工具（在 AgentHub/openclaw 侧，不在本仓）。本 spec 不涉，记录以备「修完仍偶发弹窗」时回查。

---

## 三、设计目标 / 非目标

**目标**
1. `human_browser_open` 默认不抢前台；**复用路径零重激活**（P0，直接治 #188）。
2. 显式 `activate=True` 时把**该 profile 的**目标 Chrome 确定性拉到前台（供「即将动手」与「走错窗自救」用）。
3. 定义并写死**调用方约定**（Class A/B1/B2/C + 查→不对才拉的操作循环），与 AgentHub 成员说明书口径同步。
4. 对既有消费方（ops 小红书/公众号等）零回归或 blast radius 明确可控。

**非目标（本期不做）**
- 句柄级输入投递（把 OS 输入投给指定窗口句柄而非「当时的前台」）——这是竞态与「投给前台」架构的根治，量级更大，见 §八。
- 彻底消除冷启动新进程的一次性前台抢占（§六 说明为何 best-effort）。
- **修 Windows default-daily（无 profile）路径的单例转发重激活**（§2.2b/§6.3，Chrome 自身行为、无 flag 可关；规避＝用专用 profile）。
- 触碰 openclaw 宿主 browser（§2.4）。

---

## 四、契约变更

### 4.1 工具签名

```
human_browser_open(url: str = "", profile: str = "", activate: bool = False) -> dict
```

- 新增 `activate: bool = False`。**默认 False = 不强制前台**。
- 向后兼容：老调用不传 `activate` → 走默认 False（语义见 §4.2，冷启动仍一次性浮现、复用不再抢）。

### 4.2 冷/热 × activate 语义矩阵

| 路径 | `activate=False`（默认） | `activate=True` |
|---|---|---|
| **复用（warm）** | **跳过 maximize/激活**，只做既有窗口内非破坏导航（`_warm_navigate`，走 CDP、不碰前台）。← **P0 治 #188** | 把该 profile 的 Chrome 拉前台 + 最大化（现 `ShowWindow(SW_MAXIMIZE)` 行为）＝「拉回来/即将动手」 |
| **冷启动（cold）** | 起窗；Windows 做**非激活最大化**（§6.1，best-effort）；mac 尽量后台打开（§6.2）。新进程自身的一次性前台抢占为可接受残留 | 起窗 + 激活最大化（现行为） |

- 返回值加可观测字段：`activated: bool | None`（本次是否真把窗口拉到前台；`None`＝无法确定，仅 default-daily 路径用，见 §6.3）、`maximized: bool`。**两者都必须反映本次真实动作、不得用 `bool(self._maximize_fn)` 代替**（architect BLOCKING-4：现 `:410`/`:445` 用 `bool(self._maximize_fn)`，Windows 上恒非空 → 复用+activate=False 明明没动却报 `maximized:True` 假阳性，会让 §十「activate=False 复用不动前台」验收项自检失真）。故 `foreground_fn` 须返回 `acted: bool`（是否真的调用/生效），两字段据此推导：
  - **专用 profile 路径**：`maximized = acted`；`activated = (acted and activate)`。
  - **default-daily 路径**（不调 `foreground_fn`）：`maximized = False`；`activated = None`（Chrome 单例转发不受控、无法确定，见 §6.3——**不假称 False**）。

### 4.3 注入原语签名变更

- 现 `maximize_fn(udd)` → 改 `foreground_fn(udd, activate: bool) -> bool`（**返回是否真的定位到窗口并执行了操作**，供 §4.2 的 `maximized`/`activated` 如实置）：
  - `activate=True`：`ShowWindow(SW_MAXIMIZE)`（最大化 + 激活，现行为）。
  - `activate=False`：非激活最大化（§6.1）。
- 调用点（`_human_browser.py`）——**须保留 `_maybe_maximize` 那层 `try/except`「best-effort、永不抛」包装**（`:129-138` 的显式不变量），把 `activate` 参数收进该包装、由包装内部决定调不调 `foreground_fn`；**不要把条件判断裸写进业务代码**（architect BLOCKING-4：裸调一旦 Win32 抛异常会被顶层 `:447` try/except 兜成整体 `ok:False`，使「复用本已成功」退化为「整体失败」）：
  - 复用 `:403`：包装内 `if activate: acted = foreground_fn(udd, True)`；**activate=False 不调**（P0 关键——默认不调 = 不抢）。
  - 冷启动 `:444`：包装内 `acted = foreground_fn(udd, activate)`。
  - 包装捕获异常后返回 `False`（未生效），业务据此置 `maximized/activated`。
- mac/linux 仍注入 `None`；冷启动激活与否改由 §6.2 的 `open` 参数控制。

### 4.4 新增前台检查原语 `human_dom_focused`（Class C 带外，取代截图目测作首选）

```
human_dom_focused(profile: str = "") -> dict
# → {ok: bool, focused: bool | None, profile: str, reason: str}
```

- 语义：返回**该 profile 当前活跃 tab 是否真持有焦点**（`document.hasFocus()`，见 §6.4）。
  - `focused=true`：该 profile 的活动 tab 持有焦点，OS 键鼠会落进它 → Class A 可直接操作。
  - `focused=false`：连着但没焦点（窗口不在前台 / 用户切到别的 tab 或应用）→ 需 `activate=True` 拉回。
  - `focused=None`：**拿不到信号**（该 profile 未连桥 / 当前是 `chrome://` 等扩展不注入页 / 目标非 Chrome）→ 调用方回落 `take_screenshot`（§5.2 兜底分支）。`reason` 给出是哪种。
- `profile` 省略 → 复用既有 `resolve_profile_id`（继承当前活跃 operator，与 locate/tap/fill 一致）。
- **与既有 `active` 严格分离**：桥现有 `active=!document.hidden`（可见性）**继续只用于 locate 派发**（带外 DOM 查询按可见 tab 路由，不受窗口前台影响，语义正确、不动）；新 `focused=hasFocus()` **仅供本前台检查**。两者独立字段、互不改写（§6.4）。
- 观测：`human_dom_status` 每 profile 项**加带 `focused` 字段**（可观测/排错）；操作循环用专用 `human_dom_focused`（单 profile 单布尔，更省）。

---

## 五、调用方约定（一等章节 · 供 AgentHub 同步成员说明书）

> 背景：`tap/tap_element/type_text/paste_text/press_key/swipe/move_mouse` 与 `human_dom_tap/human_dom_fill/vision_tap` **全是 OS 级动作、打在当时的前台窗口**。前台不是目标浏览器时，「ctrl+l→输网址→回车」就是往飞书发消息。成员**必须能在走错窗口时纠正，但不该例行抢**。

### 5.1 工具分栏

- **Class A — OS 级输入落前台窗口（点/写/移）**：`tap`/`tap_element`/`swipe`/`move_mouse`/`hover_preview`/`type_text`/`paste_text`/`press_key`/`human_dom_tap`/`human_dom_fill`/`vision_tap`。**动手前必须确保前台是目标浏览器**（错窗＝误点/数据错发；`hover_preview` 落 `moveTo` 到背景窗坐标会触发错误窗口的悬浮副作用——architect BLOCKING-3 补入）。
- **Class B1 — 探针（不要求任何窗口在前台）**：`take_screenshot`（整屏）、`current_app`（查当前前台是谁）。是**验证手段**、在不知前台是谁时用来查清 → **永远可先调**，不受「要在前台」约束。
- **Class B2 — 只读但要目标窗在前台可见**：`vision_locate`、`vision_locate_image`（在目标页里 OCR/模板匹配；前台错窗会识别错窗——architect BLOCKING-3 补入 `vision_locate_image`）。不写入、无错发风险，但结果失真 → 用前同样先探、不对才拉。
- **Class C — 带外 DOM，不碰屏幕/键盘**：`human_dom_locate`/`human_dom_status`/**`human_dom_focused`（新增，前台检查首选，§4.4）**，以及不带 `activate=True` 的 `human_browser_open`。**永不需要 activate**，浏览器在后台也安全。→ **前台检查的首选手段落在本栏**（带外布尔），Class B1 截图退为兜底。
- **允许动前台的口子**：`human_browser_open(profile=X, activate=True)`（首选，profile 确定性）；兜底 `focus_window`（**唯一真正改前台的工具**，配合只读的 `current_app` 探测使用，用于目标非 Chrome 时）。除这两条外任何工具都不主动改前台。

### 5.2 唯一操作循环（查 → 不对才拉；常态零 activate）——扩展为主、截图兜底

**前台检查首选走扩展带外查（Class C），而非截图目测**（StarBeam #188 用户方提、我方核实更优）：human_dom 扩展已 per-profile 注入页面在跑，让它顺带报 `document.hasFocus()`（§4.4/§6.4）→ 前台检查变成**确定性布尔、带外、无循环**（截图方案要"复核前先在最上"会绕出死循环；带外查天然打破它）。且 `hasFocus()` 比"窗口在前台"更准：**窗口在前台但用户切到别的标签/别的应用，键盘输入照样不进我们页面——`hasFocus()` 为 false、而现有 `active=!hidden` 与截图都看不出这个区别**（正是 #188"在别处打字被吞"那一刻，取证见 §6.4）。

```
每组 Class A/B2 动作的【组首】(及任何等待/重试/长操作后)必查:
  human_dom_focused(profile=X)             # Class C 带外, 又快又准(布尔)
  ├─ focused == true   → 直接操作, 不 activate                    ← 常态, 零抢焦点
  ├─ focused == false  → human_browser_open(profile=X, activate=True) → 复查 → 操作
  └─ focused == None   → 拿不到信号(扩展未连 / chrome:// 页 / 目标非 Chrome / server 未升级)
                       → 回落 take_screenshot(整屏, B1) 目测判前台 → 同上二分支
```

- **检查粒度（StarBeam 意见 2 采纳，判断权在落地方）＝按【组】非逐帧**：**无中断的连续动作视作一组、组首查一次；任何等待/重试/长耗时操作（上传、页面加载、跳页、sleep）之后必须重查**。理由：焦点只在有时间缝/异步操作时才漂走——紧邻的 `type_text`→`press_key("enter")`（几十 ms、无可插入干扰窗口）逐帧查一次带外 RPC 收益≈0，而**规则过密会压低成员执行率（"规则太密＝等于没有"，需求方反复吃过的亏）**。组首查已覆盖 #188 主场景（两次 run 之间 / 等待之后的漂移，正是数据错发风险点）；组内紧邻动作的残余漂移属 §5.3 已接受的不可消竞态。放宽的安全性由 §十 数据错发防线验收兜。
- **前台检查首选 = `human_dom_focused(profile=X)`（Class C 带外布尔）**；截图路径（B1）退为**兜底**（扩展局限见 §6.4），不再是首选。
- **首选拉前台动作 = `human_browser_open(profile=X, activate=True)`**：按 profile 确定性定位到**正确那一个** Chrome 窗口，复用路径廉价（不重启、不新开标签、url 省略即不导航）。成员不必自己判断切哪个窗。
- **兜底拉前台 = `current_app` + `focus_window`**：当目标非 Chrome 等 `human_browser_open` 不适用时的通用逃生口。
- 上述拉前台的两个是**唯一允许动前台**的口子（＝需求方三段式规则 3）。

### 5.3 竞态（已知残留，本期接受）

「探到前台正确 → 到真正动手」之间仍有缝，中途可能被通知/别的应用抢走。**两种顺序都有此缝**（先 activate 也一样：activate→查→动手中间照样有缝），消不掉；根治需 §八 的句柄级投递。故：选**常态不打扰**的「查→不对才拉」，并按 §5.2 的【组】粒度查（组首 + 任何等待/重试/长操作后重查、不复用旧结果）把窗口收窄到实际漂移风险点。逐帧查与组粒度都留同量级残余缝——选后者因其**成员执行率**远高（§5.2 意见 2）。

---

## 六、平台实现

### 6.1 Windows 非激活最大化（`win_input.py`）

- 现 `maximize_chrome_window_for_udd(udd)` 定位窗口后 `ShowWindow(h, SW_MAXIMIZE)`（激活）。
- 加 `activate` 形参，返回 `bool`（是否定位到窗口并生效）：
  - `activate=True`：保持 `ShowWindow(SW_MAXIMIZE)`（激活最大化）。
  - `activate=False`：**不走 ShowWindow**。取**目标窗口所在**显示器工作区——`MonitorFromWindow(h, MONITOR_DEFAULTTONEAREST)` → `GetMonitorInfo` 拿 `rcWork`（**architect BLOCKING-2b：绝不能照抄 `read_scale_factor` 的 `MonitorFromPoint(0,0, MONITOR_DEFAULTTOPRIMARY)` 恒取主屏**——那会把副屏上的 Chrome 一把搬到主屏，制造新打扰）——再 `SetWindowPos(h, HWND_TOP, rcWork.left, rcWork.top, w, h, SWP_NOACTIVATE)` 填满工作区。
  - **flag 订正（architect BLOCKING-2a）**：**去掉 `SWP_NOZORDER`**。`SWP_NOZORDER` 语义是「保持当前 Z 序、忽略 `hWndInsertAfter`」，与 `HWND_TOP` 同传会让 `HWND_TOP` 变死代码、窗口原地不动（若被别的窗挡住则 resize 后仍被挡，agent 截图判前台失真）。正解＝`HWND_TOP` 负责提到最前（可见）+ `SWP_NOACTIVATE` 单独负责不夺键盘焦点，二者不冲突，这是 Win32「提到最前但不激活」的标准写法。
  - 权衡：`SetWindowPos` 填工作区不置 `WS_MAXIMIZE` 状态位（还原按钮/贴靠语义与真最大化略异），但对「agent 按内容定位操作的全屏工作面」无碍。不使用 `SetWindowPlacement(SW_SHOWMAXIMIZED)`：`SW_SHOWMAXIMIZED==SW_MAXIMIZE==3`、**确定会激活**（不是「版本不一」，是确定激活），故排除。
- **best-effort 边界**：本函数在窗口**已存在**后调，能保证「不激活地最大化」；但 §2.1 冷启动**新进程自身**的一次性前台抢占发生在窗口出现之前、非本函数可控 → 记为可接受残留（真机量测其实际观感，验收项 §10）。不做「起进程前存 `GetForegroundWindow`、之后 `SetForegroundWindow` 还原」：受 Windows 前台锁限制、非持前台特权时多半只闪任务栏图标不真生效，投入产出比低（architect 认可不做）。

### 6.2 mac（`_human_browser.py`）

- 默认日常 profile 路径 `:368` `open -a "Google Chrome"`：`activate=False` 时加 `-g`（`open -g -a ...`）后台打开、不抢前台。
- 专用 profile 冷启 `:396` 直起二进制（带 `--user-data-dir`）：后台化需改 `open -g -n -a ... --args ...`，但会丢直连 Popen pid（削弱进程内复用探测，`_record_launch`/`_detect_reuse`）→ 成本大于收益，**本期保持直起、冷启动激活一次为可接受残留**（mac 非 #188 报障平台，且 mac 复用本就不抢）。
- mac 无 `foreground_fn`，复用路径本就 no-op，天然满足「复用零重激活」。

### 6.3 default-daily（无 profile）路径——【已知未闭环缺口，非一次性残留】

- **Windows `:373`**：`Popen([chrome, url])` 被 Chrome `ProcessSingleton` 转发给已跑的默认实例、**每次都自行 `SetForegroundWindow`**（§2.2b）。这**不是**我方 `foreground_fn` 或 `activate` 能压掉的（Chrome 自身行为、无 flag 可关）→ **本路径 `activate=False` 在 Windows 上无法兑现「不抢前台」**。诚实结论：**本期不修 Windows 默认路径**，返回 `note` 里显式提示「默认日常 Chrome 会被 Chrome 自身带到前台；需后台/不打扰运行请改用专用 profile」；`activated` 字段对该路径置 `None`（无法确定，不假称 False）。
- **mac `:368`**：`open -a` → `activate=False` 加 `-g`（`open -g -a ...`）可真后台打开，**mac 此路径能兑现**。→ 两平台不对称，如实文档化。
- **规避（与既有 SKILL 一致）**：SKILL 已把「无 profile = 日常 Chrome，仅一次性/非长期用」定为合法但受限用法；**recurring/后台 operator 必须用专用 profile**（§2.2b），走可受控的 `foreground_fn` 路径。此缺口不阻断 P0（P0 治的是专用 profile 复用路径的重激活，那条能确定性修好）。

### 6.4 扩展焦点上报（`content.js` + 桥 + `human_dom_focused`）——支撑 §5.2 首选检查

**取证（为何必须 `hasFocus()`、现有 `active` 不够）**：`content.js:72/84` 现只报 `active=!document.hidden`（可见性）。**用户切到别的应用**时——我们的窗口失去前台、但标签页仍"可见"未最小化——`document.hidden` **仍是 false → `active` 仍报 true**，但键盘输入已不进我们页面。`document.hasFocus()` 此时为 false，正确反映"输入会不会落进来"。这正是 #188"在别处打字被吞"那一刻，现有信号与截图都测不出。

**改动面（小、well-contained）**：
1. **`content.js`（+~5 行，两类帧必须分开——architect delta-BLOCKING-1）**：
   - **register/auth 首帧（`:71-72` `ws.onopen`）＝不动原对象、仅追加 `focused`**：
     `{type:"auth", token:TOKEN, profile_id:PROFILE_ID, tab_id:..., url:location.href, active:!document.hidden, focused:document.hasFocus()}`。
     **绝不替换成窄 payload**——桥 `make_ws_route`（`_bridge.py:101-121`）**不看 `type`、把第一帧原样**喂给 `register(ws, first.get("profile_id"), first.get("tab_id"), first.get("url"), ...)`；丢了 profile_id/tab_id/url 会让**所有 tab 登记成 "default"、摧毁按 profile 路由**（本部署 `token=""`、`check_auth` 恰放行 → bug 更隐蔽）。
   - **后续更新帧（`visibilitychange` `:83-84` + 新增 `window` 的 `focus`/`blur`）＝共用 `report()` 窄帧**：`ws.send({type:"active", active:!document.hidden, focused:document.hasFocus()})`。这些帧**不需带 profile_id 等**——`ws` 连接对象已在桥端标识是哪个 client。`visibilitychange` **不在切应用时触发**，必须靠 window focus/blur 让 `focused` 及时翻转（否则切应用后 `focused` 陈旧）。
   - 仍**只读、绝不改 DOM**（守 `content.js:1` 铁律）。
2. **桥 `_bridge.py`（+~8 行）**：`register(...)`/`make_ws_route` 读 `first.get("focused")`、`set_active` 读 `msg.get("focused")` → 存 `c["focused"]`；新增 `focus_state(profile_id)` 返回该 profile 活跃 client 的 `focused`（无连接 → `None`）。**不动 `_active`/`active` 的 locate 派发逻辑**（§4.4 严格分离）。
3. **`_human_dom.py`（+~15 行）**：注册 `human_dom_focused`（`resolve_profile_id` + `bridge.focus_state` + 组 `{ok,focused,profile,reason}`）；`human_dom_status` 每 profile 项带上 `focused`（观测）。

**诚实局限（不当银弹，需求方已列，回落截图兜底）**：
- ① 扩展只在 http/https 注入，`chrome://`/扩展页拿不到信号 → `focused=None`。
- ② 扩展会掉线（既有排错「定位不到先查扩展掉线」同理）→ 未连 → `focused=None`。
- ③ 目标非 Chrome（要操作桌面应用）完全不适用 → `focused=None`。
- ④ 多 frame：顶层 `document.hasFocus()` 在焦点落在子 iframe 内时也返回 true（含后代），对"窗口+tab 是否持焦点"的判断足够，不细分到 frame。
- ⑤ **【滚动升级期，architect delta-BLOCKING-3，非边缘】**：扩展是 **per-profile 预烤副本、只在冷启动按 `template_hash` 重烤**（`_ensure_human_dom_ext` 仅 `warm is None` 分支跑，`_human_browser.py:141-169/391`）。本次 content.js 升级上线时，**所有正跑着（warm）的 profile 仍是旧 content.js、不发 `focused` 字段**，直到各自下次冷启动才生效——这覆盖 §七 点名的**所有在跑的公众号/小红书 recurring profile**。此时 client 连着（`connected=true`）但 `c` 字典**无 `focused` 键**。→ **`focus_state` 实现必须用 `c.get("focused")`（无默认值）**，把「有 client 但无 `focused` 键」与「未连接」**同等对待返回 `None`**（回落截图）；**严禁 `c.get("focused", False)`（会把"旧扩展没上报"误判成"确定不聚焦"）或 `c["focused"]`（KeyError 崩）**。
  - **刷新到新扩展 = 该 profile 冷启动一次，但这【由 ops 侧择机做、绝不写进成员说明书】**（StarBeam 反转指正）：成员若照"重开浏览器拿焦点检查"做 = 又弹用户一次 = **正是 #188 本身**。成员侧只需容忍 `None`→截图兜底，别为拿焦点检查特意重开。
- ⑥ 多窗口同 profile（都可见、都 `active=true`）：`focus_state` 若沿用 `_active` 的"组内第一个 active"选择，选中的未必是真持 OS 焦点那个 → 可能报错窗的 `focused`。此为**既有选择逻辑的既有局限、非本次新引入**，本期文档化不改选择算法。
- ⑦ **【调用方版本先行，StarBeam 意见 1，跨仓上线大概率常态】**：成员说明书（新口径）先到、**设备端 agent-fleet server 尚未升级**时——`human_dom_focused` 是**根本不存在的工具**、`human_browser_open(activate=True)` 是**不认的参数**。这与 `focused=None` **失败形态不同**：是 **MCP 层直接报错**（工具未找到 / 参数不认），不是拿到 `None` 回落。→ **调用方须把「`None` / 工具不存在 / 调用报错」三者一视同仁**：一律回落截图兜底、别卡住别重试，不打断整个 run。（StarBeam 说明书已按此写；spec 侧登记以便双方口径与验收对齐。）根因：回填"只对新装/重装团队生效"、且**设备端 server 升级时点我方控制不了**（见早前 win-device/mac-device 严重滞后实例），"说明书先于 server 到位"是常态非边缘。
- 以上 `None`/工具不存在/调用报错 一律回落 §5.2 的 `take_screenshot` 兜底分支——扩展为主、截图不删。

---

## 七、兼容性与回归

- **默认语义变化**：`activate` 默认 False，改变了「open 即抢前台」的历史隐式行为。
- **⚠️ 修正 architect BLOCKING-5：原「ops 无回归」结论不成立、有数据错发风险**。取证：
  - ops 小红书/公众号发布走的正是 `human_dom_tap`/`human_dom_fill`（`using-human-dom/SKILL.md` 工作流），底层是**绝对屏幕坐标的 OS 级 tap + 全选粘贴填充**（`_do_fill:43-44`）＝本 spec §五 Class A。
  - 这类 recurring operator「固定 profile、跨 run 复用登录」场景在**旧行为下从没错窗**，靠的**正是每次 `human_browser_open` 复用都无条件重激活+最大化**——即本 spec 要拿掉的机制。
  - `using-human-browser/SKILL.md:44` 明写假设「**exclusive screen + input**（独占屏幕）」，且两份 SKILL 工作流**都没有「动手前查前台是不是目标浏览器」这一步**。拿掉自动激活后，若两 run 之间机器上有别的窗口在前台（用户主力机上常态），第二 run 的 `human_dom_fill` 会在**背景窗口**上全选+粘贴 → 落到别的应用，**正是 §1.3 要严防的「比抢焦点更糟的数据错发」**。
- **必做迁移动作（列入构建清单，不能只改 AgentHub 那份外部文档）**：
  1. 改**仓内第一方** `platforms/common/skills/using-human-browser/SKILL.md`（Workflow 节）与 `platforms/common/skills/using-human-dom/SKILL.md`（工作流节）：补 §5.2「每个 Class A/B2 动作前查前台（`human_dom_focused` 首选、截图兜底）、不对才拉」循环；修正 `:44`「exclusive screen」的独占假设（主力机上不成立）。
  2. §七显式登记：**warm-reuse operator 场景需迁移**为「先 `human_dom_focused` 查焦点（拿不到回落 `take_screenshot`）、不对才 `activate=True`」，而非笼统「无回归」。
- **扩展焦点上报是加法、不碰派发（但有前提，architect delta-BLOCKING-1 警示）**：新 `focused` 与既有 `active`（可见性、驱动 locate 派发）严格分离，locate/tap/fill 既有行为零改动 → 该项无回归——**前提是**：① register 首帧**保留完整字段**（不被折进窄 payload，§6.4 点 1，否则 profile 路由全毁）；② `set_active` 只**追加**存 `c["focused"]`、不动 `c["active"]`；③ `focus_state` 用 `c.get("focused")` 无默认（§6.4 局限⑤）。三条任一破 = 回归。§九分离守卫 + register 字段守卫兜。
- **不改** `--start-maximized`（`:82`）：只管几何、不额外激活，保留。
- 幂等复用/`_warm_navigate`/装扩展等逻辑不动。

---

## 八、已知残留与根治方向（本期不做，记录在案）

- **残留 1**：冷启动新进程一次性前台抢占（§6.1/6.2）——一次性、非主痛。
- **残留 2**：查→动手竞态缝（§5.3）。
- **缺口 3（architect BLOCKING-1，非一次性）**：Windows **无 profile/默认 Chrome** 路径的单例转发重激活（§2.2b/§6.3）——每次调用都被 Chrome 自身带前台、`activate` 管不到、本期不修。规避＝改用专用 profile。列此以便「修完仍偶发抢前台」时按此排查（先确认是不是走了无 profile 路径）。
- **根治方向**：所有 OS 级输入工具当前投给「当时的前台窗口」；根治应改为**投递到指定窗口句柄**（Windows：目标窗口 `PostMessage`/scoped 注入；mac：AX/CGEvent 定向）。届时「前台是谁」不再影响正确性，activate 降级为纯观感。此为架构级改动，另开需求评估。

---

## 九、测试策略（含 CI 盲区提醒）

> 提醒：本仓 CI 只跑 cli 测试，`platforms/common`、平台 server 的 pytest **不进 CI**（见 reference-agentfleet-ci-coverage-gap）；Win32/`open` 等 host-only 逻辑 Linux 无法 import。故审核靠本机 TDD 纯函数 + review gate + test-win11 真机。

- **本机可测（纯函数 / 分支选择，TDD 先行）**：
  - `_human_browser_open` 的冷/热 × activate 分派：注入假 `foreground_fn` 记录 `(udd, activate)` 调用序列，断言「复用+activate=False 零调用」「复用+activate=True 调 (udd,True)」「冷+False 调 (udd,False)」「冷+True 调 (udd,True)」。
  - **default-daily（无 profile）分支**：断言**不调 `foreground_fn`**、返回 `activated is None`、`maximized is False`、`note` 含「改用专用 profile」提示文案（architect 复验补：新扩围分支须有测试守卫）。
  - 返回值语义推导断言：专用 profile 路径 `maximized==acted`、`activated==(acted and activate)`；default-daily `activated is None`。
  - mac `open` 参数构造（`-g` 与否）纯函数化后断言。
  - **`human_dom_focused`（§4.4/§6.4）**：桥 `focus_state` 纯函数——连着且 `focused=true`→true、连着 `focused=false`→false、无连接→None；**连着但 client 字典无 `focused` 键（滚动升级期旧扩展）→ None 而非 False**（delta-BLOCKING-3 守卫，实现须 `c.get("focused")` 无默认）；`human_dom_focused` 组装 `resolve_profile_id`→`focus_state`→`{focused, reason}` 分支（含各 None 成因的 reason 分类）。
  - **`content.js` 焦点上报（node-vm，既有 human_dom 测试框架）**：`report()` 带 `focused` 字段；`focus`/`blur`/`visibilitychange` 三事件都触发 `report`；断言 `hasFocus()=false` 时 `focused=false`（模拟切应用：hidden 仍 false 但 hasFocus false → 现有 `active` 仍 true、`focused` 翻 false，守住 §6.4 取证的分叉）。
  - **register 首帧字段守卫（delta-BLOCKING-1 关键回归）**：断言 `ws.onopen` 首帧**仍含 `profile_id`/`tab_id`/`url`/`token`**（未被折进 `report()` 窄 payload），桥 `register` 拿到的 `profile_id` 是真值非 "default"。
  - **分离守卫（关键回归）**：断言新增 `focused` **不改** `_active`/locate 派发（`active` 语义与既有用例全绿）。
- **host-only（py_compile 兜 + test-win11 真机）**：`win_input` 的 `SetWindowPos(SWP_NOACTIVATE)` 分支、`GetMonitorInfo` 工作区。
- **回归守卫**：`_warm_navigate` 既有用例不回归；`activate` 缺省等价旧「不抢」预期；human_dom locate 派发不受 `focused` 影响。

---

## 十、真机验收 checklist（test-win11，专用测试机、不需用户物理在场）

**前置（否则白验，需求方提示）**：
- [ ] AgentHub 成员说明书**回填命令已跑**：`pnpm --filter @agenthub/db backfill-skill-bodies`（需连对应环境库；只对**新装/重装**团队生效，老团队工作区仍旧文档）。
- [ ] 验收所用成员工作区为**新装/重装**、确已拿到新版说明书。

**功能**：
- [ ] 复现 #188：旧行为下反复 `human_browser_open` 每次抢前台（基线）。
- [ ] 修后**常态零 activate**：`human_dom_focused` 探到 `focused=true` → 直接 Class A 操作，全程用户前台窗口焦点不被夺（观测：操作序列中前台句柄不变 / 用户输入不中断）。
- [ ] **扩展焦点检查对症（§6.4 取证的分叉）**：目标 tab 在前台 → `focused=true`；**切到别的应用**（窗口失前台但 tab 未最小化）→ `focused=false`（而旧 `active` 仍 true）；切到别的 tab → `focused=false`；`chrome://` 页 / 断开扩展 → `focused=None`。
- [ ] **截图兜底可用**：`focused=None` 时回落 `take_screenshot` 目测分支，走通「查→不对才拉」。
- [ ] **走错窗自救**：故意让前台为非 Chrome → `human_browser_open(profile=X, activate=True)` 能把该 profile 的 Chrome 确定性拉前台 → 复核后正确操作。
- [ ] `activate=True` 复用拉前台 + 最大化正确；`activate=False` 复用不动前台。
- [ ] 冷启动 `activate=False` 的一次性浮现观感量测（确认非「每动作抢」级别）。
- [ ] **仓内两份 SKILL.md 迁移已生效**（`using-human-browser`/`using-human-dom` 工作流已含「查前台→不对才拉」循环、`:44` 独占假设已修）。
- [ ] **warm-reuse 数据错发防线**（BLOCKING-5 核心项）：固定 profile、跨两次 run、**中途故意把别的窗口切到前台**，第二 run 的 `human_dom_fill` **不在背景窗误落字**（走查前台循环 → 探到不对 → activate=True 拉回再填）。这条替代原泛化的「ops 无回归」。
- [ ] **default-daily 已知缺口观测**（§6.3）：无 profile 路径返回 `activated is None`（非 False）、`note` 含「改用专用 profile」提示；确认该路径 Windows 抢前台**本期确实未修**、文档如实告知（不误判为回归）。
- [ ] **旧 server + 新说明书 版本先行**（§6.4 局限⑦，StarBeam 意见 1）：设备端跑**升级前**的 server + 成员用**新口径**说明书，调 `human_dom_focused`（工具不存在）/ `human_browser_open(activate=True)`（参数不认）时，是**可恢复的普通 MCP 报错**、成员能走回落截图分支继续，**不打断整个 run**（不卡死、不无脑重试）。
- [ ] **组粒度检查**（§5.2 意见 2）：连续 `type_text`→`press_key(enter)` 组只在组首查一次；上传/加载/跳页等待后**重查**生效；确认放宽后 warm-reuse 数据错发防线仍守住（即上一项在组粒度下不漏）。

---

## 十一、跨仓协同（与 AgentHub 同步点）

- 本 spec §五「调用方约定」是**唯一口径源**，同时驱动**两处文档**：
  - **仓内第一方 skill**（本仓落地、随本 spec 一起改、过文档 QA）：`using-human-browser/SKILL.md`、`using-human-dom/SKILL.md`（§七必做迁移 1）。
  - **AgentHub 成员说明书**（外部仓、需求方改）：`desktop/resources/skills/device-operate/SKILL.md`。
- 三份文档 + API **同版本对齐**：默认不抢 + 查→不对才拉 + `human_browser_open(activate=True)` 为首选拉前台动作。
- AgentHub 说明书改后须跑 §十 前置的回填命令（`pnpm --filter @agenthub/db backfill-skill-bodies`）方生效、且只对新装/重装团队生效。
- test-win11 一轮联合验收：「成员走错窗口能自救、平时不再抢焦点」，两仓同场。
