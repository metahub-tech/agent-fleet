#!/usr/bin/env bash
# 反向还原 install.sh 注入。
# usage: uninstall.sh /path/to/WebDriverAgent
set -eu

WDA_DIR="${1:-${WDA_DIR:-$HOME/WebDriverAgent}}"
COMMANDS_DIR="$WDA_DIR/WebDriverAgentLib/Commands"
PBXPROJ="$WDA_DIR/WebDriverAgent.xcodeproj/project.pbxproj"
PLIST="$WDA_DIR/WebDriverAgentRunner/Info.plist"

# 删 cp 的 .h/.m
rm -f "$COMMANDS_DIR/FBPhotosCommands.h" "$COMMANDS_DIR/FBPhotosCommands.m"
echo "[wda-ext] removed FBPhotosCommands.{h,m}"

# 从 pbxproj 移除文件引用
PY="${WDA_EXT_PY:-/usr/bin/python3}"
if "$PY" -c "import pbxproj" 2>/dev/null && [ -f "$PBXPROJ" ]; then
  "$PY" - "$PBXPROJ" <<'PYEOF'
import sys
from pbxproj import XcodeProject
proj = XcodeProject.load(sys.argv[1])
for fname in ("FBPhotosCommands.h", "FBPhotosCommands.m"):
    rel = f"WebDriverAgentLib/Commands/{fname}"
    res = proj.remove_file_by_path(rel)
    print(f"[wda-ext] pbxproj remove {rel} → {res}")
proj.save()
PYEOF
fi

# 删 plist key
/usr/libexec/PlistBuddy -c "Delete :NSPhotoLibraryAddUsageDescription" "$PLIST" 2>/dev/null || true
echo "[wda-ext] reverted. Re-run build-wda.sh to apply."
