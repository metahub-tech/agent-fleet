# 设备 server 的父进程拉起契约（AgentHub device-op 对接）

> 对应需求：`docs/2026-06-21-requirements-from-agenthub-device-op.md` 的 R1/R5/R7/R9/R10。
> 实现分支：`feat/agenthub-device-op-r1-r10`。本文档说明 AgentHub desktop（或任意父进程）如何把 windows 设备 server 当受管子进程拉起。

## 启动命令

server 现在接受三个参数（均带环境变量回退）：

| 参数 | 环境变量 | 默认 | 作用 |
|---|---|---|---|
| `--host` | `FLEET_HOST` | `0.0.0.0` | 绑定地址。传 `127.0.0.1` = 仅本机可达（loopback），无需防火墙/开端口/提权 |
| `--port` | `FLEET_PORT` | `8766` | 监听端口。父进程可先扫空闲端口再传入，避开占用 |
| `--token` | `FLEET_AUTH_TOKEN` | （空） | 共享密钥 bearer。设置后除 `GET /health` 外每个请求都要带 `Authorization: Bearer <token>`；空 = 不鉴权（过渡态） |

优先级：命令行 > 环境变量 > 内置默认。

**典型父进程拉起（loopback + 端口 + 鉴权）：**

```
<checkout>/platforms/windows/server/.venv/Scripts/python.exe \
    <checkout>/platforms/windows/server/win_device_mcp.py \
    --host 127.0.0.1 --port <空闲端口> --token <per-install 密钥>
```

env 注入等价：`FLEET_HOST=127.0.0.1 FLEET_PORT=<P> FLEET_AUTH_TOKEN=<密钥>`。

server 前台运行、stdout/stderr 行缓冲（日志实时），父进程 kill 即干净停止。MCP 端点 `http://<host>:<port>/mcp`（streamable-http）。

## 健康探测（R5）

`GET http://<host>:<port>/health` → `200 {"status":"ok"}`，**不需鉴权**（即使配了 token 也豁免）。父进程装好后用它确认 server 起来了再路由 MCP 流量。

## 为什么是「从 checkout 跑」而非「uvx 装子目录」（重要纠正）

需求文档原先设想 `uvx --from "git+...#subdirectory=platforms/windows/server" <entry>`。**这条路不通**：windows server 运行时靠 `sys.path.insert(.../common)` 引用 `platforms/common`（`_fsops`/`_device_state`/`capabilities`/`_server_runtime` 等），而 `#subdirectory=platforms/windows/server` 只装 server 子目录，拿不到 `common/`。

因此父进程拉起的可靠机制 = **从一份完整 checkout 跑 server 的 `.venv` python**（正是现有 Task Scheduler 模型，只是去掉 Task Scheduler 壳、改前台 + 传参）：
- desktop 准备一份 agent-fleet checkout（clone/pull）；
- 用现有 `setup-windows.ps1`（或等价：在 `platforms/windows/server/` 建 `.venv` 并 `pip install .`，会拉齐 fastmcp/starlette/pyautogui/pywinauto 等依赖）；
- 前台 spawn 上面的命令，`common/` 从 checkout 同级解析。

> **后续可选**：若要真正的「standalone uvx 一行装」，需把 `common` 拆成可安装包（如 `agent-fleet-common`）并让各平台 server 依赖它 + 改绝对 import。改动面大且影响全平台，非 device-op 首版必需，留作独立项。

## R10 最小权限确认

非管理员账户下全程不需 admin / 不弹 UAC：
- **loopback 绑定** `127.0.0.1` 不需要 Windows 防火墙规则、不开端口、不提权；
- **依赖用户级**：`.venv` 装在用户可写目录，uv/pip user install，无系统级写入；
- **操作普通应用**：驱动用户自己的 Chrome 等非 elevated 应用不需 admin。

仅以下才需提权——且属 AgentHub 侧条件处理、非 server 本体职责：
- 给 WSL/局域网放行加 Windows 防火墙规则（仅 wsl/LAN 场景，R2）；
- 操作以管理员身份运行的 elevated 应用（同权级才能驱动）。

## 实现要点（给 reviewer / 维护者）

- 共享 helper：`platforms/common/_server_runtime.py`（`parse_server_args` / `BearerAuthMiddleware` / `auth_middleware` / `register_health_route` / `serve`）。多平台 server 可复用同一套。
- bearer 网关是**纯 ASGI 中间件**（非 `BaseHTTPMiddleware`）：只看请求 scope，要么短路 401、要么原样透传，**不缓冲响应体** → 不破坏 streamable-http 的长任务流式（当年专门从 SSE 迁过来的原因）。token 比对用 `hmac.compare_digest` 防时序泄漏。
- windows server `__main__` 收敛为 `main()` → `_server_runtime.serve(mcp, prog="agent-fleet-win", default_port=8766)`。
- 测试：`platforms/common/tests/test_server_runtime.py`（12 例，参数优先级 + 网关放行/401/health 豁免/无 token 过渡态，纯 stdlib 驱动 async）。另有最小 FastMCP + httpx ASGITransport 端到端验证（health 免鉴权可达、/mcp 无错 token 401、对 token 放行）。
- 仅改 windows 平台；macos/android/ios 复用 helper 是后续小改（各自 `__main__` 照搬即可），本批未动。
