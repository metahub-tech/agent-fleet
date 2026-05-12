# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.1-alpha] - 2026-05-12

### Added
- **Android UI element introspection** (`platforms/android/server/android_mcp.py`):
  - `dump_ui_hierarchy()` — runs `uiautomator dump`, parses XML, returns flat element list with `bounds` / `center` / `text` / `resource_id` / `content_desc` / `clickable` / etc.
  - `find_elements(text=, resource_id=, content_desc=, class_name=, clickable_only=)` — substring-match filter across all elements, AND logic.
  - `tap_element(...)` — find-and-tap convenience; taps the center of the matched element instead of hardcoded pixel coordinates.
- **macOS UI element introspection** (`platforms/macos/server/macos_gui_mcp.py`) via pyobjc-framework-ApplicationServices:
  - `list_ui_elements(app=, max_depth=)` — walks an app's accessibility tree, returns elements with `role` / `title` / `label` / `position` / `size` / `center`.
  - `find_ui_element(app=, title=, role=, label=)` — filter by AX attributes.
  - `click_ui_element(...)` — find-and-click convenience.

### Why
v0.6.0-alpha end-to-end test surfaced that visual pixel estimation from screenshots is brittle: the agent missed the camera shutter button on the first try (tapped the "拍照" mode tab instead). Element-driven automation lets the agent look up controls by semantic attributes (text / role / resource-id), insulating from layout changes and screen resolution differences.

### Migration
No breaking changes. New tools added; existing tools unchanged. To get the new tools, re-run `agent-fleet setup` on each device (re-installs the venv with refreshed `requirements.txt` for the new pyobjc dep, then restarts the MCP server).

---

## [0.6.0-alpha] - 2026-05-12

### Breaking
- Renamed MCP role IDs: `macbox-gui` → `mac-device`, `winpc-gui` → `win-device`, `android-gui` → `android-device`. Existing users must update `~/.claude.json` `mcpServers` keys, redo the `agent-fleet setup` wizard, and let the new setup scripts clean up old launchd / Task Scheduler / systemd entries.
- Renamed service identifiers: launchd label `cc.metahub.macbox-gui` → `cc.metahub.mac-device`; Windows Task Scheduler `MCP-WindowsGui` → `MCP-WinDevice`, `MCP-AndroidGui` → `MCP-AndroidDevice`; Linux systemd unit `atb-android-gui.service` → `agent-fleet-android-device.service`.
- Renamed skills: `using-macbox` → `using-mac`, `using-winpc` → `using-win`.

### Added
- macOS TCC permission primer: wizard auto-triggers Accessibility / Screen Recording / Automation dialogs so Python.app pre-appears in System Settings (just toggle the switch, no manual drag).

### Migration
Old setup scripts auto-clean their legacy services when re-run. To migrate manually:
- macOS: `launchctl unload ~/Library/LaunchAgents/cc.metahub.macbox-gui.plist 2>/dev/null; rm -f ~/Library/LaunchAgents/cc.metahub.macbox-gui.plist`
- Windows: `Unregister-ScheduledTask -TaskName MCP-WindowsGui -Confirm:$false; Unregister-ScheduledTask -TaskName MCP-AndroidGui -Confirm:$false`
- Linux: `systemctl --user stop atb-android-gui.service; systemctl --user disable atb-android-gui.service; rm -f ~/.config/systemd/user/atb-android-gui.service; systemctl --user daemon-reload`

## [Unreleased]

