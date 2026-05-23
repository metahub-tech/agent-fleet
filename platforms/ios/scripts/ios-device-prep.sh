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
INSTALL_DAEMON="$SCRIPT_DIR/install-wda-daemon.sh"
XCODE_APPSTORE="macappstore://apps.apple.com/app/xcode/id497799835"
NONINTERACTIVE="${NONINTERACTIVE:-0}"

pmd(){ "$VENV_PY" -m pymobiledevice3 "$@"; }
# Team ID = the signing cert's OU. NOT the CN parens — for free/personal Apple IDs
# the CN "(…)" value differs from the real Team ID (e.g. CN "(X6K6QH36UZ)" but OU
# "TTS982TAM4"; only the OU is the DEVELOPMENT_TEAM xcodebuild accepts).
team_id_from_cert(){
    security find-certificate -a -c "Apple Development" -p 2>/dev/null \
        | openssl x509 -noout -subject 2>/dev/null \
        | grep -oE 'OU ?= ?[A-Z0-9]{10}' | head -1 | grep -oE '[A-Z0-9]{10}'
}

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
TEAM_ID="$(team_id_from_cert)"
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
    TEAM_ID="$(team_id_from_cert)"
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
    # randomize the local forward port: this fn is called repeatedly in tight
    # polling loops, and a fixed port would collide with the prior call's
    # forward (kill is async — the socket may not be released yet) → false
    # "unreachable". A fresh port per call sidesteps the race (and concurrent
    # multi-device preps on the same host).
    local p=$(( 18200 + RANDOM % 400 ))
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
# Bundle ID —— build 和 daemon 都要用,所以先确定(即便 WDA 已在跑,daemon 也要它)。
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

if [ "$NONINTERACTIVE" = "1" ]; then
    info "(non-interactive: 跳过实际 build)"
elif wda_reachable; then
    ok "WDA 已在运行 —— 跳过构建"
else
    # 后台跑 build-wda 来「构建+安装+(引导)信任」WDA:它会装上 App 并尝试启动。轮询 WDA
    # 是否可达 —— 可达 = 装好且已信任 → 杀掉这个临时 build,下一步交给 daemon 常驻。首次启动
    # 若因「证书未信任」失败,build 进程会退出 → 暂停让你在 iPhone 信任 → 自动重试。
    BUILD_LOG="${TMPDIR:-/tmp}/agent-fleet-buildwda-${UDID}.log"
    _attempt=1
    while : ; do
        info "构建+安装 WDA(后台,首次约 5-10 分钟;实时日志: tail -f $BUILD_LOG)…"
        WDA_TEAM_ID="$TEAM_ID" bash "$BUILD_WDA" "$UDID" "$BUNDLE_ID" >"$BUILD_LOG" 2>&1 &
        BUILD_PID=$!
        _reached=0
        for _i in $(seq 1 90); do                       # 最长 ~15 分钟(覆盖首次编译)
            if wda_reachable; then _reached=1; break; fi
            kill -0 "$BUILD_PID" 2>/dev/null || break   # build 进程已退出(失败/未信任)
            sleep 10
        done
        if [ "$_reached" = 1 ]; then
            ok "WDA 构建+启动验证通过"
            # 停临时 build,交给 daemon。先杀 build wrapper 的子进程(xcodebuild 及其
            # XCUITest 会话),否则杀了 wrapper 后 xcodebuild 会被 reparent 继续跑,残留
            # 的 WDA 会话会与 daemon 的 go-ios runwda 抢同一个 runner bundle。
            pkill -P "$BUILD_PID" 2>/dev/null || true
            kill "$BUILD_PID" 2>/dev/null; wait "$BUILD_PID" 2>/dev/null
            break
        fi
        wait "$BUILD_PID" 2>/dev/null
        if [ "$_attempt" -le 2 ] && pmd apps list --udid "$UDID" 2>/dev/null | grep -q "${BUNDLE_ID}.xctrunner"; then
            warn "WDA 已装到 iPhone,但启动被拒 —— 开发者证书还没在手机上「信任」(只能你在手机上点)。"
            act "去 iPhone:设置 → 通用 → VPN与设备管理 →「开发者 App」下的「Apple Development:你的 Apple ID」→ 信任"
            hint "(「VPN与设备管理」装了 App 后才出现;信任完回来按回车,我自动重试)"
            pause
            _attempt=$((_attempt + 1))
            continue
        fi
        warn "build 没成功 —— 看日志 $BUILD_LOG(常见:签名/账号、设备被锁屏)。"
        die "在 iPhone 信任证书后重跑本脚本,或查上面日志"
    done
fi

# ───────── Phase 4 · 持久化(launchd 后台常驻)─────────
step 4 "持久化 WDA(launchd 守护:登录自启、崩溃自拉、关终端/重启都不掉)"
if [ "$NONINTERACTIVE" = "1" ]; then
    info "(non-interactive: 跳过 daemon 安装)"
else
    bash "$INSTALL_DAEMON" "$UDID" "$BUNDLE_ID" || warn "daemon 安装返回非零 —— 看上面输出"
    _up=0
    for _i in $(seq 1 24); do                           # 等 daemon 经 go-ios 把 WDA 拉起来(~120s,冷启动偏慢)
        if wda_reachable; then _up=1; break; fi
        sleep 5
    done
    if [ "$_up" = 1 ]; then
        ok "daemon 已接管,WDA 后台常驻可达(go-ios runwda)"
    else
        warn "daemon 已装但暂未探到 WDA;看日志 ~/Library/Logs/agent-fleet/wda-*.log。"
        warn "(若日志反复刷「无法检测 iOS 版本」,多半是设备未解锁/未信任,处理后 launchd 会自动重试。)"
    fi
fi

# ───────── Phase 5 · 完成 ─────────
step 5 "完成"
ok "设备 $MODEL($UDID)已上线,WDA 由 launchd 后台常驻(不再依赖前台 xcodebuild)。"
info "证书 7 天到期(免费账号)→ 重跑本脚本重建即可。ios-device server 自动枚举设备;agent 端 list_devices() 就能看到它。"
printf '\n════════ done ════════\n\n'
