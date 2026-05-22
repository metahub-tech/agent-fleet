---
name: using-ios
description: Use when invoking ios-device MCP tools to drive a real iPhone or iPad over WebDriverAgent (WDA) + pymobiledevice3 (agent-fleet project) -- screen capture, tap/swipe/keyboard, app install/launch/terminate, UI hierarchy introspection, file transfer (sandbox), multi-agent coordination.
---

# Using ios-device

Drive one or more iOS/iPadOS devices via the `ios-device` MCP server (FastMCP, streamable-http on Tailscale, port 8769). The server runs on a **macOS host** (Xcode + WDA requirement), and reaches the device via **WebDriverAgent over USB** (pymobiledevice3 usbmux forward). 26 tools across 9 categories.

## Mental model

```
[You / Agent]  -- streamable-http -->  [macOS host running ios-device MCP]:8769
                                              |
                                       pymobiledevice3 USB forward
                                              |
                                       WebDriverAgent on iOS device
```

You drive the SERVER. The server drives WDA. WDA drives the DEVICE. You don't touch the device directly. WDA must be running on the device before UI tools work (see docs/platforms/ios.md for Xcode build steps).

## Critical patterns

### Coordinates are points (WDA coordinate space)

`get_screen_size` returns the device's logical size in **points** (e.g. `{width: 390, height: 844}` for iPhone 14). `take_screenshot` returns a PNG at point resolution (1x), NOT at the device's physical pixel resolution. `tap(x, y)` uses the same point space. **No scaling needed** on your end — WDA already handles the logical-to-physical mapping.

```
get_screen_size                  # {"width": 390, "height": 844}
take_screenshot                  # PNG also at 390x844 points
tap(x=195, y=422)                # center of screen
```

### tap / swipe / long_press — same naming as android-device

iOS uses touchscreens exactly like Android. Use `tap`, `swipe`, `long_press` — not `click`.

### Keyboard: type_text vs press_key

| What | Tool | Note |
|---|---|---|
| Type into a focused input | `type_text("hello")` | Routes via WDA /wda/keys → UIKit. Supports Unicode. Some custom text fields may not receive it — fall back to tap + clipboard paste if needed. |
| Physical buttons | `press_key(key="home")` | Supported: home, volume_up, volume_down, lock only. No adb-style KEYCODE mapping — iOS exposes only these four physical buttons via WDA. |

### NO adb_shell equivalent on iOS

iOS is sandboxed. There is no `adb_shell`. If you need to run shell commands on the macOS host itself, use mac-device's `run_zsh` tool (separate MCP server, port 8767).

| Need | Tool | Server |
|---|---|---|
| On-device shell | **NOT AVAILABLE** (iOS sandbox) | — |
| Host shell (macmini) | `run_zsh(script=...)` | mac-device (port 8767) |

### App lifecycle

```
list_apps(filter_substring="safari", only_user=False)  # find installed apps
start_app(bundle_id="com.apple.MobileSafari")          # launch via WDA
current_app()                                           # what's in front
terminate_app(bundle_id="com.apple.MobileSafari")      # force-terminate via WDA
activate_app(bundle_id="com.example.MyApp")            # bring to foreground (must be running)
install_ipa(ipa_path="/path/on/machost/foo.ipa")       # install .ipa on device
uninstall_app(bundle_id="com.example.MyApp")            # uninstall
```

`start_app` uses WDA `/wda/apps/launch`; `terminate_app` uses `/wda/apps/terminate`. Both require WDA to be running.

### File transfer: limited to UIFileSharingEnabled apps

iOS sandbox means you can only push/pull files to apps that have `UIFileSharingEnabled=true` (i.e. apps visible in the Files app). System apps and most third-party apps without this flag will reject the operation.

```
push_file_to_app(host_path="/tmp/test.csv", bundle_id="com.example.App", device_relpath="inbox/test.csv")
pull_file_from_app(bundle_id="com.example.App", device_relpath="output/report.pdf", host_path="/tmp/report.pdf")
```

Both `host_path` values are absolute paths on the **macOS host**, not on your agent machine.

### UI hierarchy introspection

```
dump_ui()                      # full XCUIElement JSON tree (type, name, label, value, rect)
find_elements(using="class chain", value='**/XCUIElementTypeButton[`name == "Done"`]')
tap_element(using="accessibility id", value="Login")   # find-and-tap in one call
```

Locator strategies: `class chain` (recommended), `xpath`, `predicate string`, `name`, `accessibility id`. The `rect` in dump results is `{x, y, width, height}` in points — center of element is `(x + width/2, y + height/2)`.

### Multi-agent coordination

```
get_status()                                 # see current holder
acquire(holder_name="agent-A")               # claim
... do work ...
release(holder_name="agent-A")               # explicit release
```

10-minute idle auto-release. Advisory only — tools still work for others.

### Multi-device: device param

When multiple iOS devices are connected to the host:

1. Call `list_devices()` to see connected devices (returns `udid`, `alias`, `model`, `os_version`, `in_use`).
2. Pass `device="<alias|udid>"` to each tool, e.g. `take_screenshot(device="apple-ipad15-7")`.
3. OR call `set_default_device(device="apple-ipad15-7")` once to set a session-wide sticky default.

When only one device is attached, `device` param is optional — all tools auto-route.

Aliases are auto-derived from Apple's `ProductType` (e.g. `iPad15,7` → `apple-ipad15-7`), stored in `~/.agent-fleet/ios-aliases.json`.

## Tool reference (26 tools, 9 categories)

| Category | Tools | Notes |
|---|---|---|
| Device / session state | `acquire` / `release` / `get_status` | Per-device advisory holder lock |
| Session default | `set_default_device` / `get_default_device` | MCP session-scoped sticky default |
| Device list | `list_devices` | udid, alias, model, OS version, in_use |
| Screen | `take_screenshot` / `get_screen_size` | Points (WDA coordinate space), PNG |
| Touch | `tap` / `swipe` / `long_press` | WDA point coordinates |
| Keyboard / buttons | `type_text` / `press_key` | type_text = UIKit; press_key = home/volume_up/volume_down/lock only |
| App lifecycle | `list_apps` / `install_ipa` / `uninstall_app` / `start_app` / `terminate_app` / `activate_app` / `current_app` | install = pymobiledevice3; start/terminate/activate/current = WDA |
| File transfer | `push_file_to_app` / `pull_file_from_app` | UIFileSharingEnabled apps only; host paths are on the macmini |
| UI introspection | `dump_ui` / `find_elements` / `tap_element` | WDA /source + /elements; class chain locator recommended |
| Device info | `device_info` | OS version, build, battery, model via pymobiledevice3 lockdown + diagnostics |

## Common failures and recovery

| Symptom | Cause / fix |
|---|---|
| `no iOS devices found` | Device not plugged in, or 'Trust this computer' not tapped on device. Replug USB + accept Trust prompt. |
| `multiple iOS devices attached` | Multiple devices connected but no `device` param. Pass `device="<alias|udid>"` or call `set_default_device()`. |
| `WDA not reachable` / timeout on `get_screen_size` | WDA is not running. Launch it in Xcode (scheme `WebDriverAgentRunner` on your device) or via `xcodebuild test`. See docs/platforms/ios.md. |
| `take_screenshot` hangs then errors | WDA forwarder subprocess died. Call `get_screen_size` first to trigger a reconnect, then retry. |
| `type_text` doesn't land | Some apps use custom text rendering that bypasses UIKit key injection. Workaround: tap a standard text field first, then type. Or use clipboard paste via run_zsh + pbcopy on the host. |
| `press_key(key="menu")` fails | Only home / volume_up / volume_down / lock are supported. There is no Android-style KEYCODE_MENU on iOS. |
| `push_file_to_app` returns permission error | Target app does not have `UIFileSharingEnabled=true`. You cannot push files to sandboxed system apps. |
| Service not on 8769 | `launchctl kickstart -k gui/$(id -u)/cc.metahub.ios-device` |

## iOS-specific notes

- **No `adb_shell`** — iOS is sandboxed. For host-side shell use mac-device's `run_zsh`.
- **`press_key` only supports 4 buttons**: home, volume_up, volume_down, lock. No menu/back/recent.
- **File transfer is sandbox-limited** to UIFileSharingEnabled apps (visible in Files.app on device).
- **WDA must be running** before any UI/screen/input tools work. It is NOT started by the MCP server — it must be deployed and started separately (Xcode or xcodebuild). See docs/platforms/ios.md.
- **`type_text` supports Unicode** (WDA /wda/keys → UIKit), unlike Android's `adb input text` which is ASCII-only.
- **Points vs pixels**: WDA returns logical points, not physical pixels. A 3x Retina display iPhone 14 has 1170×2532 physical pixels but WDA reports 390×844 points. Coordinates in all tools are POINTS.

## Reference

- Setup: `docs/platforms/ios.md` in agent-fleet repo
- Source code: `platforms/ios/server/ios_device_mcp.py`
- Service log: `platforms/ios/logs/ios-device.log`
- Tool surface: 26 tools across 9 categories

## Red flags

- "I'll use `adb_shell`" → no equivalent on iOS; use mac-device `run_zsh` for host-side shell
- "I'll use `click`" → wrong; iOS uses `tap`
- "I'll type in physical pixel coordinates" → WDA uses points not pixels; divide by screen scale (~3x for most modern iPhones)
- "I'll push a file to system app Documents" → won't work; iOS sandbox limits file access to UIFileSharingEnabled apps
- "The screenshot returns but taps don't register" → check WDA is still alive; forwarder may have dropped. Call `get_screen_size` to trigger reconnect.
- "I'll press the back button" → iOS has no back button in WDA; use `press_key(key="home")` or swipe gesture to navigate