### Changed
- **🚨 BREAKING (transport): SSE → streamable-http for all 3 platforms.** Long-task `-32602` bug rooted out. SSE was a long-lived event channel; under Tailscale DERP relay or NAT middle-boxes, idle keepalive timed out at ~60-120s. When that happened the client kept its old `session_id` (the MCP SSE protocol has no auto-reconnect at the SDK level), the server didn't know it, and every subsequent call returned `-32602` until `/exit` + reopen Claude Code. Documented as a known issue across 3 skills as "/exit + reopen" workaround. Now fixed at the root: server transports flipped from `transport="sse"` to `transport="http"` (FastMCP's `streamable-http` alias) and client URLs from `:port/sse` to `:port/mcp`. streamable-http uses per-request streams instead of a long-lived event channel, so a stale connection is just one bad request away from auto-reconnect, not a session-killer. **Migration steps for existing deploys**:
  1. Device hosts: `git pull` + restart service (Win Task Scheduler `MCP-WindowsGui` / `MCP-AndroidGui`; macOS `launchctl kickstart -k gui/$UID/cc.metahub.macbox-gui` / `cc.metahub.android-gui`). The new code binds the same port, just on `/mcp` path instead of `/sse`.
  2. Agent hosts: re-run `python3 scripts/install-agent-side.py --platform <name> --hostname <host>` for each. The installer now writes `"type": "http"` + `/mcp` URL; backs up `~/.claude.json` with timestamp before overwriting. Then `/exit` + reopen Claude Code.
- All examples (`platforms/<plat>/examples/claude-settings.json` × 3, top-level `examples/multi-platform-claude-settings.json`) and docs (`docs/agent-host-setup.md`, `docs/install-pattern.md`, the 3 skill `SKILL.md` files) updated to reflect the new transport. The 3 skills' `-32602` failure rows now point at "your client config is still on legacy SSE -- re-run install-agent-side.py" rather than the old `/exit + reopen` workaround. New anti-pattern entry in `docs/install-pattern.md` § 6: don't use SSE for long tasks.
- Diagnosed by an external agent during a live macbox-gui session that hit `-32602` after a long tool call; verified against FastMCP 3.2.4 source (`run_http_async` accepts `transport in {"http","sse","streamable-http"}`; default `streamable_http_path = "/mcp"`); confirmed Claude Code accepts `"type": "http"` (alias for `"streamable-http"`).

### Added
- **🆕 Android platform bridge (v0.4.0).** Single-device pure-ADB implementation. No uiautomator2 / scrcpy dependency in v0.4 -- avoided to keep first deploys working on locked-down OEM ROMs (Huawei HarmonyOS / MIUI etc.). Tools: 16 across 7 categories (state 3 / device 1 / screen 2 / touch 3 / keyboard 2 / app 6 / shell 1 / file 2). Works on either Windows (PowerShell setup script) or macOS (bash setup script, lands in v0.4.1) host. ADB connection mode (USB / Wireless Debugging / Hybrid) is operator's choice at install, persisted to `~/.atb-android/config.toml`; the server itself is mode-agnostic. First validation: Huawei P30 Pro VOG-AL00 (HarmonyOS 4.0 / EMUI 14, reports as Android 10 / SDK 29 -- meaning native Wireless Debugging is unavailable on this phone, USB or Hybrid only).
- `platforms/android/server/{android_mcp.py, requirements.txt, pyproject.toml}` (~600 lines server, deps: fastmcp + pillow + pydantic only).
- `platforms/android/scripts/setup-android.ps1` (Win11 host) + `_launch-android.ps1` -- 9-stage setup, idempotent, mirrors winpc-gui's Task Scheduler + restart-loop pattern. Asks ADB mode and writes `~/.atb-android/config.toml`.
- `platforms/android/scripts/setup-android.sh` (macOS host) + `_launch-android.sh` -- 8-stage symmetric setup using brew + launchd. Inherits all the macOS Tier-3 brew tolerance (ERR trap, dir-permission preflight, `|| true` on brew install) from setup-macos.sh. launchd plist invokes venv python directly (no bash hop). Per-launch `ATB_ANDROID_ADB` env var so the server doesn't have to re-resolve adb at startup. NOTE for macOS hosts: this server does NOT need Accessibility / Screen Recording / Automation grants (it doesn't capture anything on the Mac itself; only shells out to adb).
- `platforms/android/skills/using-android/SKILL.md` -- mental model (you drive server, server drives ADB, ADB drives phone), tap-not-click, app lifecycle pattern, multi-agent coord.
- `platforms/android/examples/claude-settings.json` mirrors the windows / macos pattern.
- `scripts/install-agent-side.py` PLATFORMS dict gains `android-gui`.
- `examples/multi-platform-claude-settings.json`: `_planned_android` is now real `android-gui`; legend updated.

