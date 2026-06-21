# agent-fleet 需求（来自 AgentHub device-op B0+B1）

> 接收方：agent-fleet 仓（本仓，独立项目）。
> 来源：AgentHub「通用设备操作能力」程序 B0+B1（AgentHub 仓 spec `docs/superpowers/specs/2026-06-21-device-op-B0-B1-detailed-design.md`）。
> 本副本由 AgentHub 侧同步落盘，便于本仓维护者查阅；canonical 版随 AgentHub 仓维护。请据此开 issue 跟踪实现。
> 用途：AgentHub 让数字团队的"操作员"agent（openclaw，跑在用户 Windows 机）通过挂载 agent-fleet 的设备 MCP，像人一样操作真实浏览器/桌面。本文件把对接所需的 agent-fleet 改动**需求化**，由 agent-fleet 并行实现；AgentHub 侧对接其产出。

## 实现状态（分支 `feat/agenthub-device-op-r1-r10`，2026-06-21）
| 需求 | 状态 | 说明 |
|---|---|---|
| R1 loopback 绑定 | ✅ 已实现 | `--host` / `FLEET_HOST`，默认仍 0.0.0.0 保持兼容，可传 127.0.0.1 |
| R9 端口可配 | ✅ 已实现 | `--port` / `FLEET_PORT`，默认 8766 |
| R7 bearer 鉴权 | ✅ 已实现 | `--token` / `FLEET_AUTH_TOKEN`，纯 ASGI 网关，空=过渡态放行 |
| R5 被父进程前台拉起 + health | ✅ 已实现 | `main()` 前台跑 + `GET /health` 免鉴权探活；拉起机制改为「从 checkout 跑 server venv」（见下方纠正 + `2026-06-21-device-op-server-launch.md`） |
| R10 最小权限 | ✅ 已确认 | loopback+用户级 venv+操作普通应用全程无需 admin（详见 launch doc） |
| R2 WSL 连通 | ⬜ 未做 | 非 native 首版必需 |
| R3 human_browser 持久 profile | ⬜ 未做 | Gate B 才需 |
| R4 回退约定 / R8 vision_locate | ⬜ 未做 | 非阻塞 |
| R6 GitHub 安装 | ⚠ 见纠正 | uvx 装子目录拿不到 common/，改为 clone checkout 跑 |

> 实现仅落 **windows** 平台 + 共享 helper `platforms/common/_server_runtime.py`；macos/android/ios 复用 helper 是后续各自 `__main__` 小改。

## 背景（agent-fleet 团队需知的对接拓扑）
- 用户机：AgentHub desktop（Electron）拉起 openclaw gateway + 操作员 agent；**openclaw 多数情形 native 跑在 Windows 本体**（实测 test-win11），少数 wsl 模式跑在 WSL2 内。
- agent-fleet 设备服务跑在 Windows 本体（操作真实浏览器/桌面/真账号）。
- **连通**：native 下 openclaw 与 agent-fleet 同 Windows 本体 → `127.0.0.1` 直通（主路径）；wsl 下 openclaw 在 WSL2 → 需经 Windows host IP 连（第二情形）。
- **挂载**：AgentHub 把 agent-fleet 的 MCP url 写进 openclaw.json 的 `mcp.servers.agenthub-device`（transport=streamable-http）。
- **由 AgentHub desktop 直接拉起+守护**（不依赖 Task Scheduler / Tailscale 向导）。

## 优先级总览
| 优先级 | 需求 | 用途 |
|---|---|---|
| **native 首版硬依赖** | R1 loopback 绑定 / R5 被 desktop 拉起 / R7 bearer 鉴权 / R9 端口可配 / R10 最小权限 | 没有这些 native 首版闭环跑不起来 |
| wsl 情形依赖 | R2 WSL2→Windows 连通 | 仅 wsl 模式需要 |
| 体验/降本（非阻塞） | R3 human_browser 持久 profile / R4 路径回退约定 / R8 vision_locate | 提升而非阻塞首版 |
| 已满足 | R6 GitHub 安装 | — |

---

