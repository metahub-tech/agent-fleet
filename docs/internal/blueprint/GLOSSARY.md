# agent-fleet 术语表

> 术语 → 路径引用。`scripts/check-blueprint-refs.sh` 会校验下面所有反引号包裹的路径在仓库里确实存在；引用失效 = CI 红。

## 顶层概念

- **fleet（舰队）**：一组可被 agent 跨平台调用的真实物理设备（Windows/macOS/Linux/Android/iOS）。设计见 `docs/architecture.md`
- **platform bridge（平台桥）**：单一平台上的 MCP server，把该平台的 OS / app / 浏览器能力暴露给 agent。每平台一份，自包含。具体见 `docs/install-pattern.md`
- **universal tool set（通用工具集）**：跨平台同名同语义的工具（`take_screenshot` / `tap` / `launch_app` 等），让 agent 切设备只是换 URL。蓝图清单见 `docs/internal/blueprint/INTERFACE.md`
- **agent-host**：跑 agent 的本地宿主机；通过 `cli/` 提供的 `fleet` CLI 安装与编排各平台桥。入门见 `docs/agent-host-setup.md`

## 平台桥（6 件套）

每个 `platforms/<name>/` 目录的标准结构：

- `platform.toml` —— manifest（id / port / host_os / 启用的能力）。例 `platforms/windows/platform.toml`
- `README.md` —— 平台速查（工具表 / 端口 / 版本）。例 `platforms/windows/README.md`
- `server/` —— MCP server 源码（含 `*_mcp.py` 主入口 + requirements + tests）
- `scripts/` —— 该平台安装脚本（setup-<name>.<ext>）
- `skills/using-<name>/` —— 给 agent 用的 skill 文档
- `examples/` —— 参考配置（如 claude-settings.json）

## 设备能力分类

- **capability**：平台桥在 `platform.toml` 里声明的能力组（决定该平台 server 启用哪些工具集）。例如启用 `agent_browser` 就会暴露 `browser_navigate` / `browser_click` 等
- **agent_browser**：playwright-mcp 控制的 headless / 自动化浏览器；零身份，可隔离 profile
- **human_browser**：宿主真实日常浏览器；**无 debug 端口、无自动化标志**，"零自动化痕迹"。设计权衡见 `DECISIONS/`

## fleet 编排

- **lease（租约）**：多 agent 共享一台设备时的资源分配机制。`acquire` / `release` 工具配对使用
- **profile（浏览器 profile）**：agent_browser 的隔离 user-data-dir（一个设备可同时跑多个不同 cookie/session 的浏览器实例）

## 工程纪律

- **6 件套**：平台目录的固定结构（见上）
- **Universal Tool Set**：跨平台工具命名约定，详见 `CONTRIBUTING.md`
- **--check mode**：所有 generator 都支持 `--check` 仅校验不写文件，给 CI 用
- **ADR**：架构决策记录，append-only。见 `DECISIONS/`