### Added
- **🎯 Developer-facing baseline doc + one-command agent-side installer.** New repo-level entrypoints that let someone who just cloned the repo install the MCP server and skill correctly without reading 5 platform docs first:
  - `docs/install-pattern.md` (~200 lines): two roles, two install paths, directory contract, "add new platform in 8 steps" recipe, anti-patterns, recommended reading order.
  - `scripts/install-agent-side.py`: cross-platform Python script. `python3 scripts/install-agent-side.py --platform macbox-gui --hostname mac-test` does (1) timestamped backup of `~/.claude.json` (2) merges the SSE entry into `mcpServers` (3) symlinks `platforms/<dir>/skills/using-<name>` into `~/.claude/skills/`. Idempotent (re-run reports "ok already configured"). `--dry-run` previews without writing. Refuses to overwrite invalid JSON or non-symlink files at the skill destination.
  - README `快速开始` section now points new joiners at install-pattern.md FIRST.
  - `docs/agent-host-setup.md` § 3.4 documents the one-liner.
- **🆕 platforms/android/ skeleton (v0.4 placeholder).** Empty directories with `.gitkeep` files documenting what each will hold (server / scripts / skills / examples), plus a `README.md` describing the planned architecture, tool surface, and dev-loop. Mirrors windows/ and macos/ structure exactly so adding the real code is a port not a fresh design.

### Changed
- **Version-number cleanup across `README.md` and `docs/roadmap.md`.** Reality: Windows shipped v0.2 (consolidated), macOS shipped v0.3, Android moved to v0.4, iOS moved to v0.5, cross-device coord moved to v0.6. README ASCII diagram, status table, "快速开始" role table, and 目录布局 all reflect this. Roadmap gets dated v0.2/v0.3 sections describing what actually shipped (not the original guesses) and bumps Android/iOS/cross-device version numbers down by one.
- **`docs/agent-host-setup.md` § 3.3 generalized from Windows-only to multi-platform.** Now lists acquire/release/status tools for every released platform in a table, not just `acquire_winpc`.
- **`platforms/macos/examples/`** is no longer empty -- mirrors windows/examples by adding `claude-settings.json` with the macbox-gui SSE entry skeleton.

