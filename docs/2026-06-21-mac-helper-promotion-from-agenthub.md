# agent-fleet 需求：把受管拉起 helper 推广到 macOS 桥

> 接收方：agent-fleet 仓（独立项目）。**执行方式**：按 AgentHub 章程，agent-fleet 改动**走 tmux 让 agent-fleet 自己的 agent 实现**，AgentHub 不直接编辑 agent-fleet 代码——本文件即交给它的需求。
> 来源：AgentHub device-op。windows 桥已通过 PR #58 合入 agent-fleet `main`（commit a07327f3），采用共享 helper `platforms/common/_server_runtime.py` 实现「父进程受管拉起」（`--host/--port/--token` + `/health` + bearer 鉴权）。本需求把**同一套**推广到 **macOS 桥**。
> **本期范围**：仅 macOS。**iOS / Android 本期不碰**（后续单独需求）。

## 目标
让 `platforms/macos/server/mac_device_mcp.py` 像 windows 桥一样接入 `_server_runtime`，使 macOS 设备 server 可被父进程（AgentHub desktop）当受管子进程拉起：可配 bind host / 端口 / 共享密钥 bearer，并暴露免鉴权 `/health` 探活。

## 唯一参考模板（照抄改法即可）
**main 上的 windows 桥就是已验证模板**，逐项对照改 macOS 即可：
- `platforms/windows/server/win_device_mcp.py`：看它顶部 `import _server_runtime` 与末尾 `main()` → `_server_runtime.serve(mcp, prog="agent-fleet-win", default_port=8766)` 的写法。
- `platforms/windows/server/pyproject.toml`：看它 `fastmcp` 下界与 `starlette` 依赖。
- `platforms/common/_server_runtime.py`：共享 helper，已含 `serve()`（已在 review 中补回 `reconfigure(line_buffering=True)`，故各平台 `main()` **不必**自己再 reconfigure）。

## 改动清单（macOS）

### M1 — mac_device_mcp.py 接入 helper
- 顶部 `sys.path.insert(0, .../common)` 之后（约现 L51-52，与 `import _fsops, _proc, _search` 同处）加 `import _server_runtime`。
- 末尾 `if __name__ == "__main__":` 块（现 L1104-1125：`reconfigure(line_buffering=True)` + `mcp.run(transport="http", host="0.0.0.0", port=8767)`）收敛为：
  ```python
  def main() -> None:
      _server_runtime.serve(mcp, prog="agent-fleet-mac", default_port=8767)

  if __name__ == "__main__":
      main()
  ```
  - **默认端口保持 8767**（macOS 桥原值，勿改成 8766）。
  - 原 `reconfigure(line_buffering=True)` 由 `serve()` 统一做，**不要**在 mac main() 里重复（与 windows 一致）。
  - **main() docstring 若写端口，写 8767**，host/transport 文案沿用 mac 原 `__main__` 注释（现 L1111-1124）；**别照搬 windows main() docstring 里的 8766**（那是 windows 专属、会自相矛盾）。
  - 模块**顶层** docstring（现 L11 "Transport: streamable-http on 0.0.0.0:8767/mcp"）**保持不动**——与 windows 接入时未改顶层 docstring 一致（host 接入后可配但默认仍 0.0.0.0，不必改文案）。

### M2 — pyproject.toml 依赖
`platforms/macos/server/pyproject.toml` 的 `dependencies`：
- `fastmcp>=2.0,!=3.3.1` → **`fastmcp>=2.3.2,!=3.3.1`**（`http_app(middleware=)` 自 2.3.2 才有，低于会启动崩——与 windows review 修复 ①一致）。
- 加 **`starlette>=0.37`**（helper 直接 import starlette；虽 fastmcp 传递依赖，显式声明更稳）。
- macOS 专属依赖（pyobjc 等）与 `py-modules = ["mac_device_mcp"]` 保持不变。

