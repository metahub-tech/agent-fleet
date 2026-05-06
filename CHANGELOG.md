# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
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