## R1 — local-only / loopback 绑定（native 首版硬依赖）
- **要什么**：MCP server 支持绑 `127.0.0.1`（及可选指定 LAN 地址），不强制 `0.0.0.0`+Tailscale。
- **为什么**：native 下 openclaw 与设备服务同机，loopback 最安全（仅本机可达、不走防火墙、无需开端口/提权）。
- **现状**：硬编码 `host="0.0.0.0"`（`mcp.run(transport="http", host="0.0.0.0", port=...)`）。
- **验收**：启动参数/配置可选 `--host 127.0.0.1`（默认或可配）；绑 127.0.0.1 后仅本机进程可连。

## R5 — 被 AgentHub desktop 直接拉起 + 守护（native 首版硬依赖）
- **要什么**：一个可被外部程序（AgentHub desktop）直接 spawn 的运行模式——不依赖 Task Scheduler / launchd / Tailscale 安装向导；进程前台可被父进程管理（启停/重启/健康探测）。
- **为什么**：AgentHub desktop 用 `device-fleet-manager`（仿其管 openclaw gateway 的方式）拉起+守护 agent-fleet，随"装了设备能力的团队"存在而起、卸载则停。
- **现状**：Windows 走 Task Scheduler(AtLogOn) + 自带 restart loop；无被外部程序拉起的模式。
- **验收**：前台拉起一个可用 MCP server，接 `--host/--port/--token`；`GET /health` 可被父进程探活；父进程 kill 能干净停。✅ 已实现。
  - **拉起命令（纠正 uvx 假设）**：`<checkout>/platforms/windows/server/.venv/Scripts/python.exe <checkout>/platforms/windows/server/win_device_mcp.py --host 127.0.0.1 --port <P> --token <T>`。详见 `2026-06-21-device-op-server-launch.md`。

## R7 — MCP bearer 鉴权（native 首版硬依赖；用户明确要求提前）
- **要什么**：MCP server 校验请求头 `Authorization: Bearer <token>`；token 由启动方（AgentHub desktop）通过 `--token` 或环境变量（如 `FLEET_AUTH_TOKEN`）注入；不匹配的请求拒绝。
- **为什么**：即便 loopback 挡住远程，**本机其它进程/恶意软件也能连无鉴权 MCP、驱动用户真实浏览器和账号**——对操作真账号的工具是实打实风险。AgentHub desktop 生成 per-install/per-machine 随机密钥，启动 agent-fleet 时传入 + 注入 openclaw.json 的 device MCP headers。
- **机制可简化**：共享密钥即可（同一 desktop 两头写），不必 JWT/JWKS。
- **现状**：完全无鉴权（roadmap v1.0.0 规划 per-device bearer，未实现）。
- **验收**：带正确 Bearer 的请求通过、无/错 Bearer 的请求 401/拒绝；token 经 `--token`/env 注入、不硬编码。
- **回退**：若 R7 暂未交付，AgentHub 临时退到 native-loopback-无token（明确过渡态），但应尽快交付。

## R9 — 端口可配 `--port`（native 首版硬依赖；用户明确要求）
- **要什么**：监听端口可经 `--port` 配置（默认 8766）。
- **为什么**：8766 可能被占用；AgentHub desktop **从 8766 起扫空闲端口**动态分配（不杀占用进程），把选中端口经 `--port` 传入并写进 device MCP url。避免端口占用导致装不上。
- **现状**：硬编码 8766。
- **验收**：`--port 8770` 能让 server 监听 8770；不传则默认 8766。

## R10 — 最小权限运行（native 首版硬依赖；用户明确要求）
- **要什么**：普通用户态（非管理员/非 elevated）即可跑：loopback 绑定不需提权、依赖装在用户级（uv/Python user install）、操作普通（非 elevated）应用不需 admin。
- **为什么**：90% 是技术小白，弹 UAC 要管理员=摩擦+信任惊吓；最小权限本身更安全（操作账号的服务不该跑 admin）。仅"加防火墙规则（wsl/LAN）/操作 elevated 应用"才需提权——那是 AgentHub 侧条件提权处理，agent-fleet 本体应能非提权跑。
- **现状**：Task Scheduler 路径默认非提权，但需确认 loopback+用户态+操作普通应用全程不需 admin。
- **验收**：在非管理员账户下，loopback 绑定 + 操作普通浏览器（用户自己的 Chrome）全流程不触发 UAC/不需 admin。

---

