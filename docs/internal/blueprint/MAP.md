# Project MAP（自动生成 · 请勿手编）

_由 `scripts/gen-blueprint-map.sh` 从代码自动生成。改完代码后跑这个脚本同步；CI 用 `--check` 模式把门。_

## platforms/

### android

Android Platform Bridge — v0.8.2-alpha

**关键文件**：
- `platforms/android/platform.toml`
- `platforms/android/README.md`
- `platforms/android/server/android_device_mcp.py` _(MCP server 主入口)_
- `platforms/android/skills/using-android/` _(skill 文档)_

### ios

iOS Platform Bridge — v0.8.2-alpha

**关键文件**：
- `platforms/ios/platform.toml`
- `platforms/ios/README.md`
- `platforms/ios/server/ios_device_mcp.py` _(MCP server 主入口)_
- `platforms/ios/skills/using-ios/` _(skill 文档)_

### macos

macOS Platform Bridge

**关键文件**：
- `platforms/macos/platform.toml`
- `platforms/macos/README.md`
- `platforms/macos/server/mac_device_mcp.py` _(MCP server 主入口)_
- `platforms/macos/skills/using-mac/` _(skill 文档)_
- `platforms/macos/skills/using-vision/` _(skill 文档)_

### windows

Windows Platform Bridge

**关键文件**：
- `platforms/windows/platform.toml`
- `platforms/windows/README.md`
- `platforms/windows/server/win_device_mcp.py` _(MCP server 主入口)_
- `platforms/windows/skills/using-vision/` _(skill 文档)_
- `platforms/windows/skills/using-win/` _(skill 文档)_

## cli/

agent-fleet CLI

**关键模块**：
- `cli/src/fleet/cli.py`
- `cli/src/fleet/detect.py`
- `cli/src/fleet/frameworks/antigravity.py`
- `cli/src/fleet/frameworks/base.py`
- `cli/src/fleet/frameworks/claude_code.py`
- `cli/src/fleet/frameworks/cline.py`
- `cli/src/fleet/frameworks/cursor.py`
- `cli/src/fleet/frameworks/hermes.py`
- `cli/src/fleet/frameworks/openclaw.py`
- `cli/src/fleet/installers/_android.py`
- `cli/src/fleet/installers/_env.py`
- `cli/src/fleet/installers/_hooks.py`
- `cli/src/fleet/installers/_ios.py`
- `cli/src/fleet/installers/_manifest_installer.py`
- `cli/src/fleet/installers/base.py`
- `cli/src/fleet/macos_perm.py`
- `cli/src/fleet/smoke.py`
- `cli/src/fleet/types.py`
- `cli/src/fleet/verify.py`
- `cli/src/fleet/wizard.py`

**Guidance 资产（CLI 安装向导用的剧本 yaml）**：
- `cli/src/fleet/guidance/android_dev_options.yaml`
- `cli/src/fleet/guidance/android_usb_debug.yaml`
- `cli/src/fleet/guidance/android_wireless_pair.yaml`
- `cli/src/fleet/guidance/ios_wda_deploy.yaml`
- `cli/src/fleet/guidance/macos_accessibility.yaml`
- `cli/src/fleet/guidance/macos_automation.yaml`
- `cli/src/fleet/guidance/macos_full_disk_access.yaml`
- `cli/src/fleet/guidance/macos_screen_recording.yaml`
- `cli/src/fleet/guidance/windows_postinstall.yaml`

## scripts/

**仓库级运维脚本**：
- `scripts/check-blueprint-refs.sh` — check-blueprint-refs.sh
- `scripts/check-ps-syntax.sh` — Validate PowerShell script syntax across the repo via AST parse.
- `scripts/gen-blueprint-interface.sh` — gen-blueprint-interface.sh
- `scripts/gen-blueprint-map.sh` — gen-blueprint-map.sh
- `scripts/gen-docs.py`
- `scripts/gen_docs.py`
- `scripts/install-agent-side.py`

## docs/

**共享设计/上手文档**：
- `docs/2026-06-21-device-op-server-launch.md`
- `docs/2026-06-21-mac-helper-promotion-from-agenthub.md`
- `docs/2026-06-21-requirements-from-agenthub-device-op.md`
- `docs/agent-host-setup.md`
- `docs/architecture.md`
- `docs/install-pattern.md`
- `docs/roadmap.md`
- `docs/platforms/` _(各平台 setup guide)_

