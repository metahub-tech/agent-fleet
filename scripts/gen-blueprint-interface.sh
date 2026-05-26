#!/usr/bin/env bash
# gen-blueprint-interface.sh
#
# 自动从代码生成项目蓝图：INTERFACE.md（MCP 工具签名清单）
# 用法：
#   ./scripts/gen-blueprint-interface.sh           # 写入文件
#   ./scripts/gen-blueprint-interface.sh --check   # 仅校验
#
# 实现：用 Python ast 模块扫描各平台 server/*_mcp.py 里所有
# @mcp.tool / @mcp.tool() / @app.tool 装饰过的函数，提取签名。

set -euo pipefail

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

OUT="docs/internal/blueprint/INTERFACE.md"
TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

{
  echo "# Project INTERFACE（自动生成 · 请勿手编）"
  echo ""
  echo "_由 \`scripts/gen-blueprint-interface.sh\` 从代码自动生成。各平台 MCP server 上的工具签名集 = agent 跨平台调用的 universal tool set。_"
  echo ""
  echo "> **覆盖范围**：仅列各 server 里 \`@*.tool\` 静态装饰的函数。"
  echo "> **不在覆盖范围**：能力框架运行时动态注入的可选能力工具（如 Windows / macOS 上的 \`agent_browser\` / \`human_browser_open\` 系列，共 ~28 个）——这些工具运行时通过 \`list_capabilities()\` 取真实清单；文档侧见各平台 README 的 \"浏览器能力（可选）/ Platform-specific extensions\" 节。"
  echo ""

  for p in $(ls platforms/ 2>/dev/null | sort); do
    case "${p}" in
      common|tests) continue ;;
    esac
    main_py=""
    for candidate in "platforms/${p}/server/${p}_device_mcp.py" "platforms/${p}/server/"*_mcp.py; do
      if [ -f "${candidate}" ]; then
        main_py="${candidate}"
        break
      fi
    done
    [ -z "${main_py}" ] && continue

    echo "## ${p}"
    echo ""
    echo "源：\`${main_py}\`"
    echo ""

    python3 - "${main_py}" <<'PYEOF'
import ast, sys

src = sys.argv[1]
try:
    tree = ast.parse(open(src).read())
except SyntaxError:
    print("_(parse 失败)_")
    sys.exit(0)

tools = []
for node in ast.walk(tree):
    if not isinstance(node, ast.FunctionDef):
        continue
    is_tool = False
    for dec in node.decorator_list:
        s = ast.unparse(dec)
        # 匹配 @mcp.tool / @mcp.tool(...) / @app.tool / @<server>.tool
        if s.endswith(".tool") or ".tool(" in s:
            is_tool = True
            break
    if not is_tool:
        continue
    args = []
    for a in node.args.args:
        if a.arg in ("self", "ctx"):
            continue
        ann = ""
        if a.annotation is not None:
            try:
                ann = ": " + ast.unparse(a.annotation)
            except Exception:
                ann = ": ?"
        args.append(f"{a.arg}{ann}")
    ret = ""
    if node.returns is not None:
        try:
            ret = " -> " + ast.unparse(node.returns)
        except Exception:
            ret = " -> ?"
    tools.append((node.name, args, ret))

tools.sort(key=lambda t: t[0])
for name, args, ret in tools:
    args_str = ", ".join(args)
    print(f"- `{name}({args_str}){ret}`")
if not tools:
    print("_(未检测到 @*.tool 装饰的函数；若实际有工具请检查 generator 的装饰器匹配规则)_")
PYEOF
    echo ""
  done
} > "${TMP}"

if [ "${CHECK}" = "1" ]; then
  if ! diff -q "${OUT}" "${TMP}" >/dev/null 2>&1; then
    echo "❌ ${OUT} 与代码现状不同步" >&2
    echo "请跑 \`./scripts/gen-blueprint-interface.sh\` 后重新提交" >&2
    diff "${OUT}" "${TMP}" >&2 || true
    exit 1
  fi
  echo "✓ ${OUT} 与代码同步"
else
  mkdir -p "$(dirname "${OUT}")"
  cp "${TMP}" "${OUT}"
  echo "✓ wrote ${OUT}"
fi
