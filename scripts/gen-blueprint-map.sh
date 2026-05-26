#!/usr/bin/env bash
# gen-blueprint-map.sh
#
# 自动从代码生成项目蓝图：MAP.md（模块地图）
# 用法：
#   ./scripts/gen-blueprint-map.sh           # 写入文件
#   ./scripts/gen-blueprint-map.sh --check   # 仅校验，若与代码不同步则 exit 1
#
# 设计：输出必须是 deterministic（无时间戳、文件列表 sort），便于 CI --check 用 diff 判定。

set -euo pipefail

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

OUT="docs/internal/blueprint/MAP.md"
TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

{
  echo "# Project MAP（自动生成 · 请勿手编）"
  echo ""
  echo "_由 \`scripts/gen-blueprint-map.sh\` 从代码自动生成。改完代码后跑这个脚本同步；CI 用 \`--check\` 模式把门。_"
  echo ""

  echo "## platforms/"
  echo ""
  for d in $(ls -d platforms/*/ 2>/dev/null | sort); do
    p="$(basename "${d}")"
    case "${p}" in
      common|tests) continue ;;
    esac
    echo "### ${p}"
    echo ""
    if [ -f "${d}README.md" ]; then
      # 抓 README 第一行（含 # 标题）作为一句话描述
      one=$(head -1 "${d}README.md" | sed 's/^#*[[:space:]]*//')
      echo "${one}"
      echo ""
    fi
    echo "**关键文件**："
    for f in "${d}platform.toml" "${d}README.md"; do
      [ -f "${f}" ] && echo "- \`${f}\`"
    done
    for f in $(ls "${d}server/"*_mcp.py 2>/dev/null | sort); do
      echo "- \`${f}\` _(MCP server 主入口)_"
    done
    if [ -d "${d}skills" ]; then
      for sd in $(ls -d "${d}skills/"*/ 2>/dev/null | sort); do
        echo "- \`${sd}\` _(skill 文档)_"
      done
    fi
    echo ""
  done

  echo "## cli/"
  echo ""
  if [ -f cli/README.md ]; then
    head -1 cli/README.md | sed 's/^#*[[:space:]]*//'
    echo ""
  fi
  echo "**关键模块**："
  for f in $(find cli/src -name '*.py' ! -name '__init__.py' 2>/dev/null | sort); do
    echo "- \`${f}\`"
  done
  echo ""

  echo "## scripts/"
  echo ""
  echo "**仓库级运维脚本**："
  for f in $(find scripts -maxdepth 1 \( -name '*.sh' -o -name '*.py' \) 2>/dev/null | sort); do
    desc=$(head -3 "${f}" | grep -m1 '^#[^!]' | sed 's/^#[[:space:]]*//' || true)
    echo "- \`${f}\`${desc:+ — ${desc}}"
  done
  echo ""

  echo "## docs/"
  echo ""
  echo "**共享设计/上手文档**："
  for f in $(find docs -maxdepth 1 -name '*.md' 2>/dev/null | sort); do
    echo "- \`${f}\`"
  done
  echo "- \`docs/platforms/\` _(各平台 setup guide)_"
  echo ""
} > "${TMP}"

if [ "${CHECK}" = "1" ]; then
  if ! diff -q "${OUT}" "${TMP}" >/dev/null 2>&1; then
    echo "❌ ${OUT} 与代码现状不同步" >&2
    echo "请跑 \`./scripts/gen-blueprint-map.sh\` 后重新提交（蓝图维护 SOP）" >&2
    echo "--- 期望（基于代码） vs 当前文件 ---" >&2
    diff "${OUT}" "${TMP}" >&2 || true
    exit 1
  fi
  echo "✓ ${OUT} 与代码同步"
else
  mkdir -p "$(dirname "${OUT}")"
  cp "${TMP}" "${OUT}"
  echo "✓ wrote ${OUT}"
fi
