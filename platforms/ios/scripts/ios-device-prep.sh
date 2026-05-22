#!/usr/bin/env bash
# Guided, idempotent, version-aware iOS device onboarding for WebDriverAgent.
#
# Automates what it can; for the steps only you can do (add an Apple ID + 2FA in
# Xcode, taps on the iPhone) it prints the EXACT Settings path, opens the screen
# where possible, waits, then re-checks. Re-run anytime — it resumes from wherever
# it stopped (idempotent). Written for macOS's stock bash 3.2.
#
# Usage: ios-device-prep.sh [UDID]    # UDID optional when exactly one device attached
# Env:   NONINTERACTIVE=1  -> never block on prompts (used for self-test/CI)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_DIR="$(cd "$SCRIPT_DIR/../server" && pwd)"
VENV_PY="$SERVER_DIR/.venv/bin/python"
WDA_DIR="${WDA_DIR:-$HOME/WebDriverAgent}"
BUILD_WDA="$SCRIPT_DIR/build-wda.sh"
XCODE_APPSTORE="macappstore://apps.apple.com/app/xcode/id497799835"
NONINTERACTIVE="${NONINTERACTIVE:-0}"

pmd(){ "$VENV_PY" -m pymobiledevice3 "$@"; }

ok(){   printf '  \033[32m✓\033[0m %s\n' "$*"; }
info(){ printf '  • %s\n' "$*"; }
warn(){ printf '  \033[33m⚠\033[0m %s\n' "$*"; }
step(){ printf '\n\033[1m[%s] %s\033[0m\n' "$1" "$2"; }
act(){  printf '\n\033[1;33m▶ 需要你操作:\033[0m %s\n' "$*"; }
hint(){ printf '     %s\n' "$*"; }
die(){  printf '\n\033[31m✗ %s\033[0m\n\n' "$1"; exit "${2:-1}"; }
pause(){
    if [ "$NONINTERACTIVE" = "1" ]; then printf '   (non-interactive: 跳过等待)\n'; return; fi
    printf '\n   做完后按 \033[1m回车\033[0m 继续(Ctrl-C 退出,稍后重跑续上)… '
    read -r _ || true
}
maybe_open(){ [ "$NONINTERACTIVE" = "1" ] && return 0; open "$@" 2>/dev/null || true; }
# best-effort: drive Xcode to open Settings/Preferences → Accounts. Needs Automation
# permission; the first run may prompt "Terminal wants to control Xcode/System Events".
# If it fails/denied, the printed menu path is the fallback.
open_xcode_accounts(){
    [ "$NONINTERACTIVE" = "1" ] && return 0
    osascript >/dev/null 2>&1 <<'OSA' || true
tell application "Xcode" to activate
delay 0.6
tell application "System Events" to tell process "Xcode"
  set frontmost to true
  delay 0.3
  repeat with mi in (menu items of menu 1 of menu bar item "Xcode" of menu bar 1)
    set nm to (name of mi)
    if nm is not missing value and (nm contains "Settings" or nm contains "Preferences") then
      click mi
      exit repeat
    end if
  end repeat
  delay 1.2
  repeat with w in windows
    try
      repeat with b in (buttons of toolbar 1 of w)
        if (description of b is "Accounts") or (name of b is "Accounts") then
          click b
          exit repeat
        end if
      end repeat
    end try
  end repeat
end tell
OSA
}

[ -x "$VENV_PY" ] || die "ios server venv 未就绪($VENV_PY);先在仓库根跑:bash platforms/ios/scripts/setup-ios.sh"

# Per-device state dir: remember manual steps we can't re-detect so re-runs don't re-nag.
STATE_ROOT="$HOME/.agent-fleet/ios-onboard"
marked(){ [ -f "$STATE_DIR/$1" ]; }
mark(){   mkdir -p "$STATE_DIR"; : > "$STATE_DIR/$1"; }

printf '\n════════ iOS 设备引导(可重复跑 · 断点续)════════\n'

