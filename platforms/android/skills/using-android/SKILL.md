---
name: using-android
description: Use when invoking android-gui MCP tools to drive a real Android device or emulator over ADB (agent-test-bench project) -- screen capture, tap/swipe/keyboard, app install/launch/kill, on-device shell, host<->device file transfer, multi-agent coordination.
---

# Using android-gui

Drive a remote Android device via the `android-gui` MCP server (FastMCP, SSE on Tailscale, port 8768). The server runs on a **PC host** (Windows or macOS), and reaches the phone via **ADB** (USB or Wireless). 16 tools across 7 categories.

## Mental model

```
[You / Agent]  -- SSE -->  [PC Host running android-gui MCP]  -- ADB --> [Android Phone]
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
| Type into a focused input | `type_text("hello world")` | Spaces auto-escaped to `%s`. Newlines / Chinese / emoji NOT supported by `adb input text` -- skip these for v0.4. |
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
| `dir`, `Get-Process`, `python` on the host PC | NOT EXPOSED in this server -- use winpc-gui's `run_powershell` if the Android host is Windows; macbox-gui's `run_zsh` if macOS | Host |

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

## Common failures and recovery

| Symptom | Cause / fix |
|---|---|
| `no authorized Android device found` | Phone unplugged / USB cable bad / USB debugging not authorized. Plug in, watch the phone for "Allow USB debugging?" prompt, click "Always allow from this computer". |
| `multiple devices attached` | v0.4.0 supports only one device. Unplug others, or set `ATB_ANDROID_SERIAL` env var on the host. |
| `take_screenshot` returns garbage / fallback path used | Some Huawei / OEM ROMs corrupt `exec-out screencap`. Fallback to `screencap -p /sdcard/...` + `adb pull` is automatic. If that also fails, ROM is locked down -- need to grant Developer Options > "Disable permission monitoring". |
| Phone locked (lock screen) | `press_key("wake")` then swipe up via `swipe(540, 1800, 540, 600, 300)` (calibrate to your screen). For PIN-locked phones, type the PIN via `type_text("1234")` after swipe-up. |
| `type_text` Chinese / emoji silently dropped | `adb input text` ASCII-only on most ROMs. v0.4 doesn't ship a Unicode workaround; for now copy text via `push_file` to clipboard or use a third-party IME. |
| `MCP error -32602` on every tool | SSE session corrupted. Recovery: `/exit` + reopen Claude Code. |
| Service not on 8768 (host = Windows) | `Stop-ScheduledTask MCP-AndroidGui; Start-ScheduledTask MCP-AndroidGui` |
| Service not on 8768 (host = macOS) | `launchctl kickstart -k gui/$(id -u)/cc.metahub.android-gui` |

## Reference

- Setup: `docs/platforms/android.md` in agent-test-bench repo (planned)
- Source code: `platforms/android/server/android_mcp.py`
- Service log (Win): `<repo>/platforms/android/logs/android-gui.log`
- Service log (Mac): same path
- Tool surface: 16 tools across 7 categories (state / device-info / screen / touch / keyboard / app / shell / file-transfer)

## Roadmap notes

- v0.4.1 will add uiautomator2-backed UI introspection (`dump_ui_xml`, `find_by_resource_id`) behind a feature flag (avoids breaking deploys on locked-down OEM ROMs).
- v0.5 will add multi-device routing (`acquire_android(serial=...)` + per-tool serial param).
- Long-running ops (`start_logcat` / `start_recording`) are planned; until then use `adb_shell("logcat -d")` for one-shot dumps.

## Red flags

- "I'll use click" -> wrong, phones use `tap`
- "I'll just bump the timeout for this APK install" -> `install_apk` already has 120s; a slow ADB connection means USB or driver issue, not timeout
- "I'll skip acquire/release for one tap" -> fine for one-off; required for multi-step automated tests where another agent might intervene
- "I'll send Chinese text via type_text" -> silently dropped on most ROMs, plan around it (clipboard paste / IME / hardcoded test data)
- "MCP errors are intermittent" -> -32602 means session is dead; `/exit` and reopen