### Fixed
- **macOS docs explicitly recommend Full Disk Access + warn against granting Photos / Calendar / Reminders / Contacts.** First-deploy session triggered 5 separate per-folder prompts (照片 / 桌面 / 日历 / 提醒事项 / 文稿) the moment a probe ran `find ~ -maxdepth 3`, which surprised the operator. Two doc updates: (1) `docs/platforms/macos.md` § 4.3.8 introduces the capability-vs-user-data permission split and recommends one-shot Full Disk Access for Python.app to cover Documents / Desktop / Downloads / all of ~/Library; warns operators to refuse Photos / Calendar / Reminders / Contacts since agent-driven testing doesn't need them. (2) `using-macbox` skill gets a "Avoid scanning protected user-data directories" subsection that tells agents to scope `start_search` / `list_directory` to known workspace roots, not blanket-scan home, and to use `run_zsh "ls -d ~/*workspace* ~/code"` for discovery instead.
- **macOS Accessibility / Screen Recording: explain why brew's symlink path and Cellar resolved path produce TWO TCC entries.** First-deploy users see "Python" entry from dragging in the .app bundle (recorded under symlink path `/usr/local/opt/python@3.12/.../Python.app`), then a second prompt auto-adds "python3.12" (recorded under resolved Cellar path `/usr/local/Cellar/python@3.12/<ver>/.../Python.app/Contents/MacOS/Python`). Both must be ticked. macOS uses the canonicalized exec path as TCC key, but the Privacy panes only accept `.app` bundles when manually adding -- so the symlink-path entry never matches at runtime. Deferred grant via auto-prompt is what makes the second (correct) entry appear. Verified end-to-end: after adding python3.12 to Accessibility, cross-app AppleScript window enumeration (`tell application "System Events" to count windows of process X`) succeeds. The previously-documented "TCC -25211 limit" in this file was a misdiagnosis from incomplete grant -- removed. New section 4.3.7 in `docs/platforms/macos.md` explains the symlink/Cellar duality so future deploys know both prompts are normal and not a bug.
- **macOS docs now warn loudly about `launchctl bootout gui/$UID` without a plist path.** Real-incident from a Mac deployment: a multi-line copy-paste of `launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/cc.metahub.macbox-gui.plist` got split at the newline and bash executed `launchctl bootout "gui/501"` as a standalone command -- which Apple defines as "remove every LaunchAgent in the user's GUI domain", causing immediate logout + black screen + return to login window. New section 7.0.5 in `docs/platforms/macos.md` documents the correct restart sequences (`kickstart -k` for code reload; `bootout`+`bootstrap` for plist changes) with explicit single-line warnings. Section 6 (Uninstall) also got the same warning prepended.
- **launchd plist now invokes the venv python directly, no `bash` wrapper.** macOS TCC walks the responsible-process chain to decide which binary needs Accessibility / Screen Recording permission. With the previous `launchd -> /bin/bash _launch-macos-gui.sh -> python` chain, TCC asked the user to grant `bash` permission *in addition* to Python.app -- a confusing second prompt that wasn't explained anywhere in the docs. Plist `ProgramArguments` is now `[$VENV_PY, $SERVER_PY]`, so the chain is just `launchd -> python` and only Python.app needs perms. `_launch-macos-gui.sh` is kept in the repo as a CLI debug entry point (`bash _launch-macos-gui.sh`) for inspecting startup behavior outside launchd; not in the launchd path anymore.
- **`take_screenshot` now returns logical-pixel images** matching `click(x, y)` and `get_screen_size`. Previously the raw `ImageGrab.grab()` returned physical pixels (2880x1800 on Retina) while `pyautogui.click` used logical (1440x900) -- so an agent reading the screenshot would compute coordinates that landed off-screen or in the wrong quadrant. The tool now resizes the capture to logical size before returning.
- **GUI-permission docs now point to the framework `Python.app`, not the venv's `bin/python3` symlink.** macOS Privacy & Security > Accessibility / Screen Recording panes refuse symlinks and CLI binaries (the entry shows up greyed out). The brew framework Python ships a `Python.app` at `<brew_prefix>/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app` which IS draggable. `setup-macos.sh` now resolves and prints this path at the end of the run; `docs/platforms/macos.md` § 4 calls out the trap explicitly with both Intel and Apple-Silicon paths.
- **`docs/platforms/macos.md` validation snippets no longer hard-code `~/agent-test-bench`** -- they use `<repo>/platforms/macos/server/.venv/bin/python3` so users with a non-default clone path (e.g. `~/code/agent-test-bench`, `~/qjl-workspace/agent-test-bench`) don't get a confusing `No such file or directory`.
- **`setup-macos.sh` no longer dies silently on brew permission glitches or Tier-3 (macOS 12) brew oddities.** Three changes: (1) An ERR trap now prints which step exploded and the failing line -- `set -e` previously killed the script with no output, leaving first-time users guessing. (2) New `[0/5]` pre-flight checks `/usr/local/share`, `/usr/local/lib`, `/usr/local/Cellar`, `/usr/local/var/homebrew` writability and prints the exact `sudo chown -R` command if any is owned by root (the most common macOS 12 trap). (3) `brew install python@3.12` is now wrapped in `|| true`; success is verified by direct binary existence check (`brew --prefix python@3.12/bin/python3.12`, with fallbacks to `/usr/local/bin/python3.12` and `/opt/homebrew/bin/python3.12`) -- brew's exit code on Tier-3 macOS is unreliable. New troubleshooting section 7.0 in `docs/platforms/macos.md` documents the root causes.