# ───────── Phase 0.1 · 完整 Xcode ─────────
step 0.1 "检查 Xcode(WDA 构建必须用完整 Xcode,不是 Command Line Tools)"
XSEL="$(xcode-select -p 2>/dev/null || true)"
if ! printf '%s' "$XSEL" | grep -q "Xcode.app"; then
    warn "未检测到完整 Xcode(当前: ${XSEL:-无})。"
    act "安装 Xcode —— 正在为你打开 App Store 的 Xcode 页面"
    maybe_open "$XCODE_APPSTORE"
    hint "(若没自动弹出 App Store,手动打开 App Store 搜索 Xcode)"
    hint "装好后执行这两条,再重跑本脚本:"
    hint "   sudo xcode-select -s /Applications/Xcode.app"
    hint "   sudo xcodebuild -license accept"
    die "等 Xcode 装好后重跑本脚本" 0
fi
XVER_LINE="$(xcodebuild -version 2>/dev/null | head -1)"
XVER_MAJ="$(printf '%s' "$XVER_LINE" | sed -E 's/[^0-9]*([0-9]+).*/\1/')"
ok "Xcode 已装:${XVER_LINE:-未知}"

# ───────── Phase 1 · 设备检测 + 抓 UDID/iOS版本/机型 ─────────
step 1 "检测已连接的 iPhone / iPad"
WANT_UDID="${1:-}"
SEL="$(pmd usbmux list 2>/dev/null | "$VENV_PY" -c '
import sys, json
want = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    data = json.load(sys.stdin)
except Exception:
    data = []
if want:
    data = [d for d in data if d.get("UniqueDeviceID") == want]
if len(data) == 1:
    d = data[0]
    print("ONE\t%s\t%s\t%s" % (d.get("UniqueDeviceID",""), d.get("ProductVersion",""), d.get("ProductType","")))
elif not data:
    print("NONE")
else:
    print("MULTI")
    for d in data:
        print("  - %s  iOS %s  %s" % (d.get("UniqueDeviceID",""), d.get("ProductVersion",""), d.get("ProductType","")))
' "$WANT_UDID" 2>/dev/null)"

FIRST="$(printf '%s\n' "$SEL" | head -1)"
case "$FIRST" in
    ONE*)
        UDID="$(printf '%s' "$FIRST" | cut -f2)"
        IOSVER="$(printf '%s' "$FIRST" | cut -f3)"
        MODEL="$(printf '%s' "$FIRST" | cut -f4)"
        ;;
    MULTI)
        printf '%s\n' "$SEL" | tail -n +2
        die "检测到多台设备 —— 请指定 UDID:bash $0 <UDID>"
        ;;
    *)
        warn "没找到已配对的 iOS 设备。"
        act "用数据线把 iPhone 连到这台 Mac → 设备上点「信任此电脑」并输密码"
        pause
        die "设备未就绪;插好并信任后重跑本脚本" 0
        ;;
esac
IOS_MAJ="${IOSVER%%.*}"
ok "设备:$MODEL  iOS $IOSVER"
ok "UDID:$UDID"
STATE_DIR="$STATE_ROOT/$UDID"

# Xcode-vs-iOS 兼容性提醒(不阻断):Xcode 16+ 走 CoreDevice,无法给 iOS<17 真机 test。
if [ -n "$XVER_MAJ" ] && [ "$XVER_MAJ" -ge 16 ] 2>/dev/null && [ -n "$IOS_MAJ" ] && [ "$IOS_MAJ" -lt 17 ] 2>/dev/null; then
    warn "Xcode $XVER_MAJ 可能无法给 iOS $IOSVER 真机做 xcodebuild test(CoreDevice 不支持 iOS<17)。"
    hint "若 build 阶段报 'build number'/'Logic Testing Unavailable',改用 Xcode 14 或 15。"
fi

