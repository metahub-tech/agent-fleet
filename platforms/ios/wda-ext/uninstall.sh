#!/usr/bin/env bash
# 反向还原 install.sh 注入。
# usage: uninstall.sh /path/to/WebDriverAgent
set -eu

WDA_DIR="${1:-${WDA_DIR:-$HOME/WebDriverAgent}}"
ROUTES_DIR="$WDA_DIR/WebDriverAgentLib/Routes"
ROUTER_M="$WDA_DIR/WebDriverAgentLib/Routes/FBCommandRouter.m"
PLIST="$WDA_DIR/WebDriverAgentRunner/Info.plist"

# 删 cp 的 .h/.m
rm -f "$ROUTES_DIR/FBPhotosCommands.h" "$ROUTES_DIR/FBPhotosCommands.m"
echo "[wda-ext] removed FBPhotosCommands.{h,m}"

# 去 import + routes 数组项
if [ -f "$ROUTER_M" ]; then
  # 去 import 行
  sed -i.bak -e '/#import "FBPhotosCommands.h"/d' "$ROUTER_M"
  # 去 ", [FBPhotosCommands class]" 这一行（容忍前后空白）
  python3 - "$ROUTER_M" <<'PYEOF'
import re, sys
p = sys.argv[1]
src = open(p).read()
# 干掉 ", [FBPhotosCommands class]" 或独立一行 "[FBPhotosCommands class]"（容前后逗号与空白）
src = re.sub(r',?\s*\[FBPhotosCommands\s+class\]\s*,?', '', src)
open(p, "w").write(src)
PYEOF
  rm -f "$ROUTER_M.bak"
  echo "[wda-ext] cleaned FBCommandRouter.m"
fi

# 删 plist key
/usr/libexec/PlistBuddy -c "Delete :NSPhotoLibraryAddUsageDescription" "$PLIST" 2>/dev/null || true
echo "[wda-ext] reverted. Re-run build-wda.sh to apply."
