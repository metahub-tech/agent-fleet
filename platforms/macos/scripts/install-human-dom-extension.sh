#!/usr/bin/env bash
# install-human-dom-extension.sh
# 一次性把 human_dom Chrome 扩展装进真实 Chrome profile（开发者模式 Load unpacked）。
#
# 与早期版本不同：现在按 profile 路由。每个 profile 生成一份独立的扩展副本，
# 副本里烤入了该 profile 对应的桥端口（PORT）和 profile_id，互不串扰。
# 安装目标目录：~/.fleet/human-dom-ext/<profile_id>/
#
# 用法：
#   bash platforms/macos/scripts/install-human-dom-extension.sh            # 默认日常 Chrome（profile_id=default）
#   bash platforms/macos/scripts/install-human-dom-extension.sh "<PROFILE>" # 指定专用 profile（传 profile 串）
#   bash platforms/macos/scripts/install-human-dom-extension.sh "<PROFILE>" <MCP_PORT> # 指定 profile + 非默认 mcp_port
#       （在 agent-fleet repo 根目录执行，或用绝对路径；PROFILE 串与 human_dom_locate 的 profile 参数一致）
#       第 2 个参数 MCP_PORT 可选，默认 8767；若 server 以非默认 --port 启动，传对应 mcp_port，
#       本脚本才会读对的 portfile（并把对的桥端口烤进副本）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
COMMON_DIR="${REPO_ROOT}/platforms/common"

# 可选参数：要安装到的 profile 串（默认空 = 默认日常 Chrome）。
PROFILE="${1:-}"

# mac server 默认 mcp_port（与 Task 9 server 的 default_port 对齐）；桥端口回退 = mcp_port + 13。
# 第 2 位置参数可覆盖：若 server 以非默认 --port 启动，传对应 mcp_port 才能读对 portfile。
MCP_PORT="${2:-8767}"
PORTFILE="${HOME}/.fleet/dom-bridge-${MCP_PORT}.port"

# 1. 算 profile_id（""→"default"），install 与 locate 共用同一套规范化逻辑。
PROFILE_ID="$(python3 -c "import sys; sys.path.insert(0, sys.argv[2]); from capabilities.human_dom._ident import human_dom_profile_id; print(human_dom_profile_id(sys.argv[1]))" "${PROFILE}" "${COMMON_DIR}")"

# 2. 算 bridge_port：优先读 server 启动时持久化的端口文件；文件不存在或内容非法
#    （如 server 崩溃写了半截）则回退 mcp_port + 13。
BRIDGE_PORT=$((MCP_PORT + 13))
if [[ -f "${PORTFILE}" ]]; then
  _raw="$(cat "${PORTFILE}")"
  if [[ "${_raw}" =~ ^[0-9]+$ ]]; then
    BRIDGE_PORT="${_raw}"
  fi
fi

EXT_OUT="${HOME}/.fleet/human-dom-ext/${PROFILE_ID}"

echo "====================================================="
echo "  agent-fleet human_dom 扩展 — 按 profile 安装引导"
echo "====================================================="
echo ""
echo "目标 profile  : ${PROFILE:-（默认日常 Chrome）}"
echo "profile_id    : ${PROFILE_ID}"
echo "桥端口 (PORT) : ${BRIDGE_PORT}"
echo ""

# 3. 生成该 profile 专属的扩展副本（烤入 PORT + profile_id + 写 meta.json）。
python3 -c "import sys; sys.path.insert(0, sys.argv[4]); from capabilities.human_dom._setup import prepare_extension; print(prepare_extension(sys.argv[1], int(sys.argv[2]), sys.argv[3]))" \
  "${EXT_OUT}" "${BRIDGE_PORT}" "${PROFILE_ID}" "${COMMON_DIR}" >/dev/null

echo "扩展目录已生成（Load unpacked 时选这个目录）："
echo "  ${EXT_OUT}"
echo ""
echo "步骤："
echo "  1. 打开目标 Chrome profile（要让 human_dom 操控的那个 profile）"
echo "  2. 地址栏输入  chrome://extensions  并回车"
echo "  3. 右上角打开「开发者模式」(Developer mode) 开关"
echo "  4. 点击「加载已解压的扩展程序」(Load unpacked)"
echo "  5. 选择上面列出的扩展目录，点「选择」/「打开」"
echo "  6. 扩展列表里出现「agent-fleet human_dom locator」即安装成功"
echo ""
echo "注意："
echo "  - 扩展只读 DOM，绝不点击/修改页面，对网站完全透明。"
echo "  - PORT 与 profile_id 已烤入该副本，无需手改 content.js。"
echo "  - 装好后该 Chrome profile 每次启动都会自动激活扩展，无需重复操作。"
echo ""

# 在 Finder 里打开扩展目录，方便选目录（非交互/无 GUI 环境允许失败）。
open "${EXT_OUT}" 2>/dev/null || true

# 写全局标记（保留兼容：server 端静态判定 human_dom 是否已引导过）。
mkdir -p "${HOME}/.fleet"
touch "${HOME}/.fleet/human-dom-ready"

echo "已写入标记 ~/.fleet/human-dom-ready。"
echo ""
echo "装好扩展后："
echo "  - 重连 mac-device（/mcp reconnect 或重启 server），human_dom 工具即可用。"
echo "  - 多 profile：对每个 profile 各自重跑本步，把 PROFILE 参数传成对应 profile 串，"
echo "    例如：bash platforms/macos/scripts/install-human-dom-extension.sh \"<其它 PROFILE>\""
