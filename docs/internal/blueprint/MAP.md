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

### windows

Windows Platform Bridge

**关键文件**：
- `platforms/windows/platform.toml`
- `platforms/windows/README.md`
- `platforms/windows/server/win_device_mcp.py` _(MCP server 主入口)_
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
- `docs/agent-host-setup.md`
- `docs/architecture.md`
- `docs/install-pattern.md`
- `docs/roadmap.md`
- `docs/platforms/` _(各平台 setup guide)_