### Added
- **🆕 macOS platform bridge (v0.3.0 base).** New `macbox-gui` MCP server in `platforms/macos/`, mirroring the Windows architecture: FastMCP on SSE, port 8767, advisory acquire/release state model (`acquire_mac` / `release_mac` / `get_mac_status`), ~30 tools across state / screen / mouse / keyboard / process / file / search / shell. Mac-specific: `open_app` instead of `launch_app` (uses `open -a`); `run_zsh` + `run_applescript` instead of `run_powershell`; `press_key` accepts `cmd` / `option` aliases. Tools missing in v0.3.0 (deferred to a later minor): `list_windows` / `inspect_window` / `focus_window` -- on Windows these come from pywinauto; macOS equivalents need AppleScript or NSAccessibility, currently reachable indirectly via `run_applescript`.
- `setup-macos.sh` provisions Tailscale + brew Python + venv + a launchd plist (`~/Library/LaunchAgents/cc.metahub.macbox-gui.plist`). launchd's native `KeepAlive={Crashed=true,SuccessfulExit=false}` + `ThrottleInterval=3` gives us free crash-restart and rate-limiting -- no need for the while-loop launcher hack the Windows side has. The bash launcher (`_launch-macos-gui.sh`) is therefore much thinner: it just `exec`s python and lets launchd handle restart.
- `using-macbox` skill at `platforms/macos/skills/using-macbox/SKILL.md`. Same structure as `using-winpc` (coordinate scaling / long task pattern / multi-agent coordination / common failures), specialized for macOS gotchas (Cmd vs Ctrl, Accessibility / Screen Recording / Automation permission grants, AppleScript automation).
- `docs/platforms/macos.md` setup guide (~150 lines): 7-section walkthrough including the GUI permission grant procedure, validation snippets, common failures, and uninstall steps.
- `examples/multi-platform-claude-settings.json` updated: `macbox-gui` is now a real entry; updated comment to reflect winpc-gui (v0.2) + macbox-gui (v0.3) both being live.

### Changed
- **🚀 Consolidated `winpc-shell` into `winpc-gui` (single MCP server architecture).** Previously the Windows bridge ran two MCP services side-by-side: `winpc-gui` on 8766 (FastMCP, our own GUI tools) and `winpc-shell` on 8765 (mcp-proxy + npm `desktop-commander` providing shell / file / process tools). The `winpc-shell` chain hit several upstream issues over the past iterations (single-client lockout when one agent holds the SSE connection; npm `_npx` cache ENOTEMPTY race on Task Scheduler restart; supergateway IPv6-only bind requiring `netsh portproxy`; mcp-proxy default-mode tying stdio child lifetime to the first SSE client; puppeteer postinstall failing on restricted networks). v0.2 ports the desktop-commander tools — `read_file`, `write_file`, `edit_block`, `list_directory`, `create_directory`, `move_file`, `get_file_info`, `start_process`, `read_process_output`, `interact_with_process`, `force_terminate`, `list_sessions`, `start_search`, `get_more_search_results`, `list_searches`, `stop_search` — into Python inside `windows_gui_mcp.py`. FastMCP supports multi-client SSE natively, so multiple agents can connect simultaneously without the supergateway-style lockout. Net effect: one service instead of two, no Node.js / npm dependency, no portproxy, no mcp-proxy, no per-launch download race. setup-windows.ps1 step 0 cleans up all v0.1 leftovers (old scheduled task, firewall rule, npm globals, portproxy entry, dead launcher script).
- **In-use state model (`acquire_winpc` / `release_winpc` / `get_winpc_status`).** Foundation for multi-agent coordination on a shared Windows test machine. Module-level holder state with 10-minute idle timeout; advisory enforcement (tools work for everyone, but status reports who claimed it). Each tool call refreshes the holder's `last_used_at`. v0.5 plans hard enforcement (reject calls from non-holder when set). Three new tools at the top of the tool list.
- Replaced supergateway with mcp-proxy as the stdio→SSE bridge for desktop-commander. supergateway 3.4.3 has a fatal design bug: it tries to reuse the same MCP `Server` (`Protocol`) instance across SSE connections, so the second SSE client gets `Error: Already connected to a transport. Call close() before connecting to a new transport, or use a separate Protocol instance per connection.` and the process exits with code 1. Claude Code reconnects SSE on every session restart, so every restart killed the bridge. mcp-proxy (Python, `sparfenyuk/mcp-proxy`) is designed for repeated client connections, plus it natively binds `0.0.0.0` via `--sse-host` (no more netsh portproxy workaround) and lives in the same Python venv we already maintain for windows-gui (one fewer toolchain).
- `requirements.txt` adds `mcp-proxy>=0.4`.
- `setup-windows.ps1` step 3 no longer installs supergateway globally; only desktop-commander stays on `npm -g`. If supergateway is detected from a prior version of the script, it is uninstalled.
- `setup-windows.ps1` step 5 stops adding the netsh `v4tov6` portproxy entry (and removes any leftover one).
- `_launch-desktop-commander.ps1` now invokes `python -m mcp_proxy --sse-host 0.0.0.0 --sse-port 8765 -- desktop-commander` and uses `Tee-Object -Append` instead of `*>> $Log` redirection (the latter wrote UTF-16 LE under PowerShell 5.1, mojibake-ing the log so the supergateway crash trace was unreadable until decoded with `[System.Text.Encoding]::Unicode`).
- `diagnose.ps1` section 5b inverted: now expects "no legacy portproxy entry"; warns if one is left over.

