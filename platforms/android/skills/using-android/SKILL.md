---
name: using-android
description: Use when invoking android-device MCP tools to drive a real Android device or emulator over ADB (agent-fleet project) -- screen capture, tap/swipe/keyboard, app install/launch/kill, on-device shell, host<->device file transfer, multi-agent coordination.
---

# Using android-device

Drive one or more Android devices via the `android-device` MCP server (FastMCP, streamable-http on Tailscale, port 8768). The server runs on a **PC host** (Windows or macOS), and reaches the phone(s) via **ADB** (USB or Wireless). 25 tools across 9 categories.

## Mental model

```
[You / Agent]  -- streamable-http -->  [PC Host running android-device MCP]  -- ADB --> [Android Phone]
```

You drive the SERVER. The server drives ADB. ADB drives the PHONE. You don't touch the phone directly.

## Critical patterns

### Coordinates are device-screen pixels (no Retina-style scaling)

`get_screen_size` returns the phone's wm size (e.g. `{width: 1080, height: 2340}`). `take_screenshot` returns a PNG sized identically. `tap(x, y)` uses the same coordinate space. **No scaling math needed** — phones don't have macOS-style logical/physical pixel split.

```
get_screen_size                  # {"width": 1080, "height": 2340}
take_screenshot                   # PNG also at 1080x2340
tap(x=540, y=1170)                # center of screen
```

### tap, NOT click

