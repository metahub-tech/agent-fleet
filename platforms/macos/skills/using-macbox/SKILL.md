---
name: using-macbox
description: Use when invoking macbox-gui MCP tools to drive a Mac test machine (agent-test-bench project) -- screenshot-and-click UI testing, long-running shell or zsh commands, file or process operations, AppleScript automation, or coordinating exclusive device use across multiple agents.
---

# Using macbox-gui

Drive a remote Mac test machine via the `macbox-gui` MCP server (FastMCP, SSE transport on Tailscale, port 8767). Multi-client native; advisory single-holder coordination; ~30 tools spanning state / screen / mouse / keyboard / process / file / search / zsh / AppleScript.

## Critical patterns

### Screenshot click coordinates are SCREEN pixels, NOT image-display pixels

`take_screenshot` returns a PNG of the actual screen (e.g. 2880x1800 on Retina). The viewer (Read tool, image preview, etc.) MAY downscale for display. **Always use the actual screen resolution for click coordinates.**

```
get_screen_size                       # returns {"width": 2880, "height": 1800}
take_screenshot                        # PNG of full screen; rendered display may be smaller
click(x=1440, y=900)                   # MUST be in 2880x1800 space
```

If clicks miss: call `get_screen_size` first. Note that on Retina displays `pyautogui.size()` returns logical pixels (not physical), and `ImageGrab.grab()` returns physical pixels — they may differ by 2x. Trust `get_screen_size`.

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
| `MCP error -32602: Invalid request parameters` on every tool | SSE session corrupted -- often after a long-running tool blocking the caller. Recovery: `/exit` + reopen Claude Code |
| Click landed wrong place / no effect | Either Accessibility permission not granted, OR coordinate-system confusion. Check `get_screen_size`; verify `Privacy & Security > Accessibility` includes the venv's python3 |
| `take_screenshot` returns black image | Screen Recording permission not granted for the venv's python3 |
| `run_applescript` returns `execution error -1743 (errAEEventNotPermitted)` | Automation permission missing -- expand python3 in Privacy & Security > Automation, tick the controlled app |
| Service not on port 8767 after Mac wake | launchd should auto-restart with KeepAlive. If not: `launchctl kickstart -k gui/$(id -u)/cc.metahub.macbox-gui` |
| `mcp__macbox-gui__*` not in available tools | Schema not loaded -- ToolSearch with `select:mcp__macbox-gui__<name>` first |

## Reference

- Setup: `docs/platforms/macos.md` in agent-test-bench repo
- Source code: `platforms/macos/server/macos_gui_mcp.py`
- launchd plist: `~/Library/LaunchAgents/cc.metahub.macbox-gui.plist`
- Service log: `platforms/macos/logs/macos-gui.log`
- Tool surface: ~30 tools across 9 categories (no `list_windows` family yet -- use `run_applescript` instead)

## Red flags

- "I'll just use the displayed image's pixel position" -> wrong, use `get_screen_size`
- "I'll bump `run_zsh` timeout to 600 for this big install" -> fragile, use `start_process` + poll
- "I'll skip acquire/release, this is just one tool call" -> fine for single calls; required for multi-step flows
- "MCP errors are intermittent, I'll retry" -> -32602 means session is dead, restart Claude Code
- "I'll keep clicking, maybe permission will magically appear" -> macOS won't grant silently. Check the permission panes.
