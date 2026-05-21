# macOS Platform Bridge

macOS device-host bridge for `agent-fleet`. Enables LLM agents to drive a Mac for CLI/GUI test automation over Tailscale + MCP.

Mirrors the Windows bridge architecture (FastMCP server, streamable-http on Tailscale, advisory acquire/release state model). Integration on Mac is actually simpler than Windows because launchd does the restart-on-crash work in-kernel.

## Quick Start

完整手册：[`../../docs/platforms/macos.md`](../../docs/platforms/macos.md)。

TL;DR (Mac terminal):

```bash
# 1. Install Tailscale (brew cask) + login via menubar
brew install --cask tailscale

# 2. Get the code
git clone https://github.com/metahub-tech/agent-fleet.git ~/agent-fleet
cd ~/agent-fleet

# 3. Setup
bash platforms/macos/scripts/setup-macos.sh

# 4. Grant macOS permissions (one-time, manual):
#    System Settings > Privacy & Security > Accessibility    -> add venv python
#    System Settings > Privacy & Security > Screen Recording -> add venv python
#    System Settings > Privacy & Security > Automation       -> tick System Events
```

Agent 端配置见 [`../../docs/agent-host-setup.md`](../../docs/agent-host-setup.md)。

## Demo — example agent session

```text
You:   "Run the test suite, then open Safari and screenshot it."
Agent: run_zsh(script="cd ~/proj && pytest -q")        → 96 passed in 4.1s
       open_app(app="Safari")                          → frontmost
       take_screenshot()                               → agent verifies the screen
```

GUI automation + shell on a real Mac, through one unified MCP tool interface.
See the animated demo (a real iPad) in the [main README](../../README.md).

## 暴露的工具

`mac-device` MCP server (FastMCP, native multi-client) 通过 streamable-http 监听 `0.0.0.0:8767/mcp`：

| 类别 | 工具 |
|---|---|
| **使用状态** | `acquire_mac`, `release_mac`, `get_mac_status` |
| 屏幕 | `get_screen_size`, `take_screenshot` |
| 鼠标 | `click`, `move_mouse` |
| 键盘 | `type_text`, `paste_text`, `press_key` (cmd / option / shift / ctrl) |
| 进程（一次性） | `open_app` (uses `open -a`), `kill_process`, `list_processes` |
| 长时进程 | `start_process`, `read_process_output`, `interact_with_process`, `force_terminate`, `list_sessions` |
| 文件系统 | `read_file`, `write_file`, `edit_block`, `list_directory`, `create_directory`, `move_file`, `get_file_info` |
| 文件搜索 | `start_search`, `get_more_search_results`, `list_searches`, `stop_search` |
| Shell | `run_zsh`, `run_applescript` |

> **与 Windows win-device 的差异**：
> - 没有 `list_windows` / `inspect_window` / `focus_window`（Windows 用 pywinauto，macOS 等价物用 AppleScript / NSAccessibility，v0.3.0 暂未实现，可通过 `run_applescript` 间接达成）
> - `launch_app` → `open_app`（macOS 习惯用 `open -a`）
> - `run_powershell` → `run_zsh` + 新增 `run_applescript`
> - `press_key` 支持 `cmd` / `option` 别名（pyautogui 的 `command` / `option`）

## 目录布局

```
platforms/macos/
├── README.md                     # 本文件
├── server/                       # MCP server 源码 + 依赖
│   ├── mac_device_mcp.py
│   ├── requirements.txt
│   └── pyproject.toml
├── scripts/                      # 一键安装 + launcher
│   ├── setup-macos.sh
│   └── _launch-mac-device.sh
└── skills/
    └── using-mac/SKILL.md     # 给 agent 的使用规则
```

## 运行依赖

| 组件 | 必须 | 用途 | 自动安装 |
|---|---|---|---|
| Tailscale | ✅ | 跨网组网 | 用户在第 1 步装（brew cask） |
| Python 3.10+ | ✅ | 跑 mac_device_mcp.py | setup-macos.sh 自动装（brew） |
| Homebrew | ✅ | 装 Tailscale + Python | setup 检测，缺则提示装 |
| GUI 权限授权 | ✅ | 鼠标 / 键盘 / 截屏 / AppleScript | **手动**在系统设置中授权（一次性） |
| 用户已登录 | ✅ | launchd LaunchAgent 在用户登录时启动 | 设备一直开着即可（你的部署形态） |

## 故障排查

完整排错章节见 [`../../docs/platforms/macos.md` § 7](../../docs/platforms/macos.md)。常见：

- 端口 8767 没监听：`tail platforms/macos/logs/mac-device.log` 看 traceback
- 鼠标点击没反应 / 截图全黑：权限没给（看 setup 末尾打印的清单）
- AppleScript 报"-1743 not allowed"：Automation 权限里缺该 app 勾选

## License

Apache 2.0 — 见 [`LICENSE`](../../LICENSE)。