Phones use touchscreens. The tool is `tap`, not `click`. Calling `click` will fail (it's a Windows / macOS thing).

### Keyboard: input text vs press_key

| What | Tool | Note |
|---|---|---|
| Type into a focused input | `type_text("hello world")` | Spaces auto-escaped to `%s`. Newlines / Chinese / emoji NOT supported by `adb input text`. For SMS specifically, use the intent-extra workaround in Recipes; for in-app search / share, look for an intent the target app accepts with a string extra. |
| System buttons | `press_key("back")`, `press_key("home")`, `press_key("recent")` | Aliases for KEYCODE_BACK / HOME / APP_SWITCH |
| Volume / power | `press_key("volume_up")`, `press_key("power")`, `press_key("wake")` | Useful for wakelock testing |

### App lifecycle

```
list_packages(filter_substring="weibo", only_user=True)   # find installed user apps
start_app(package="com.sina.weibo")                        # launcher intent (default)
start_app(package="com.example", activity=".MainActivity") # explicit activity
current_app()                                              # what's in front
kill_app(package="com.sina.weibo")                         # force-stop
install_apk(apk_path="C:\\\\path\\\\to\\\\foo.apk", replace=True)
uninstall_app(package="com.example.foo")
```

`start_app` without `activity` uses `monkey -p <pkg> -c android.intent.category.LAUNCHER 1` -- the same intent the launcher sends. With `activity` it uses `am start -n pkg/activity` for explicit deep links.

### On-device shell vs host shell

| Need | Tool | Runs on |
|---|---|---|
| `getprop`, `dumpsys`, `pm`, `am`, `settings`, `cmd` on the phone | `adb_shell("getprop ro.build.version.release")` | Phone |
| `dir`, `Get-Process`, `python` on the host PC | NOT EXPOSED in this server -- use win-device's `run_powershell` if the Android host is Windows; mac-device's `run_zsh` if macOS | Host |

Mixing these is the #1 mistake. `adb_shell` always means "on the phone".

### Multi-agent coordination (advisory)

Tools work for everyone regardless of who claims the device:

```
get_android_status                     # see who has it
acquire_android(holder_name="agent-A") # claim
... do work; tools refresh idle timer ...
release_android(holder_name="agent-A") # explicit release
```

10 minutes of idle auto-releases.

### File transfer between host and phone

```
push_file(host_path="C:\\\\reports\\\\test.txt", device_path="/sdcard/test.txt")
pull_file(device_path="/sdcard/screenshots/foo.png", host_path="/tmp/foo.png")
```

Both sides need absolute paths. `push_file` size limit 300s timeout (large APKs use `install_apk` instead, which is APK-aware).

## Recipes (battle-tested on real deploys)

### Recipe: when 2+ blind taps miss, dump UI -- don't keep guessing

**The single biggest time-saver.** Visual coordinate estimation from a screenshot is ±50px at best (especially when the screenshot is rendered at thumbnail size). Modern apps' touch targets are often smaller. If your first 1-2 taps don't produce a state change, **stop tapping and dump the UI hierarchy** to get exact bounds:

```
adb_shell("uiautomator dump /sdcard/ui.xml")
adb_shell("cat /sdcard/ui.xml | tr '>' '\n' | grep -E 'TARGET_TEXT|TARGET_RESOURCE_ID' | head -5")
```

The XML gives `bounds="[L,T][R,B]"` for every clickable element. Compute center `((L+R)/2, (T+B)/2)`. Real example from a Kuaishou login flow:

- I tapped a checkbox at (135, 2090) — missed (was unchecked still)
- Dumped UI: `protocol_checkbox bounds=[120,2105][168,2153]` → real center (144, 2129)
- Re-tapped at (144, 2129) → checkbox became ✓

The native UI tools `dump_ui_hierarchy`, `find_elements`, and `tap_element` are available — use them directly instead of the manual shell workaround when you need exact element bounds.

### Recipe: read SMS verification code via dual channels

The SMS provider on EMUI / MIUI is permission-gated for `adb shell` — but the notification provider often isn't. Try BOTH; at least one usually works:

```
# Channel 1: notification dump (fast; works even when SMS provider is locked)
adb_shell("dumpsys notification --noredact | grep -A 1 -E 'mms|sms|验证码|verification' | head -20")

# Channel 2: SMS provider (works on most ROMs once an SMS has actually arrived)
adb_shell("content query --uri content://sms/inbox --projection address:body --sort 'date DESC' | head -3")
```

Wait ~5-10s after triggering the SMS before querying. Provider returns "No result found" if there is no message yet — not the same as denial.

### Recipe: send SMS (Unicode-clean) via SENDTO intent

`adb input text` is ASCII-only on most ROMs (Chinese / emoji silently dropped). For SMS specifically, **route around the IME entirely** by passing the body as an Intent extra — bytes go directly from adb to the SMS app via Binder IPC, no keyboard involved:

```
adb_shell("am start -a android.intent.action.SENDTO -d 'smsto:13800138000' --es sms_body '你好，这是中文短信'")
```

The default SMS app opens with recipient + body pre-filled. Then tap the send button (use the UI-dump recipe to find exact bounds — on EMUI 14 / Android 10 it's `button_singlesim_model_parent` at [924,2196][1044,2236] → center (984, 2216)):

```
tap(x=984, y=2216)
```

Verify via the sent provider:

```
adb_shell("content query --uri content://sms/sent --projection address:body:date --sort 'date DESC' | head -3")
```

If a fresh SENDTO arrives while the SMS app is already open on another conversation, you may see `Activity not started, intent has been delivered to currently running top-most instance` — informational, not an error; the composer's recipient + body do swap to the new intent.

**General principle**: Intent extras are a Unicode-safe data channel into Android apps. When you need non-ASCII text in an app's input field and the IME is in the way, look for an intent the app responds to with the right extra (`sms_body`, `android.intent.extra.TEXT` for share intents, `query` for search intents, etc.).

### Recipe: hardware health snapshot

One adb_shell call per subsystem. Use to verify a freshly-deployed test box, or as a sanity check before / after a long test run:

```
adb_shell("dumpsys battery | head -16")                                       # level/voltage/temp/health
adb_shell("wm size; wm density; dumpsys display | grep mScreenBrightness")   # screen
adb_shell("cat /proc/meminfo | head -4")                                      # RAM
adb_shell("nproc; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq") # CPU cores+freq
adb_shell("df -h /data /sdcard 2>&1 | head -5")                               # storage
adb_shell("dumpsys wifi | grep -E 'mWifiInfo|RSSI|LinkSpeed' | head -5")      # WiFi
adb_shell("dumpsys telephony.registry | grep mServiceState= | head -1")       # cellular
adb_shell("getprop gsm.sim.state; getprop gsm.operator.alpha")                # SIM
adb_shell("dumpsys sensorservice | grep -oE 'android\\.sensor\\.[a-z_]+' | sort -u")  # sensor list
```

### Recipe: active hardware drive (vibrate as proof-of-execution)

When you need a physically-perceptible signal that the agent is actually driving the device (e.g. demo, post-deploy verify, "ping" between agent and device admin):

```
adb_shell("cmd vibrator vibrate 800 atb-test")    # 800ms; the second arg is the reason logged
```

Returncode 0 + empty stdout = vibration triggered. The reason string shows up in `dumpsys vibrator` history.

For sensor liveness without raw values (EMUI redacts the values but keeps timestamps):

```
adb_shell("dumpsys sensorservice | grep -A 6 'Recent Sensor events' | head -30")
```

Recent event timestamps prove the sensor is actively sampling; useful for sanity-checking that step counter / accelerometer hardware is alive even when content is `[value masked]`.

## 多设备模式

v0.7.0-alpha 起，单 MCP 入口可同时挂多台手机。默认行为：

- 只连一台手机时，所有工具**自动路由**，无需传 `device`。
- 连了多台手机时，LLM 应当：

  1. 先调 `list_devices()` 查看连接清单（返回 `alias` / `serial` / `brand` / `model` / `in_use`）。
  2. 调工具时传 `device="<别名或serial>"`，例如 `take_screenshot(device="pixel-8")`；
     或先调 `set_default_device(device="pixel-8")` 设置会话级默认，后续省略 `device`。
  3. 并行操作多机时，先 `acquire_android(device="...", holder_name="agent-A")` 拿排他锁，
     操作完调 `release_android(device="...", holder_name="agent-A")`。

别名在 `~/.agent-fleet/android-aliases.json` 中定义，由安装向导自动推断
（格式：`{brand}-{slug(model)}`，重名按 serial 字典序加 `-1/-2`，fallback 为 `phone-N`）。

MCP 握手时 `instructions=` 中已列出当前所有连接设备的摘要；资源
`androidfleet://devices` 可随时获取实时 JSON 快照。

## Common failures and recovery

| Symptom | Cause / fix |
|---|---|
| `no authorized Android device found` | Phone unplugged / USB cable bad / USB debugging not authorized. Plug in, watch the phone for "Allow USB debugging?" prompt, click "Always allow from this computer". |
| `multiple devices attached` (MultipleDevicesError) | Multiple phones connected but no `device` param supplied. Pass `device="<alias or serial>"` or call `set_default_device()` first. |
| `take_screenshot` returns garbage / fallback path used | Some Huawei / OEM ROMs corrupt `exec-out screencap`. Fallback to `screencap -p /sdcard/...` + `adb pull` is automatic. If that also fails, ROM is locked down -- need to grant Developer Options > "Disable permission monitoring". |
| Phone locked (lock screen) | `press_key("wake")` then swipe up via `swipe(540, 1800, 540, 600, 300)` (calibrate to your screen). For PIN-locked phones, type the PIN via `type_text("1234")` after swipe-up. |
| `type_text` Chinese / emoji silently dropped | `adb input text` ASCII-only on most ROMs. v0.4 doesn't ship a Unicode workaround; for now copy text via `push_file` to clipboard or use a third-party IME. |
| `type_text` into a verify-code field gets eaten; permission dialog from IME pops up | OEM-bundled IMEs (Baidu / Sogou on Huawei / Xiaomi) intercept SMS-code fields to ask for SMS read permission. The dialog steals focus before your text reaches the field. Fix: tap "禁止" (~305, 2192 -- size depends on dialog) on the IME permission dialog, dismiss any follow-up "去设置" prompt with "取消", THEN re-issue `type_text`. We already have the code via the SMS recipe above; the IME doesn't need its own SMS access. |
| `MCP error -32602` on every tool | **Should not happen on v0.4.x post-patch** -- the SSE→streamable-http migration eliminated this. If you still see it, your client config is on `"type": "sse"` / `/sse` URL. Re-run `python3 scripts/install-agent-side.py --platform android-device --hostname <HOST>` to rewrite to `"type": "http"` / `/mcp`, then `/exit` + reopen. |
| Service not on 8768 (host = Windows) | `Stop-ScheduledTask MCP-AndroidDevice; Start-ScheduledTask MCP-AndroidDevice` |
| Service not on 8768 (host = macOS) | `launchctl kickstart -k gui/$(id -u)/cc.metahub.android-device` |

## Reference

- Setup: `docs/platforms/android.md` in agent-fleet repo
- Source code: `platforms/android/server/android_device_mcp.py`
- Service log (Win): `<repo>/platforms/android/logs/android-device.log`
- Service log (Mac): same path
- Tool surface: 25 tools across 9 categories (state 3 / session-default 2 / device-info 1 / screen 2 / touch 3 / keyboard 2 / app 6 / shell 1 / file-transfer 2 / ui-introspection 3)

## Red flags

- "I'll use click" -> wrong, phones use `tap`
- "I'll just bump the timeout for this APK install" -> `install_apk` already has 120s; a slow ADB connection means USB or driver issue, not timeout
- "I'll skip acquire/release for one tap" -> fine for one-off; required for multi-step automated tests where another agent might intervene
- "I'll send Chinese text via type_text" -> silently dropped on most ROMs, plan around it (clipboard paste / IME / hardcoded test data)
- "MCP errors are intermittent" -> on streamable-http transport this is rare; if it persists, your client config is still on legacy SSE -- re-run install-agent-side.py + restart Claude Code
- "I'll keep tapping at slightly different coords until something happens" -> after 2 misses, dump UI; visual estimation rarely beats ±50px and modern targets are smaller
- "I'll just type the verify code, the IME won't care" -> on Huawei/Xiaomi the OEM IME WILL pop a permission dialog and eat your input; expect it
