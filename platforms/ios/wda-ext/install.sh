#!/usr/bin/env bash
# 幂等地把 agent-fleet WDA 扩展注入到 $WDA_DIR 的 WebDriverAgent 源码树。
#
# usage:  install.sh /path/to/WebDriverAgent
#         install.sh                              # 默认 $WDA_DIR 或 $HOME/WebDriverAgent
#
# 注入项:
#   1) cp FBPhotosCommands.{h,m} → WebDriverAgentLib/Routes/
#   2) FBCommandRouter.m 注入 #import + commandHandlerClasses 数组项
#   3) WebDriverAgentRunner/Info.plist upsert NSPhotoLibraryAddUsageDescription
#   4) touch -m 让 xcodebuild 增量 build 失效
#
# 失败即非零退出（build-wda.sh 检 rc，避免编译出没新路由的 WDA）。

set -eu

WDA_DIR="${1:-${WDA_DIR:-$HOME/WebDriverAgent}}"
EXT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$WDA_DIR/WebDriverAgentLib" ]; then
  echo "[wda-ext] FATAL: $WDA_DIR/WebDriverAgentLib not found; pass correct WDA_DIR" >&2
  exit 1
fi

ROUTES_DIR="$WDA_DIR/WebDriverAgentLib/Routes"
ROUTER_M="$WDA_DIR/WebDriverAgentLib/Routes/FBCommandRouter.m"
PLIST="$WDA_DIR/WebDriverAgentRunner/Info.plist"

if [ ! -f "$ROUTER_M" ]; then
  echo "[wda-ext] FATAL: $ROUTER_M not found（WDA 结构变了？）" >&2
  exit 1
fi
if [ ! -f "$PLIST" ]; then
  echo "[wda-ext] FATAL: $PLIST not found（WDA runner Info.plist 缺失？）" >&2
  exit 1
fi

# ---- (1) cp .h/.m（幂等：每次覆盖到一致内容）----
install -m 0644 "$EXT_DIR/FBPhotosCommands.h" "$ROUTES_DIR/FBPhotosCommands.h"
install -m 0644 "$EXT_DIR/FBPhotosCommands.m" "$ROUTES_DIR/FBPhotosCommands.m"
echo "[wda-ext] copied FBPhotosCommands.{h,m} → $ROUTES_DIR"

# ---- (2a) 注入 #import "FBPhotosCommands.h"（幂等）----
if grep -q '"FBPhotosCommands.h"' "$ROUTER_M"; then
  echo "[wda-ext] #import already present, skip"
else
  # 在最后一条 #import "FB*.h" 之后追加我们的 import
  awk '
    /^#import "FB.*\.h"/ { lastImport=NR }
    { lines[NR]=$0 }
    END {
      for (i=1; i<=NR; i++) {
        print lines[i]
        if (i == lastImport) print "#import \"FBPhotosCommands.h\""
      }
    }
  ' "$ROUTER_M" > "$ROUTER_M.tmp" && mv "$ROUTER_M.tmp" "$ROUTER_M"
  if grep -q '"FBPhotosCommands.h"' "$ROUTER_M"; then
    echo "[wda-ext] injected #import \"FBPhotosCommands.h\" into FBCommandRouter.m"
  else
    echo "[wda-ext] FATAL: 未找到 #import \"FB*.h\" 锚点；FBCommandRouter.m 结构可能变化" >&2
    exit 1
  fi
fi

# ---- (2b) 注入 commandHandlerClasses 数组项（幂等，借 python regex）----
if grep -q "\[FBPhotosCommands class\]" "$ROUTER_M"; then
  echo "[wda-ext] [FBPhotosCommands class] already present, skip"
else
  python3 - "$ROUTER_M" <<'PYEOF' || exit 1
import re, sys
p = sys.argv[1]
src = open(p).read()
# 在数组结束前最后一项 [FBxxxCommands class] 后插入逗号 + 换行 + 我们的项。
# 匹配："[FBxxxCommands class]" 后紧跟可选空白 + "]" + 可选空白 + ";"
new = re.sub(r'(\[FB[A-Za-z_]+Commands\s+class\])(\s*\]\s*;)',
             r'\1,\n  [FBPhotosCommands class]\2', src, count=1)
if new == src:
    print("[wda-ext] FATAL: 未找到 commandHandlerClasses 数组锚点（最后一个 [FBxxxCommands class]）；"
          "FBCommandRouter.m 结构变化，请手动添加或调整 install.sh 锚点正则", file=sys.stderr)
    sys.exit(1)
open(p, "w").write(new)
PYEOF
  echo "[wda-ext] injected [FBPhotosCommands class] into commandHandlerClasses"
fi

# ---- (3) Info.plist upsert NSPhotoLibraryAddUsageDescription（PlistBuddy 幂等）----
DESC="用于把上传的图片/视频加入相册（agent-fleet WDA 扩展）"
/usr/libexec/PlistBuddy -c "Add :NSPhotoLibraryAddUsageDescription string '$DESC'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :NSPhotoLibraryAddUsageDescription '$DESC'" "$PLIST"
echo "[wda-ext] upserted NSPhotoLibraryAddUsageDescription"

# ---- (4) touch -m 让 xcodebuild 增量 build 失效 ----
touch -m "$ROUTES_DIR/FBPhotosCommands.h" "$ROUTES_DIR/FBPhotosCommands.m" "$ROUTER_M" "$PLIST"

echo "[wda-ext] done. Re-run build-wda.sh to compile."
