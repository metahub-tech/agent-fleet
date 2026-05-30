#!/usr/bin/env bash
# 幂等地把 agent-fleet WDA 扩展注入到 $WDA_DIR 的 WebDriverAgent 源码树。
#
# usage:  install.sh /path/to/WebDriverAgent
#         install.sh                              # 默认 $WDA_DIR 或 $HOME/WebDriverAgent
#
# 适配 Appium WebDriverAgent 13.x：
#   - 路由文件放 WebDriverAgentLib/Commands/（不是老版 Routes/）。
#   - FBPhotosCommands 类实现 <FBCommandHandler> 协议 → FBWebServer 的运行时协议发现
#     (FBClassesThatConformsToProtocol) 自动挂载，**无需修改任何 router 文件**。
#   - 须把新文件加入 project.pbxproj 的 WebDriverAgentLib target（用 Python pbxproj 库）。
#
# 注入项：
#   1) cp FBPhotosCommands.{h,m} → WebDriverAgentLib/Commands/
#   2) project.pbxproj 注册新文件到 WebDriverAgentLib target（pbxproj 库 add_file，幂等）
#   3) WebDriverAgentRunner/Info.plist upsert NSPhotoLibraryAddUsageDescription
#   4) touch -m 让 xcodebuild 增量 build 失效
#
# 失败即非零退出（build-wda.sh 检 rc）。
#
# 一次性安装 pbxproj python 库（per-mac）:
#   /usr/bin/python3 -m pip install --user pbxproj
# 本脚本会在缺失时自动尝试 pip install --user。

set -eu

WDA_DIR="${1:-${WDA_DIR:-$HOME/WebDriverAgent}}"
EXT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$WDA_DIR/WebDriverAgentLib/Commands" ]; then
  echo "[wda-ext] FATAL: $WDA_DIR/WebDriverAgentLib/Commands not found（WDA 不是 Appium 13.x 结构？）" >&2
  exit 1
fi

COMMANDS_DIR="$WDA_DIR/WebDriverAgentLib/Commands"
PBXPROJ="$WDA_DIR/WebDriverAgent.xcodeproj/project.pbxproj"
PLIST="$WDA_DIR/WebDriverAgentRunner/Info.plist"

if [ ! -f "$PBXPROJ" ]; then
  echo "[wda-ext] FATAL: $PBXPROJ not found" >&2
  exit 1
fi
if [ ! -f "$PLIST" ]; then
  echo "[wda-ext] FATAL: $PLIST not found" >&2
  exit 1
fi

# ---- (1) cp .h/.m（幂等：覆盖到一致内容）----
install -m 0644 "$EXT_DIR/FBPhotosCommands.h" "$COMMANDS_DIR/FBPhotosCommands.h"
install -m 0644 "$EXT_DIR/FBPhotosCommands.m" "$COMMANDS_DIR/FBPhotosCommands.m"
echo "[wda-ext] copied FBPhotosCommands.{h,m} → $COMMANDS_DIR"

# ---- (2) project.pbxproj 注册新文件到 WebDriverAgentLib target（幂等）----
# 用系统 python3（Xcode 自带的 /usr/bin/python3）+ pbxproj 库。
PY="${WDA_EXT_PY:-/usr/bin/python3}"
if ! "$PY" -c "import pbxproj" 2>/dev/null; then
  echo "[wda-ext] installing pbxproj python lib (--user) ..."
  "$PY" -m pip install --user --quiet pbxproj || {
    echo "[wda-ext] FATAL: pip install pbxproj failed. 手装: $PY -m pip install --user pbxproj" >&2
    exit 1
  }
fi

"$PY" - "$PBXPROJ" <<'PYEOF'
import sys
from pbxproj import XcodeProject

pbxproj_path = sys.argv[1]
proj = XcodeProject.load(pbxproj_path)

# 加 .h（Headers phase）+ .m（Sources phase）到 WebDriverAgentLib target；
# add_file 默认 force=False → 已存在则不重复加。
for fname in ("FBPhotosCommands.h", "FBPhotosCommands.m"):
    rel = f"WebDriverAgentLib/Commands/{fname}"
    res = proj.add_file(rel, target_name="WebDriverAgentLib", force=False)
    print(f"[wda-ext] pbxproj add_file {rel} → {'added' if res else 'already present'}")

proj.save()
print("[wda-ext] pbxproj saved")
PYEOF

# ---- (3) Info.plist upsert NSPhotoLibraryAddUsageDescription（PlistBuddy 幂等）----
DESC="用于把上传的图片/视频加入相册（agent-fleet WDA 扩展）"
/usr/libexec/PlistBuddy -c "Add :NSPhotoLibraryAddUsageDescription string '$DESC'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :NSPhotoLibraryAddUsageDescription '$DESC'" "$PLIST"
echo "[wda-ext] upserted NSPhotoLibraryAddUsageDescription"

# ---- (4) touch -m 让 xcodebuild 增量 build 失效 ----
touch -m "$COMMANDS_DIR/FBPhotosCommands.h" "$COMMANDS_DIR/FBPhotosCommands.m" "$PBXPROJ" "$PLIST"

echo "[wda-ext] done. Re-run build-wda.sh to compile."