# ───────── Phase 0.2 · Apple ID / 签名证书 ─────────
step 0.2 "检查 Apple ID 签名证书(WDA 签名必须)"
TEAM_ID="$(security find-identity -v -p codesigning 2>/dev/null | grep "Apple Development" | head -1 | sed -E 's/.*\(([A-Z0-9]{10})\)".*/\1/')"
if [ -z "$TEAM_ID" ]; then
    warn "钥匙串里没有 'Apple Development' 证书 —— 还没在 Xcode 里登 Apple ID。"
    act "在 Xcode 里加 Apple ID(免费账号即可,7 天证书):"
    if [ -d "$WDA_DIR/WebDriverAgent.xcodeproj" ]; then
        maybe_open "$WDA_DIR/WebDriverAgent.xcodeproj"   # 直接打开 WDA 工程(比 Xcode 欢迎页有用)
    else
        maybe_open -a Xcode
    fi
    open_xcode_accounts   # 自动把 Xcode 切到 偏好设置 → Accounts 页
    hint "已为你打开 Xcode 的 Accounts 页 → 点左下「+」→ Apple ID → 登录(2FA 验证码在你其它 Apple 设备上)"
    hint "(若没自动跳到:Xcode 顶部菜单 → Settings…(Xcode 14 叫 Preferences…,快捷键都是 ⌘,)→ Accounts 标签)"
    hint "(加完 Apple ID 顺手可在 WebDriverAgentRunner → Signing & Capabilities 选你的 Team)"
    pause
    TEAM_ID="$(security find-identity -v -p codesigning 2>/dev/null | grep "Apple Development" | head -1 | sed -E 's/.*\(([A-Z0-9]{10})\)".*/\1/')"
    [ -z "$TEAM_ID" ] && die "仍没检测到开发证书;在 Xcode 里登好 Apple ID 后重跑本脚本"
fi
ok "签名证书就绪(Team $TEAM_ID)"

# ───────── Phase 2 · 设备设置(版本感知) ─────────
# 2a. Developer Mode —— 仅 iOS≥16;iOS 15 没有这个开关。
step 2a "Developer Mode(开发者模式)"
# 仅 iOS≥16 有 Developer Mode;版本未知/为空时也走「跳过」分支(不复现旧 bug)。
if [ -n "$IOS_MAJ" ] && [ "$IOS_MAJ" -ge 16 ] 2>/dev/null; then
    DM="$(pmd amfi developer-mode-status --udid "$UDID" 2>/dev/null | tr -d '[:space:]' | tail -c 5)"
    if printf '%s' "$DM" | grep -qi true; then
        ok "Developer Mode 已开"
    else
        warn "Developer Mode 未开 —— 正在 reveal + 触发开启…"
        pmd amfi reveal-developer-mode --udid "$UDID" 2>/dev/null || true
        pmd amfi enable-developer-mode --udid "$UDID" >/dev/null 2>&1 || true
        act "设备会重启;开机后锁屏会弹「打开开发者模式?」→ 点 Turn On → 输密码"
        hint "(没弹的话:设置 → 隐私与安全性 → 开发者模式 → 打开 → 重启)"
        pause
        DM="$(pmd amfi developer-mode-status --udid "$UDID" 2>/dev/null | tr -d '[:space:]' | tail -c 5)"
        printf '%s' "$DM" | grep -qi true || die "Developer Mode 仍未开;开好后重跑本脚本"
        ok "Developer Mode 已开"
    fi
else
    ok "iOS ${IOSVER:-未知} 无需 Developer Mode(iOS<16 没有此开关)—— 跳过"
fi

# 2b. Enable UI Automation(无法自动检测 → 引导 + 标记)
step 2b "Enable UI Automation(自动化必须;开完要重启设备)"
if marked ui-automation; then
    ok "已确认(之前标记过)"
else
    act "在 iPhone 上:设置 → 开发者 → Enable UI Automation → 打开 → 然后重启 iPhone"
    hint "(「开发者」菜单要等设备连过 Xcode 后才出现;若没有,先在 Xcode → Window → Devices and Simulators 里连一次这台设备)"
    hint "(开完务必重启,否则 WDA 会一直 'Timed out while enabling automation mode')"
    pause
    [ "$NONINTERACTIVE" = "1" ] || mark ui-automation
fi

# 2c. Auto-Lock=永不 + 屏幕使用时间安装限制关(无法自动检测 → 引导 + 标记)
step 2c "保持设备醒着 + 不挡装 App"
if marked device-misc; then
    ok "已确认(之前标记过)"
