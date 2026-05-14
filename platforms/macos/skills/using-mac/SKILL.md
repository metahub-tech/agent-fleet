---
name: using-mac
description: Use when invoking mac-device MCP tools to drive a Mac test machine (agent-fleet project) -- screenshot-and-click UI testing, long-running shell or zsh commands, file or process operations, AppleScript automation, or coordinating exclusive device use across multiple agents.
---

# Using mac-device

Drive a remote Mac test machine via the `mac-device` MCP server (FastMCP, SSE transport on Tailscale, port 8767). Multi-client native; advisory single-holder coordination; 31 tools spanning state / screen / mouse / keyboard / process / file / search / zsh / AppleScript.

## Critical patterns

### Screenshot pixels == click pixels (logical / point space)

`take_screenshot` is sized to **logical pixels** (e.g. 1440x900 on a Retina MacBook), matching `click(x, y)` and `get_screen_size`. So coordinates from a screenshot can be passed directly to `click` without scaling. This is implemented server-side: the raw `ImageGrab` capture is physical (2880x1800) but the tool resizes before returning.

```
get_screen_size                       # {"width": 1440, "height": 900}  -- logical
take_screenshot                        # PNG also at 1440x900
click(x=720, y=450)                    # center; same space as screenshot
```

If clicks miss anyway: usually a permission issue, NOT a coordinate issue. Verify Accessibility is granted (System Settings > Privacy & Security > Accessibility shows Python.app, switch on).

### macOS modifiers: `cmd`, not `ctrl`

`press_key("cmd+s")` saves; `press_key("cmd+space")` opens Spotlight. `paste_text` already uses Cmd+V internally. Modifier aliases:

| You write | pyautogui receives |
|---|---|
| `cmd` | `command` |
| `option` / `alt` | `option` |
| `ctrl` | `ctrl` |
| `shift` | `shift` |

### Long-running tasks: `start_process`, NOT `run_zsh`

`run_zsh` caps at 60s (max 600s). For builds, installs, slow networks:

```
{pid} = start_process(command="...", shell="zsh")
read_process_output(pid=..., offset=-200, length=200)   # tail; poll periodically
force_terminate(pid)                                     # if abandoned
list_sessions()                                          # see all started_process slots
```

`run_zsh` is fine for one-shot < 60s commands like `date`, port checks, simple file moves.

### Controlling other apps: `run_applescript`

For window manipulation, app activation, dialog automation:

```
run_applescript(script='tell application "Safari" to activate')
run_applescript(script='''
    tell application "System Events"
        tell process "Safari"
            keystroke "l" using {command down}
            delay 0.2
            keystroke "https://example.com"
            keystroke return
        end tell
    end tell
''')
```

**Requires Automation permission** (System Settings > Privacy & Security > Automation). First call to a new app triggers a system permission dialog — user must click Allow. Subsequent calls work permanently.

### File operation decision tree

| Need | Tool |
|---|---|
| Read text file content | `read_file(path, offset, length)` -- supports `~` expansion |
| Find string across many files | `start_search(path, pattern)` then `get_more_search_results(search_id)` |
| Tree of directory | `list_directory(path, depth)` |
| Find-and-replace inside file | `edit_block(path, old, new, replace_all)` -- fails if `old` not unique unless `replace_all=True` |

Don't use `start_search` for known single-file content lookups -- use `read_file` directly.

### Avoid scanning protected user-data directories

macOS Privacy independently gates each of: `~/Documents`, `~/Desktop`, `~/Downloads`, `~/Pictures/Photos Library`, `~/Library/Calendars`, `~/Library/Reminders`, `~/Library/AddressBook`. Each first access triggers a separate prompt. **Don't `find ~ -maxdepth N` blindly** -- it'll fan out into all of them.