### Fixed
- **`_launch-windows-gui.ps1` now wraps python.exe in a restart loop.** Rationale: when Windows kills our python.exe externally (session lock, modern standby, log-off; observed exit code 1067 = `ERROR_PROCESS_ABORTED`), Task Scheduler's `-RestartCount` does NOT trigger because the launcher action itself is still running its `& python` call. The `AtLogOn` trigger also doesn't re-fire on lock/unlock. Result: service stays dead until manual `Start-ScheduledTask`. Loop respawns python within 3s after any external kill, with a rapid-fail safety (3 crashes within 6s = give up, so config errors stay observable). Same pattern we used for the v0.1 mcp-proxy launcher.
- **Documentation pointed at the wrong file for Claude Code MCP config.** `docs/agent-host-setup.md`, `examples/multi-platform-claude-settings.json`, and `platforms/windows/examples/claude-settings.json` all said to merge `mcpServers` into `~/.claude/settings.json`. Claude Code actually reads MCP config from `~/.claude.json` (the top-level single-file state) and `<repo>/.mcp.json` (project-level); `mcpServers` placed in `~/.claude/settings.json` is silently ignored. Verified empirically: editing `settings.json` left `/mcp` showing only built-in plugin servers; moving the same block to `~/.claude.json` made `winpc-shell` and `winpc-gui` connect on next session start. All four files updated, with an added inline warning explaining the trap.
- **Setup script was killing svchost.exe and taking Tailscale down with it.** The user reported Tailscale stopping every time `setup-windows.ps1` reached step 5/6, with the daemon log showing `Got Windows Service event: Stop`. Root cause traced to step 6's port-cleanup loop:
  ```powershell
  Get-NetTCPConnection -LocalPort 8765,8766 -State Listen | ForEach-Object {
      Stop-Process -Id $_.OwningProcess -Force
  }
  ```
  This was supposed to kill leftover MCP service instances. After we added `netsh interface portproxy v4tov6` (the IPv4-IPv6 bridge for supergateway's IPv6-only bind), port 8765 has two listeners: `node.exe` (supergateway, on `::`) AND `svchost.exe` hosting the IP Helper service `iphlpsvc` (the portproxy kernel forwarder, on `0.0.0.0`). The blanket `Stop-Process -Force` was killing svchost. svchost hosts many shared services — including Tailscale — so the entire group went down with it. Fixed by restricting the kill list to known MCP process names (`node`, `python`, `powershell`, `cmd`) only.
- **Firewall rules go orphaned when Tailscale service stops.** Setup previously bound `New-NetFirewallRule -InterfaceAlias Tailscale`; Windows resolves the alias to the adapter's GUID at rule-creation time. When the Tailscale service stops (e.g. after Windows modern-standby), the adapter is removed and the rule's GUID becomes invalid. Even if Tailscale restarts and the adapter returns, a new GUID may not match the rule. Switched to `-RemoteAddress 100.64.0.0/10, fd7a:115c:a1e0::/48` (Tailscale CGNAT IPv4 range + Tailscale ULA IPv6 prefix). Rule now matches by source IP regardless of adapter state, survives Tailscale service restarts, and is tighter than adapter binding (only Tailscale-IP traffic accepted, not arbitrary traffic that happens to enter via the Tailscale adapter).
- diagnose.ps1 grew section 0 (Tailscale daemon health) at the very top: shows the Windows service state and a 3-line `tailscale status` head. Most failures we have hit cascade from "Tailscale daemon down on Windows", and burying that in section 7 made it the last thing read.
- **`npm install -g @wonderwhy-er/desktop-commander` failing on restricted networks.** desktop-commander has `puppeteer` as a transitive dep; puppeteer's postinstall downloads `chrome-headless-shell` from `storage.googleapis.com`, which is unreliable on networks with poor Google-CDN connectivity (China, GFW-affected regions). A half-finished download leaves a directory shell that breaks all subsequent installs with `"browser folder exists but executable is missing"`. Setup script now sets `PUPPETEER_SKIP_DOWNLOAD=true` before `npm install` and clears any stale `~/.cache/puppeteer` directory. desktop-commander's core tools (shell / file / process) work without the browser; for browser automation use the playwright MCP server instead.
- **desktop-commander silently exiting with code 1 a few seconds after launch.** Diagnosed by spawning the npm package directly with stdio capture: `npx -y` extracts the package into a per-invocation cache (`%APPDATA%\npm-cache\_npx\<hash>`). When Task Scheduler retries the launcher fast (we set `RestartCount=5 RestartInterval=1m`), two extracts race on the same path and one dies with `ENOTEMPTY: directory not empty, rename '...node_modules/<dep>' -> '...<dep>-<random>'` during npm's atomic-move step. Fix: setup-windows.ps1 now does `npm install -g supergateway @wonderwhy-er/desktop-commander`, and the launcher invokes `supergateway --stdio "desktop-commander"` — globals live in a stable `%APPDATA%\npm` location with no per-run extract step. Bonus: significantly faster startup (no re-download).
- **desktop-commander unreachable from agent over Tailscale IPv4.** supergateway 3.4.3 calls `app.listen(port)` with no host argument; on Windows, Node defaults to binding `::` (IPv6 only, not dual-stack), so connections from a Tailscale IPv4 peer hit TCP RST. Workaround: setup-windows.ps1 now adds `netsh interface portproxy v4tov6` mapping `0.0.0.0:8765 -> ::1:8765`. Built-in Windows feature, kernel-level forwarder, no external dependency. Tracked for v0.5.x: open an upstream PR at supercorp-ai/supergateway to add a `--host` flag, then drop the workaround.
- diagnose.ps1 grew section 5b which prints `netsh portproxy show v4tov6` so the workaround state is visible.
- Windows docs § 6 (uninstall) now also removes the portproxy entry.
- `setup-windows.ps1` source-parse failed on zh-CN Windows due to PowerShell 5.1 reading UTF-8 (no BOM) source as the system code page (GBK). Rewrote all user-facing strings to ASCII / English. Localized output stays in Markdown docs which are not parsed by PowerShell. Top-of-file note added for future contributors.
- `setup-windows.ps1` runtime-failed parsing `tailscale status --json` on zh-CN Windows: the JSON contains the account display name (which can be CJK), but PowerShell 5.1 reads child-process stdout using the OEM code page, mangling the bytes and breaking `ConvertFrom-Json`. Force `[Console]::OutputEncoding = UTF-8` at script start. Also improved the error path to distinguish "tailscale daemon down" vs "json parse failed" vs "not logged in".
- MCP services started by Task Scheduler showed visible console windows: `python.exe` is a console app (always opens a window), and `cmd.exe /c npx ...` shows a CMD window. Closing the window killed the service. Switched to a hidden PowerShell launcher pattern for both services: `powershell.exe -WindowStyle Hidden -File _launch-<service>.ps1`. The launcher invokes the underlying program (`python.exe` for windows-gui, `npx supergateway` for desktop-commander) which inherits the parent's hidden console — no visible window, but real std handles, and stdout / stderr are appended to a per-service log under `platforms/windows/logs/`.
- An earlier attempt at hiding the windows-gui service used `pythonw.exe`, which exits with code 1 when starting FastMCP/uvicorn (those expect real std handles, but pythonw binds them to NUL). Reverted to `python.exe` inside the hidden launcher.
- Setup script now stops existing tasks and kills any leftover process bound to 8765/8766 before re-registering, so re-running the script cleanly replaces older visible-window instances.

### Changed
- **Breaking · removed SSH from the standard flow.** All Linux↔Windows interaction now goes through MCP only (desktop-commander on 8765 + windows-gui on 8766). Existing v0.1.0 deployments can clean up: stop & uninstall OpenSSH Server, remove `C:\ProgramData\ssh\administrators_authorized_keys`, drop the SSH firewall rule.
- `setup-windows.ps1` now auto-discovers `server/` relative to itself; runs the GUI MCP directly from the cloned repo (no more `C:\mcp\gui` copy). Single source of truth.
- `setup-windows.ps1` auto-installs Python 3.12 if missing (or version < 3.10).
- `setup-windows.ps1` registers Task Scheduler tasks under `$env:USERNAME` instead of hardcoded `Administrator`.
- `setup-windows.ps1` adds 60s post-start verification with port-listen polling.

### Added
- `docs/agent-host-setup.md`: agent-side configuration guide (Tailscale + MCP client setup), audience-separated from the Windows guide.
- `README.md`: role-based entry points (device admin vs agent admin).
- `platforms/windows/scripts/diagnose.ps1`: read-only diagnostic that prints listening-address bind state, owning process, localhost / Tailscale-IP self-tests, MCP firewall rules with their interface filter, Tailscale adapter, last scheduled task result, **service log tails** (sections 9), and **recent Task Scheduler events** (section 10). Triages "agent host cannot reach the MCP services" in under a minute. Surfaced at the top of `docs/platforms/windows.md` § 7.
- Per-service log files at `platforms/windows/logs/{desktop-commander,windows-gui}.log` (gitignored). Both launchers append stdout + stderr so silent service failures (the hardest kind) are debuggable post-mortem.
- `scripts/check-ps-syntax.sh`: AST-parse all `.ps1` files in the repo via PowerShell 7's parser. Runs locally to catch syntax errors before pushing.

### Removed
- `setup-windows.ps1`: OpenSSH Server installation, default-shell registry tweak, `administrators_authorized_keys` setup, port 22 firewall rule.
- `docs/platforms/windows.md`: SSH key generation, `administrators_authorized_keys` placement, ssh-config setup, ssh test verification, file-transfer-via-http.server section. Doc is now Windows-administrator-focused (~150 lines, was ~500).

## [0.1.0] - 2026-05-06

Initial private release. Windows platform bridge.

### Added
- **Windows 11 platform bridge** (`platforms/windows/`)
  - `windows_gui_mcp.py`: FastMCP server exposing 17 tools over SSE on port 8766
    - Screen: `get_screen_size`, `take_screenshot`
    - Window: `list_windows`, `inspect_window`, `focus_window`
    - Mouse: `click`, `move_mouse`
    - Keyboard: `type_text`, `paste_text`, `press_key`
    - Process: `launch_app`, `kill_process`, `list_processes`
    - Shell: `run_powershell`
  - `setup-windows.ps1`: one-click installer covering Tailscale check, Node.js LTS, Python venv, firewall rules, and Task Scheduler auto-start for both MCP services
  - `requirements.txt` + `pyproject.toml` for installation
  - `claude-settings.json` reference config for the agent host's Claude Code
- **Tailscale-based cross-network connectivity** (works across LANs, no port-forwarding required)
- **desktop-commander** integration on port 8765 (community shell/file/process MCP via supergateway stdio→SSE bridge)
- **Architecture document** (`docs/architecture.md`) — defines the universal three-segment bridge model and the Universal Tool Set contract that all platforms must implement
- **Roadmap** (`docs/roadmap.md`) — version targets for macOS (0.2.0), Android (0.3.0), iOS (0.4.0), cross-device coordination (0.5.0), public OSS release (1.0.0)
- **Setup guide** (`docs/platforms/windows.md`) — operations manual in Chinese with troubleshooting checklist

### Security
- MCP ports (8765/8766) are restricted to the Tailscale network interface via Windows Firewall rules; not exposed to LAN or internet

[Unreleased]: https://github.com/metahub-tech/agent-test-bench/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/metahub-tech/agent-test-bench/releases/tag/v0.1.0