else
    act "在 iPhone 上设置以下两项:"
    hint "设置 → 显示与亮度 → 自动锁定 → 永不(build 期间别息屏锁屏)"
    hint "设置 → 屏幕使用时间 → 内容和隐私访问限制 →(若开着)关掉对「安装 App」的限制"
    pause
    [ "$NONINTERACTIVE" = "1" ] || mark device-misc
fi

# ───────── Phase 3 · 构建 WDA ─────────
step 3 "WebDriverAgent 构建 / 启动"
[ -d "$WDA_DIR/WebDriverAgent.xcodeproj" ] || {
    warn "没找到 WebDriverAgent($WDA_DIR)"
    act "克隆 WebDriverAgent(我也可以,但你跑更稳):"
    hint "git -c http.version=HTTP/1.1 clone https://github.com/appium/WebDriverAgent.git \"$WDA_DIR\""
    pause
    [ -d "$WDA_DIR/WebDriverAgent.xcodeproj" ] || die "WDA 仓库未就绪;克隆后重跑本脚本"
}

# 已经在跑就跳过(幂等)。用一个临时 forward 探活。
wda_reachable(){
    local p=18290
    pmd usbmux forward "$p" 8100 --udid "$UDID" >/dev/null 2>&1 &
    local fpid=$!
    disown "$fpid" 2>/dev/null || true   # don't let the shell print "Terminated: 15" when we kill it
    local up=1 i=0
    while [ $i -lt 5 ]; do
        if curl -s --max-time 2 "http://127.0.0.1:$p/status" 2>/dev/null | grep -q '"state"'; then up=0; break; fi
        sleep 1; i=$((i+1))
    done
    kill "$fpid" 2>/dev/null || true
    return $up
}
if wda_reachable; then
    ok "WDA 已在设备上运行且可达 —— 跳过构建"
else
    DEF_BUNDLE="com.$(id -un | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9').WebDriverAgentRunner"
    BUNDLE_ID="${WDA_BUNDLE_ID:-}"
    if [ -z "$BUNDLE_ID" ]; then
        if [ "$NONINTERACTIVE" = "1" ]; then
            BUNDLE_ID="$DEF_BUNDLE"
        else
            printf '\n   输入 WDA 的 Bundle ID(全局唯一;直接回车用默认 \033[1m%s\033[0m): ' "$DEF_BUNDLE"
            read -r BUNDLE_ID || true
            [ -z "$BUNDLE_ID" ] && BUNDLE_ID="$DEF_BUNDLE"
        fi
    fi
    info "Bundle ID: $BUNDLE_ID    Team: $TEAM_ID    Device: $UDID"
    act "接下来跑 build(xcodebuild test,约 5-10 分钟,会一直挂着以保持 WDA 运行)。"
    hint "⚠ 首次 build 把 App 装上后,iPhone 会弹「未受信任的开发者」,build 会卡住等你信任 —— 这不是死机!"
    hint "   去手机:设置 → 通用 → VPN与设备管理 → 你的 Apple ID($TEAM_ID)→ 信任"
    hint "   信任后 build 自动继续(若没动静,Ctrl-C 再重跑本脚本即可,会从这步续上)。现在开始构建 ↓"
    if [ "$NONINTERACTIVE" = "1" ]; then
        info "(non-interactive: 跳过实际 build)"
    else
        WDA_TEAM_ID="$TEAM_ID" bash "$BUILD_WDA" "$UDID" "$BUNDLE_ID" || \
            die "build 没成功。常见:① iPhone 上还没「信任」开发者证书;② Auto-Lock 把屏锁了。处理后重跑本脚本。"
        # build-wda 是挂着的 test;真到这里说明它退出了 —— 再探一次活。
        wda_reachable && ok "WDA 可达" || warn "build 退出但 WDA 未探到;若刚信任完证书,请重跑本脚本"
    fi
fi

# ───────── Phase 4 · 完成 ─────────
step 4 "完成"
ok "设备 $MODEL($UDID)前置就绪。"
info "ios-device server 每次工具调用都会自动重新枚举设备;WDA 起来后在 agent 端重连 + list_devices() 即可看到它。"
printf '\n════════ done ════════\n\n'
