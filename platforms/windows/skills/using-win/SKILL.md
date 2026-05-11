---
name: using-win
description: Use when invoking win-device MCP tools to drive a Windows test machine (agent-test-bench project) -- screenshot-and-click UI testing, long-running shell commands, file or process operations, or coordinating exclusive device use across multiple agents.
---

# Using win-device

Drive a remote Windows test machine via the `win-device` MCP server (FastMCP, SSE transport on Tailscale). Multi-client native; advisory single-holder coordination; ~33 tools spanning state / screen / window / mouse / keyboard / process / file / search / shell.

## Critical patterns

### Screenshot click coordinates are SCREEN pixels, NOT image-display pixels

`take_screenshot` returns a PNG of the **actual screen** (e.g. 1920x1080). The viewer rendering it (Read tool, image preview, etc.) MAY downscale to a smaller display size like 960x540. **Always pass click coordinates in actual screen pixels.**

```
get_screen_size                       # returns {"width": 1920, "height": 1080}
take_screenshot                        # PNG of full screen; rendered display may be smaller
click(x=1096, y=600)                   # x,y MUST be in 1920x1080 space
```

If clicks miss: the displayed image is a thumbnail, not the source of truth. Call `get_screen_size` first; reason about coordinates in that coordinate system.

### Long-running tasks: `start_process`, NOT `run_powershell`

`run_powershell` caps at 60s default (max 600s). For anything that may exceed -- installs, builds, slow networks, downloads:

```
{pid} = start_process(command="...", shell="powershell")
read_process_output(pid=..., offset=-200, length=200)   # tail; poll periodically
# read_process_output's "done" field flips True when process exits, with exit_code
force_terminate(pid)                                     # if abandoned
list_sessions()                                          # see all started_process slots
```

`run_powershell` is fine for one-shot < 60s commands like `Get-Date`, port checks, simple file moves.

### File operation decision tree

| Need | Tool | Note |
|---|---|---|
| Read text file content | `read_file(path, offset, length)` | `offset=-N` returns tail N lines |
| Find string across many files | `start_search(path, pattern)` then `get_more_search_results(search_id)` | regex; returns matches as `{file, line, text}` |
| Tree of directory | `list_directory(path, depth)` | depth=1 for immediate children |
| Find-and-replace inside file | `edit_block(path, old, new, replace_all)` | fails if `old` not unique unless `replace_all=True` |
| Write or append | `write_file(path, content, mode)` | `mode="append"` for log-like usage |

Don't use `start_search` to look up content of a single known file -- use `read_file` directly.

### Multi-agent coordination (advisory)

Tools work for everyone regardless of who claims the device, but `get_winpc_status` reports the current holder. In shared setups, follow this etiquette:

```
get_winpc_status                                    # see who has it
acquire_winpc(holder_name="agent-A")                # claim
... do work; each tool call refreshes idle timer ...
release_winpc(holder_name="agent-A")                # explicit release
```

Holder auto-clears after **10 minutes** of no tool activity. Skip acquire/release for one-off single-tool calls (overhead not worth it for a single screenshot).

## Common failures and recovery

| Symptom | Cause / fix |
|---|---|
| `MCP error -32602: Invalid request parameters` on every tool | **Should not happen on v0.2.x post-patch** -- the SSE→streamable-http migration eliminated this. If you still see it, your client config is on `"type": "sse"` / `/sse` URL. Re-run `python3 scripts/install-agent-side.py --platform win-device --hostname <HOST>` to rewrite to `"type": "http"` / `/mcp`, then `/exit` + reopen. |
| `edit_block` returns `old_string not unique` | Pass `replace_all=True`, or extend `old_string` with surrounding context to make it unique |
| Click landed wrong place | Coordinate system confusion -- call `get_screen_size`; treat displayed image as thumbnail; don't compute coords from rendered dimensions |
| Service not listening on 8766 | Restart task: `run_powershell` calling `Stop-ScheduledTask MCP-WinDevice; Start-ScheduledTask MCP-WinDevice` |
| `mcp__win-device__*` not in available tools | Schema not loaded -- ToolSearch with `select:mcp__win-device__<name>` first |

## Reference

- Setup: `docs/platforms/windows.md` in agent-test-bench repo
- Diagnostic: run `platforms/windows/scripts/diagnose.ps1` on the Windows host
- Tool surface: 33 tools in 9 categories
- Source code: `platforms/windows/server/windows_gui_mcp.py`

## Red flags

- "I'll just use the displayed image's pixel position" → wrong, use `get_screen_size`
- "I'll bump `run_powershell` timeout to 600 for this big install" → fragile, use `start_process` + poll
- "I'll skip acquire/release, this is just one tool call" → fine for single calls; required for multi-step flows
- "MCP errors are intermittent, I'll retry" → on streamable-http transport this is rare; if persists, client config is still on legacy SSE -- re-run install-agent-side.py + restart