Best practice for mac-device workflows:
- Scope `start_search` and `list_directory` to the project's actual workspace dir (e.g. `~/qjl-workspace/...`, `~/code/...`).
- Use `run_zsh "ls -d ~/*workspace* ~/code 2>/dev/null"` to discover candidate roots before scanning.
- If broad access is genuinely needed, ask the operator to grant Python.app **Full Disk Access** once -- it covers Documents/Desktop/Downloads/all of ~/Library, but NOT Photos / Calendar / Reminders / Contacts (which agents shouldn't touch anyway).

### Recipe: smoke-test a GUI .app bundle

The canonical end-to-end pattern after the operator hands you an .app path:

```
# 1. Strip Gatekeeper quarantine if downloaded via browser/Safari (curl
#    via API doesn't set it; AirDrop / Safari / DMG-mount do).
run_zsh("xattr -dr com.apple.quarantine /path/to/Foo.app 2>/dev/null || true")

# 2. Launch
open_app(app="/path/to/Foo.app")            # uses macOS `open -a` semantics

# 3. Confirm process tree (Electron typically spawns Helper / GPU / Renderer)
run_zsh("pgrep -fl 'Foo' | head -10")

# 4. First screenshot once UI settles
sleep ~3-5s server-side or wait briefly client-side
take_screenshot()

# 5. Discover the window via System Events (verifies app is visible)
run_applescript("tell application \"System Events\" to get name of every window of process \"Foo\"")

# 6. Click / type / press_key as needed for flows
```

If the app is unsigned and HAS a quarantine xattr, `open` will be blocked by Gatekeeper. Either remove the xattr (above) or `spctl --add /path/to/Foo.app`. For repeat-use test machines, removing quarantine once is fine; for prod-user simulation, leave it on to verify the dialog works.

### Multi-agent coordination (advisory)

Tools work for everyone regardless of who claims the device, but `get_mac_status` reports the current holder:

```
get_mac_status                                      # see who has it
acquire_mac(holder_name="agent-A")                  # claim
... do work; each tool call refreshes idle timer ...
release_mac(holder_name="agent-A")                  # explicit release
```

Holder auto-clears after 10 minutes of no tool activity. Skip acquire/release for one-off single-tool calls.

## macOS-specific failures and recovery

| Symptom | Cause / fix |
|---|---|
| `MCP error -32602: Invalid request parameters` on every tool | **Should not happen anymore as of v0.4.x** -- the SSE→streamable-http migration eliminated the long-task / middle-box keepalive failure mode that caused this. If you still see it, your client config is on `"type": "sse"` / `/sse` URL. Re-run `python3 scripts/install-agent-side.py --platform mac-device --hostname <HOST>` to rewrite to `"type": "http"` / `/mcp`, then `/exit` + reopen. |
| Click landed wrong place / no effect | Accessibility permission not granted. The .app must be `<brew_prefix>/opt/python@3.12/Frameworks/Python.framework/.../Resources/Python.app` (NOT the venv's bin/python3 symlink, which macOS rejects) |
| `take_screenshot` returns black image | Screen Recording permission not granted; same `.app` rule as Accessibility |
| `run_applescript` returns `execution error -1743 (errAEEventNotPermitted)` | Automation permission missing -- expand python3 in Privacy & Security > Automation, tick the controlled app |
| `run_applescript` returns `osascript 不允许辅助访问 (-25211)` | TCC traced responsibility back to python (osascript inherits from parent). Fix: System Settings > Privacy & Security > Accessibility, ensure BOTH `Python` (symlink-path entry) AND `python3.12` (Cellar-path entry) are ticked. The first prompt only adds one of them; the cross-app accessibility query triggers a second prompt for the other. After both are granted, cross-app window enumeration (`count windows of process X`, etc.) works. |
| Service not on port 8767 after Mac wake | launchd should auto-restart with KeepAlive. If not: `launchctl kickstart -k gui/$(id -u)/cc.metahub.mac-device` |
| `mcp__mac-device__*` not in available tools | Schema not loaded -- ToolSearch with `select:mcp__mac-device__<name>` first |

## Reference

- Setup: `docs/platforms/macos.md` in agent-fleet repo
- Source code: `platforms/macos/server/mac_device_mcp.py`
- launchd plist: `~/Library/LaunchAgents/cc.metahub.mac-device.plist`
- Service log: `platforms/macos/logs/mac-device.log`
- Tool surface: ~30 tools across 9 categories (no `list_windows` family yet -- use `run_applescript` instead)

## Red flags

- "I'll just use the displayed image's pixel position" -> wrong, use `get_screen_size`
- "I'll bump `run_zsh` timeout to 600 for this big install" -> fragile, use `start_process` + poll
- "I'll skip acquire/release, this is just one tool call" -> fine for single calls; required for multi-step flows
- "MCP errors are intermittent, I'll retry" -> on v0.4.x+ streamable-http transport this is rare; if it persists, your client config is still on legacy SSE -- re-run install-agent-side.py and restart Claude Code
- "I'll keep clicking, maybe permission will magically appear" -> macOS won't grant silently. Check the permission panes.