### M3 — 集成测试（鉴权真接进 app，**平台无关·CI 可跑·windows/mac 共用一份**）
仿 windows review 补的那条，但**做成平台无关的共享测试文件**（如 `platforms/common/tests/test_server_app_integration.py`），而不是塞进只在 mac 上跑的 `test_mac_server.py`：
- 用最小 `FastMCP()` + `register_health_route` + `mcp.http_app(transport="http", middleware=auth_middleware("<token>"))` + `httpx.ASGITransport` 跑断言，**不 import pyautogui/pyobjc/pywinauto**（故 Linux CI 也能跑、windows/mac 共用一份）：
  - `GET /health` 免鉴权 → 200 `{"status":"ok"}`
  - `/mcp` 无 token → 401；错 token → 401；对 token → 非 401（过网关）
  - 无 token 配置时整链放行（过渡态）
- 注：`platforms/common/tests/test_server_runtime.py` 已覆盖 helper 纯逻辑（参数优先级 + ASGI gate + 跨族端口探测回归）；本条侧重「鉴权真接进了 app（`mcp.http_app(middleware=)` 真生效）、不是空摆设」。windows review 那条实测逻辑可直接迁过来共用。

### M4 — 启动/守护脚本（确认即可，多半无需改）
- macOS 走 `platforms/macos/scripts/_launch-mac-device.sh`（launchd）。**确认**：① 直接前台跑 `<server .venv/bin/python3> mac_device_mcp.py` 仍可用（AgentHub desktop 走 checkout-run = clone + 建 mac venv + 跑这个 python，与 windows 同模型）；② 若希望 launchd 路径也支持 token，可让脚本透传 `--host/--port/--token` 或 env `FLEET_*`（可选，非阻塞）。
- 不需要加 `[project.scripts]` 控制台入口（与 windows 一致：server 靠 checkout 布局引用 `common/`，standalone 入口拿不到 common；拉起 = 从 checkout 跑 .py）。

## 验收（macOS，对齐 windows R1/R5/R7/R9/R10）
- **R1 loopback**：`--host 127.0.0.1`（默认 0.0.0.0 兼容）；绑 127.0.0.1 后仅本机可连。
- **R9 端口可配**：`--port 8770` 生效；不传默认 **8767**。
- **R7 bearer**：`--token` / `FLEET_AUTH_TOKEN`；无/错 token → 401，对 token 放行，`/health` 豁免；空 token = 过渡态放行。
- **R5 前台拉起 + health**：`<.venv/bin/python3> mac_device_mcp.py --host 127.0.0.1 --port <P> --token <T>` 前台起；`GET /health` 200；父进程 kill 干净停；stdio 行缓冲（serve 已做）。
- **R10 最小权限**：普通用户态、loopback 不需提权（macOS 上注意：首次操作可能触发"辅助功能/屏幕录制"授权，那是 macOS 系统授权，属用户一次性授予，非提权——如实记录即可）。
- 既有 macOS 工具（browser_*/run_applescript/take_screenshot 等）不受影响。

## 不在本需求范围（避免误做）
- **iOS / Android 桥**：本期不碰。
- **AgentHub desktop 侧 macOS 支持**：device-fleet-manager 目前 windows-only（venv 路径 `.venv\Scripts\python.exe`、serverDir 指 windows/server、runtimeMode 判定）。让 AgentHub desktop 能在 mac 上拉起 macOS 桥，是 **AgentHub 仓自己的后续任务**（由 agenthub agent 直接做），不在 agent-fleet 本需求内。本需求只保证 macOS **server 端**接好 helper、接受参数、暴露 /health + 鉴权。

## 对接契约（与 windows 同款）
- 挂载：openclaw.json `mcp.servers.agenthub-device = { transport:"streamable-http", url:"http://127.0.0.1:<port>/mcp", headers:{ Authorization:"Bearer <token>" } }`。
- 启动：`<checkout>/platforms/macos/server/.venv/bin/python3 <checkout>/platforms/macos/server/mac_device_mcp.py --host 127.0.0.1 --port <空闲端口> --token <per-install 密钥>`（或 env `FLEET_HOST/FLEET_PORT/FLEET_AUTH_TOKEN`）。
- 健康：`GET /health` → 200 `{"status":"ok"}`。