## R2 — WSL2 → Windows 连通（wsl 情形依赖，native 不需）
- **要什么**：① server 可绑 WSL2 可达的 Windows host 地址（非仅 127.0.0.1）；② 文档化"从 WSL 探测 Windows host IP"的稳定方式（resolv.conf nameserver / ip route default gw / WSL2 mirrored 模式 127.0.0.1 直通）；③ Windows 防火墙放行 WSL 子网的指引。
- **为什么**：wsl 模式下 openclaw 在 WSL2、agent-fleet 在 Windows，127.0.0.1 跨网络栈不通。
- **现状**：完全不支持 WSL2 特殊网络栈。
- **验收**：WSL2 内的进程能经探测出的 Windows host IP:port 连到 agent-fleet；三方案至少一个稳定可用 + 文档。
- **优先级**：native 首版不需要，可在 native 闭环后做。

## R3 — human_browser 持久 profile（体验依赖，非首版阻塞）
- **要什么**：`human_browser_open` 支持 `--user-data-dir`（持久登录态），像 agent_browser 那样。
- **为什么**：真账号登录态保留；agent_browser 被判 bot 时回退 human_browser 仍保持登录。
- **现状**：human_browser 纯启动真实 Chrome，无 profile 控制（agent_browser 已有持久 profile）。
- **验收**：`human_browser_open` 可指定持久 profile，二次打开保留登录态。Gate B 验。

## R4 — agent_browser ↔ human_browser 回退约定（体验依赖，非首版阻塞）
- **要什么**：两路径切换/回退的明确约定（同 profile-key 互斥下，agent_browser 被判 bot → 回退 human_browser 同 profile）。
- **现状**：租约互斥机制（BrowserLeaseRegistry）已成熟，但无回退策略。
- **验收**：AgentHub 侧先做"显式切"（agent 读屏发现验证墙→主动切 human_browser）；agent-fleet 提供同 profile 切换不丢登录态的保证。"自动检测降级"留后续。

## R8 — vision_locate / vision_tap（降本提稳，非阻塞）
- **要什么**：OCR/模板离线定位工具（设计稿已有），0 LLM、纯 CPU，返回坐标。
- **为什么**：操作员"视觉脑"每步读屏=多模态调用（成本/延迟）；离线定位可加速、降本、提稳（结构化定位之外的图形元素）。
- **现状**：设计稿（`docs/internal/design/2026-06-04-vision-localization-capability.md`），未实现。
- **验收**：`vision_locate(query)`/`vision_tap(query)` 返回/点中坐标，与 `tap` 同坐标空间。非阻塞（B0 视觉脑可兜底）。

## R6 — 安装走 GitHub（纠正：clone checkout，非 uvx 装子目录）
- **原设想**：`uvx --from "git+...#subdirectory=platforms/windows/server" <entry>`。**不通**——server 运行时靠 `sys.path.insert(.../common)` 引用 `platforms/common`，装单个子目录拿不到 `common/`。
- **实际机制**：AgentHub desktop **clone/pull 一份完整 agent-fleet checkout**，在 `platforms/windows/server/` 建 `.venv` 并 `pip install .`（拉齐依赖），前台跑 `win_device_mcp.py`（`common/` 从 checkout 同级解析）。详见 `2026-06-21-device-op-server-launch.md`。
- **后续可选**：把 `common` 拆成可安装包让 server 依赖之 + 改绝对 import，才能真正 standalone uvx 一行装；改动面大，非首版必需，独立项。

---

## 对接契约（AgentHub 侧已据此设计，agent-fleet 实现时对齐）
- **挂载**：openclaw.json `mcp.servers.agenthub-device = { transport:"streamable-http", url:"http://<host>:<port>/mcp", headers:{ Authorization:"Bearer <token>" } }`。
- **启动**：AgentHub desktop 从 checkout spawn `<server .venv python> win_device_mcp.py --host 127.0.0.1 --port <动态空闲端口> --token <per-install 密钥>`（或经 env `FLEET_HOST/FLEET_PORT/FLEET_AUTH_TOKEN`）。**非** uvx 装子目录（见 R6 纠正）。
- **健康**：提供可探测的健康信号（HTTP 端点或 MCP ping）供 desktop 装后自检。
- **工具**：openclaw 操作员经此 MCP 调 `take_screenshot`/`browser_*`(agent_browser)/`human_browser_open`/`tap`/`type_text`/`find_elements`/`tap_element` 等（现有 71 工具够首版；R8 加 vision_locate 提升）。
