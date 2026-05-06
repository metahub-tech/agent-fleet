# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `setup-windows.ps1` parse-failed on zh-CN Windows due to PowerShell 5.1 reading UTF-8 (no BOM) source as the system code page (GBK). Rewrote all user-facing strings to ASCII / English. Localized output stays in Markdown docs which are not parsed by PowerShell. Top-of-file note added for future contributors.

### Changed
- **Breaking · removed SSH from the standard flow.** All Linux↔Windows interaction now goes through MCP only (desktop-commander on 8765 + windows-gui on 8766). Existing v0.1.0 deployments can clean up: stop & uninstall OpenSSH Server, remove `C:\ProgramData\ssh\administrators_authorized_keys`, drop the SSH firewall rule.
- `setup-windows.ps1` now auto-discovers `server/` relative to itself; runs the GUI MCP directly from the cloned repo (no more `C:\mcp\gui` copy). Single source of truth.
- `setup-windows.ps1` auto-installs Python 3.12 if missing (or version < 3.10).
- `setup-windows.ps1` registers Task Scheduler tasks under `$env:USERNAME` instead of hardcoded `Administrator`.
- `setup-windows.ps1` adds 60s post-start verification with port-listen polling.

### Added
- `docs/agent-host-setup.md`: agent-side configuration guide (Tailscale + MCP client setup), audience-separated from the Windows guide.
- `README.md`: role-based entry points (device admin vs agent admin).

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
