#!/usr/bin/env bash
# check-blueprint-refs.sh
#
# 校验 docs/internal/blueprint/ 内 markdown 文件中"明确的文件引用"实际存在。
# 失效 → exit 1。
#
# 只校验真实的"单文件路径引用"，跳过：
#   - 目录引用（无扩展名 / 以 / 结尾）
#   - 通配符路径（含 *, ?, [, ]）
#   - 跨仓库引用（含 :）
#   - URL（http/https 开头）
#   - 含 shell 元字符 / 占位符标记的（$ = ! \ # @ < > { } | space）
#   - 代码块内的引用（``` ... ``` 围栏内不算文档引用，是示例代码）
#
# 解析既支持仓库根相对路径（如 docs/foo.md），也支持当前 md 文件相对路径（如 DECISIONS/0001-x.md）。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

python3 - <<'PYEOF'
import re
import sys
from pathlib import Path

REPO = Path(".")
BLUEPRINT = REPO / "docs/internal/blueprint"

if not BLUEPRINT.exists():
    print(f"⚠️ {BLUEPRINT} 不存在，跳过（首次建蓝图前 CI 该步会被 skip）")
    sys.exit(0)

# 字符黑名单：含其中任一即非"单文件引用"
FORBIDDEN_CHARS = set(" *?[]{}()<>|$=!\\#@:")

def is_file_ref(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if "/" not in s:
        return False
    if s.startswith(("http://", "https://", "//")):
        return False
    if any(c in FORBIDDEN_CHARS for c in s):
        return False
    if s.endswith("/"):  # 目录引用
        return False
    # basename 必须含 `.`（看起来是文件名）
    last = s.rsplit("/", 1)[-1]
    if "." not in last:
        return False
    return True

def strip_code_fences(text: str) -> str:
    # 删除 ``` ... ``` 三反引号代码块；保留行内反引号
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)

errors = []
for md in sorted(BLUEPRINT.rglob("*.md")):
    text = strip_code_fences(md.read_text(encoding="utf-8"))
    for m in re.finditer(r"`([^`\n]+)`", text):
        ref = m.group(1).strip()
        if not is_file_ref(ref):
            continue
        # 先按仓库根解析，再按 md 同目录解析
        cands = [REPO / ref, md.parent / ref]
        if not any(p.exists() for p in cands):
            errors.append((str(md), ref))

if errors:
    print(f"❌ {len(errors)} 处蓝图引用路径无效：", file=sys.stderr)
    for f, ref in errors:
        print(f"  {f} → {ref}", file=sys.stderr)
    sys.exit(1)

print("✓ 蓝图内所有路径引用均有效")
PYEOF
