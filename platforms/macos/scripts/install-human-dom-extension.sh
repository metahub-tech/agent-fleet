#!/usr/bin/env bash
# install-human-dom-extension.sh
# 一次性把 human_dom Chrome 扩展装进真实 Chrome profile（开发者模式 Load unpacked）。
# 装好后本脚本写入标记 ~/.fleet/human-dom-ready，重连 mac-device 即启用 human_dom 工具。
#
# 用法：bash platforms/macos/scripts/install-human-dom-extension.sh
#       （在 agent-fleet repo 根目录执行，或用绝对路径）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
EXT_DIR="${REPO_ROOT}/platforms/common/capabilities/human_dom/extension"

echo "====================================================="
echo "  agent-fleet human_dom 扩展 — 一次性安装引导"
echo "====================================================="
echo ""
echo "扩展目录（Load unpacked 时选这个目录）："
echo "  ${EXT_DIR}"
echo ""
echo "步骤："
echo "  1. 打开真实 Chrome（你日常用的那个，带真实账号的 profile）"
echo "  2. 地址栏输入  chrome://extensions  并回车"
echo "  3. 右上角打开「开发者模式」(Developer mode) 开关"
echo "  4. 点击「加载已解压的扩展程序」(Load unpacked)"
echo "  5. 选择上面列出的扩展目录，点「选择」/「打开」"
echo "  6. 扩展列表里出现「agent-fleet human_dom locator」即安装成功"
echo ""
echo "注意："
echo "  - 扩展只读 DOM，绝不点击/修改页面，对网站完全透明。"
echo "  - 装好后该 Chrome profile 每次启动都会自动激活扩展，无需重复操作。"
echo "  - 若 mac-device server 端口非默认 8767，需先编辑 content.js"
echo "    里的 PORT 常量再 Load unpacked。"
echo ""

# 写安装标记（无论用户是否按引导操作，标记即认为已装好，重连后启用）
# 若希望严格等用户确认再写，可改成交互式询问；
# 目前采用「打印引导后即写标记」的无阻塞模式，与 server 静态判定对齐。
mkdir -p "${HOME}/.fleet"
touch "${HOME}/.fleet/human-dom-ready"

echo "已写入标记 ~/.fleet/human-dom-ready。"
echo "装好扩展后重连 mac-device（/mcp reconnect 或重启 server），human_dom 工具即可用。"
