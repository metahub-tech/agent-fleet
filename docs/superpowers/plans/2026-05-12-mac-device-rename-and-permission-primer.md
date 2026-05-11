# Mac-device rename + macOS TCC permission primer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `macbox-gui`/`winpc-gui`/`android-gui` → `mac-device`/`win-device`/`android-device` everywhere, and add a macOS TCC permission primer that auto-triggers each permission dialog (so Python.app pre-appears in System Settings — user toggles a switch instead of dragging binaries).

**Architecture:**
1. **Rename:** mechanical replacement of role IDs and service identifiers (launchd plist label, Task Scheduler names, skill dir names, log file names). Platform directories (`platforms/macos/` etc.) stay — they describe OS, not role. Server Python entry points (`macos_gui_mcp.py` etc.) stay — internal. Config dirs (`.atb-android`) and env vars (`ATB_ANDROID_*`) stay this round — out of scope.
2. **Permission primer:** new module `cli/src/fleet/macos_perm.py` with 4 functions (one per TCC permission). Each function shells out to the macOS server's venv python (which has pyobjc pre-installed) to trigger the relevant API, then opens the corresponding System Settings pane via `x-apple.systempreferences://` URL. Wizard's `_run_guidance` calls primer-then-prompt for mac-device's steps.
3. **Regression test:** `test_no_legacy_naming.py` asserts no legacy role/service strings exist in active code (allowlist for CHANGELOG and historical plans).

**Tech Stack:** Python 3.10+, subprocess, pytest, pytest-mock, AppKit/Quartz/ApplicationServices via macOS server venv (already a dep there)

---

## Identifier Mapping

| Old | New |
|---|---|
| **Role IDs** | |
| `macbox-gui` | `mac-device` |
| `winpc-gui` | `win-device` |
| `android-gui` | `android-device` |
| **Service identifiers** | |
| launchd label `cc.metahub.macbox-gui` | `cc.metahub.mac-device` |
| launchd plist `cc.metahub.macbox-gui.plist` | `cc.metahub.mac-device.plist` |
| Win task `MCP-WindowsGui` | `MCP-WinDevice` |
| Win task `MCP-AndroidGui` | `MCP-AndroidDevice` |
| systemd unit `atb-android-gui.service` | `agent-fleet-android-device.service` |
| **File names** | |
| `_launch-macos-gui.sh` | `_launch-mac-device.sh` |
| `_launch-windows-gui.ps1` | `_launch-win-device.ps1` |
| `_launch-android.{sh,ps1}` | unchanged (no role suffix) |
| **Skill dirs** | |
| `platforms/macos/skills/using-macbox/` | `platforms/macos/skills/using-mac/` |
| `platforms/windows/skills/using-winpc/` | `platforms/windows/skills/using-win/` |
| `platforms/android/skills/using-android/` | unchanged |
| **Out of scope** (deferred to follow-up) | |
| `~/.atb-android/config.toml` | unchanged |
| `ATB_ANDROID_ADB` env var | unchanged |
| `macos_gui_mcp.py` / `windows_gui_mcp.py` / `android_mcp.py` | unchanged |
| `platforms/macos/` etc. dir layout | unchanged |

---

## File Structure

**New files:**
- `cli/src/fleet/macos_perm.py` — primer module (4 functions + 1 pane-open helper)
- `cli/tests/test_macos_perm.py` — unit tests (mocked subprocess)
- `cli/tests/test_no_legacy_naming.py` — global regression test
- `cli/tests/fixtures/__init__.py` — if not exists; small helper for repo-root lookup

**Modified — CLI (Python):**
- `cli/src/fleet/installers/macos.py` — `role_id`, `display_name`, `guidance_steps()` re-ordering; new `_run_primer_then_step` helper called by wizard
- `cli/src/fleet/installers/windows.py` — `role_id`, `display_name`
- `cli/src/fleet/installers/linux.py` — `role_id`, `display_name` for the android-bridge installer
- `cli/src/fleet/installers/base.py` — comment/docstring updates
- `cli/src/fleet/types.py` — `role_id` literal docs
- `cli/src/fleet/cli.py` — wizard integration (call primer fn for mac-device guidance)
- `cli/src/fleet/guidance/macos_accessibility.yaml` — update copy ("Python.app is already in the list; toggle the switch")
- `cli/src/fleet/guidance/macos_screen_recording.yaml` — same
- `cli/src/fleet/guidance/macos_automation.yaml` — same
- `cli/src/fleet/guidance/macos_full_disk_access.yaml` — same (note: only pane-open, no API trigger)
- `cli/src/fleet/guidance/windows_postinstall.yaml` — references `winpc-gui` text
- `cli/tests/test_installers_macos.py` — assert `role_id == "mac-device"`
- `cli/tests/test_installers_windows.py` — assert `role_id == "win-device"`
- `cli/tests/test_installers_linux.py` — assert `role_id == "android-device"`
- `cli/tests/test_installers_registry.py` — fixtures
- `cli/tests/test_wizard.py` — fixtures
- `cli/tests/test_types.py` — fixtures
- `cli/tests/test_frameworks_jsonhttp.py` — fixtures
- `cli/tests/test_frameworks_other.py` — fixtures
- `cli/src/fleet/__init__.py` — bump `__version__` to `0.6.0a1`

**Modified — platform scripts (bash/powershell):**
- `platforms/macos/scripts/setup-macos.sh` — `LABEL`, `PLIST_PATH`, log paths
- `platforms/macos/scripts/_launch-macos-gui.sh` → rename to `_launch-mac-device.sh`
- `platforms/windows/scripts/setup-windows.ps1` — `TaskName`
- `platforms/windows/scripts/_launch-windows-gui.ps1` → rename to `_launch-win-device.ps1`
- `platforms/windows/scripts/diagnose.ps1` — `TaskName` refs
- `platforms/android/scripts/setup-android.sh` — launchd LABEL on mac-host case
- `platforms/android/scripts/setup-android.ps1` — `TaskName`
- `platforms/android/scripts/setup-android-linux.sh` — systemd unit name

**Modified — docs:**
- `README.md` — status table, ASCII diagram, badges, snippet examples
- `CHANGELOG.md` — add v0.6.0-alpha section noting breaking rename
- `docs/agent-host-setup.md`
- `docs/install-pattern.md`
- `docs/platforms/macos.md`
- `docs/platforms/windows.md`
- `docs/roadmap.md`
- `platforms/macos/README.md`
- `platforms/windows/README.md`
- `platforms/android/README.md`
- `platforms/macos/skills/using-macbox/SKILL.md` (rename dir; update content)
- `platforms/windows/skills/using-winpc/SKILL.md` (rename dir; update content)
- `platforms/android/skills/using-android/SKILL.md` (update content only)
- `examples/multi-platform-claude-settings.json`
- `platforms/macos/examples/claude-settings.json`
- `platforms/windows/examples/claude-settings.json`
- `platforms/android/examples/claude-settings.json`
- `scripts/install-agent-side.py`

**Modified — server files (content only, file names unchanged):**
- `platforms/macos/server/macos_gui_mcp.py` — any user-facing string referencing the role
- `platforms/windows/server/windows_gui_mcp.py` — same
- `platforms/android/server/android_mcp.py` — same

**Untouched:** all `*.venv/`, `*__pycache__*`, `.git/`, `node_modules/`.

---

## Phase 1 — Permission primer (new module)

### Task 1: macos_perm.py skeleton + open_settings_pane helper

**Files:**
- Create: `cli/src/fleet/macos_perm.py`
- Test: `cli/tests/test_macos_perm.py`

- [ ] **Step 1: Write the failing test**

```python
# cli/tests/test_macos_perm.py
from unittest.mock import patch
from fleet.macos_perm import open_settings_pane, SettingsPane


def test_open_settings_pane_calls_open_with_correct_url():
    with patch("subprocess.run") as mock_run:
        open_settings_pane(SettingsPane.ACCESSIBILITY)
        mock_run.assert_called_once_with(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=False,
        )


def test_settings_pane_enum_values():
    assert SettingsPane.ACCESSIBILITY.url_suffix == "Privacy_Accessibility"
    assert SettingsPane.SCREEN_RECORDING.url_suffix == "Privacy_ScreenCapture"
    assert SettingsPane.AUTOMATION.url_suffix == "Privacy_Automation"
    assert SettingsPane.FULL_DISK_ACCESS.url_suffix == "Privacy_AllFiles"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && uv run pytest tests/test_macos_perm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.macos_perm'`

- [ ] **Step 3: Write minimal implementation**

```python
# cli/src/fleet/macos_perm.py
"""macOS TCC permission primer.

Triggers the macOS Privacy & Security permission dialogs programmatically so
Python.app gets registered in the relevant TCC list, then opens System
Settings to the corresponding pane.  After this runs the user can just toggle
the switch — no manual binary drag required.
"""
from __future__ import annotations

import enum
import subprocess
from pathlib import Path


class SettingsPane(enum.Enum):
    """System Settings → Privacy & Security panes addressable via URL scheme.

    The URL suffix corresponds to the anchor in
    x-apple.systempreferences:com.apple.preference.security?<suffix>
    """
    ACCESSIBILITY = "Privacy_Accessibility"
    SCREEN_RECORDING = "Privacy_ScreenCapture"
    AUTOMATION = "Privacy_Automation"
    FULL_DISK_ACCESS = "Privacy_AllFiles"

    @property
    def url_suffix(self) -> str:
        return self.value


def open_settings_pane(pane: SettingsPane) -> None:
    """Open System Settings directly to the given Privacy pane.

    Uses the documented x-apple.systempreferences:// URL scheme.  Best-effort
    (check=False) — if `open` fails the user can still navigate manually.
    """
    url = f"x-apple.systempreferences:com.apple.preference.security?{pane.url_suffix}"
    subprocess.run(["open", url], check=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && uv run pytest tests/test_macos_perm.py -v`
Expected: PASS for both tests

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/macos_perm.py cli/tests/test_macos_perm.py
git commit -m "feat(macos_perm): add SettingsPane enum + open_settings_pane helper"
```

---

### Task 2: prime_accessibility — trigger TCC + open pane

**Files:**
- Modify: `cli/src/fleet/macos_perm.py`
- Modify: `cli/tests/test_macos_perm.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to cli/tests/test_macos_perm.py
from pathlib import Path


def test_prime_accessibility_calls_venv_python_then_opens_pane():
    from fleet.macos_perm import prime_accessibility
    venv_py = Path("/tmp/venv/bin/python3")
    with patch("subprocess.run") as mock_run:
        prime_accessibility(venv_py)
        # First call: trigger the TCC dialog by importing ApplicationServices
        first_args = mock_run.call_args_list[0].args[0]
        assert first_args[0] == str(venv_py)
        assert "-c" in first_args
        assert "AXIsProcessTrustedWithOptions" in first_args[-1]
        # Second call: open the pane
        second_args = mock_run.call_args_list[1].args[0]
        assert second_args[0] == "open"
        assert "Privacy_Accessibility" in second_args[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && uv run pytest tests/test_macos_perm.py::test_prime_accessibility_calls_venv_python_then_opens_pane -v`
Expected: FAIL — `ImportError: cannot import name 'prime_accessibility'`

- [ ] **Step 3: Add implementation**

```python
# Append to cli/src/fleet/macos_perm.py


def prime_accessibility(venv_python: Path) -> None:
    """Trigger Accessibility permission registration for Python.app.

    Calls AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    via the macOS server's venv python (which has pyobjc installed).  This
    pops the system dialog AND registers Python.app in the Accessibility list
    even if denied.  Then opens the Accessibility pane so user can toggle.
    """
    snippet = (
        "from ApplicationServices import "
        "AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt; "
        "AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})"
    )
    subprocess.run([str(venv_python), "-c", snippet], check=False)
    open_settings_pane(SettingsPane.ACCESSIBILITY)
```

- [ ] **Step 4: Run test**

Run: `cd cli && uv run pytest tests/test_macos_perm.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/macos_perm.py cli/tests/test_macos_perm.py
git commit -m "feat(macos_perm): prime_accessibility (trigger TCC + open pane)"
```

---

### Task 3: prime_screen_recording

**Files:**
- Modify: `cli/src/fleet/macos_perm.py`
- Modify: `cli/tests/test_macos_perm.py`

- [ ] **Step 1: Write the failing test**

```python
def test_prime_screen_recording():
    from fleet.macos_perm import prime_screen_recording
    venv_py = Path("/tmp/venv/bin/python3")
    with patch("subprocess.run") as mock_run:
        prime_screen_recording(venv_py)
        first_args = mock_run.call_args_list[0].args[0]
        assert first_args[0] == str(venv_py)
        assert "CGRequestScreenCaptureAccess" in first_args[-1]
        second_args = mock_run.call_args_list[1].args[0]
        assert "Privacy_ScreenCapture" in second_args[1]
```

- [ ] **Step 2: Run test (fails on ImportError)**

Run: `cd cli && uv run pytest tests/test_macos_perm.py::test_prime_screen_recording -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implementation**

```python
# Append to cli/src/fleet/macos_perm.py


def prime_screen_recording(venv_python: Path) -> None:
    """Trigger Screen Recording permission registration.

    Quartz.CGRequestScreenCaptureAccess() — macOS 11+ API that pops the
    system dialog and registers Python.app in the Screen Recording list.
    """
    snippet = "import Quartz; Quartz.CGRequestScreenCaptureAccess()"
    subprocess.run([str(venv_python), "-c", snippet], check=False)
    open_settings_pane(SettingsPane.SCREEN_RECORDING)
```

- [ ] **Step 4: Run test**

Run: `cd cli && uv run pytest tests/test_macos_perm.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/macos_perm.py cli/tests/test_macos_perm.py
git commit -m "feat(macos_perm): prime_screen_recording"
```

---

### Task 4: prime_automation (uses osascript, not venv python)

**Files:**
- Modify: `cli/src/fleet/macos_perm.py`
- Modify: `cli/tests/test_macos_perm.py`

- [ ] **Step 1: Write the failing test**

```python
def test_prime_automation_uses_osascript():
    from fleet.macos_perm import prime_automation
    with patch("subprocess.run") as mock_run:
        prime_automation()
        first_args = mock_run.call_args_list[0].args[0]
        assert first_args[0] == "osascript"
        assert "-e" in first_args
        assert "System Events" in first_args[-1]
        second_args = mock_run.call_args_list[1].args[0]
        assert "Privacy_Automation" in second_args[1]
```

- [ ] **Step 2: Run test (fails)**

Run: `cd cli && uv run pytest tests/test_macos_perm.py::test_prime_automation_uses_osascript -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implementation**

```python
# Append to cli/src/fleet/macos_perm.py


def prime_automation() -> None:
    """Trigger Automation/AppleScript permission registration.

    First-time use of `tell application "System Events"` triggers the
    Automation prompt for the calling app (Terminal, in this context — the
    parent of the wizard process).  This is different from the others: it
    grants Terminal the right to control System Events, which transitively
    lets python subprocesses spawned from Terminal control GUI apps.
    """
    script = 'tell application "System Events" to count of processes'
    subprocess.run(["osascript", "-e", script], check=False)
    open_settings_pane(SettingsPane.AUTOMATION)
```

- [ ] **Step 4: Run test**

Run: `cd cli && uv run pytest tests/test_macos_perm.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/macos_perm.py cli/tests/test_macos_perm.py
git commit -m "feat(macos_perm): prime_automation via osascript"
```

---

### Task 5: prime_full_disk_access (no trigger API; pane-open only)

**Files:**
- Modify: `cli/src/fleet/macos_perm.py`
- Modify: `cli/tests/test_macos_perm.py`

- [ ] **Step 1: Write the failing test**

```python
def test_prime_full_disk_access_only_opens_pane():
    from fleet.macos_perm import prime_full_disk_access
    with patch("subprocess.run") as mock_run:
        prime_full_disk_access()
        # No API-trigger call possible — only the open-pane call
        assert len(mock_run.call_args_list) == 1
        args = mock_run.call_args_list[0].args[0]
        assert args[0] == "open"
        assert "Privacy_AllFiles" in args[1]
```

- [ ] **Step 2: Run test (fails)**

Run: `cd cli && uv run pytest tests/test_macos_perm.py::test_prime_full_disk_access_only_opens_pane -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implementation**

```python
# Append to cli/src/fleet/macos_perm.py


def prime_full_disk_access() -> None:
    """Open the Full Disk Access pane.

    Unlike the other three permissions, macOS provides no public API to
    pre-trigger FDA's TCC entry, so this just opens the pane.  The user
    needs to drag-add Python.app or Terminal manually.
    """
    open_settings_pane(SettingsPane.FULL_DISK_ACCESS)
```

- [ ] **Step 4: Run test**

Run: `cd cli && uv run pytest tests/test_macos_perm.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/macos_perm.py cli/tests/test_macos_perm.py
git commit -m "feat(macos_perm): prime_full_disk_access (pane-open only)"
```

---

### Task 6: Wire primer into wizard guidance flow

**Files:**
- Modify: `cli/src/fleet/cli.py:_run_guidance` (lines 115-131)
- Modify: `cli/src/fleet/guidance/macos_accessibility.yaml`
- Modify: `cli/src/fleet/guidance/macos_screen_recording.yaml`
- Modify: `cli/src/fleet/guidance/macos_automation.yaml`
- Modify: `cli/src/fleet/guidance/macos_full_disk_access.yaml`

- [ ] **Step 1: Update macos_accessibility.yaml copy**

```yaml
# cli/src/fleet/guidance/macos_accessibility.yaml
id: macos_accessibility
title: 辅助功能 (Accessibility) 权限
description: |
  我已经触发了辅助功能授权对话框。系统设置已自动打开到 隐私与安全性 → 辅助功能。

  你应该看到 **Python**（或 Python.app）已经出现在列表里 —— **只需打开开关**即可。
  如果列表里没看到，请按 + 手动添加：
    Intel:   /usr/local/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app
    ARM:     /opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app

  ⚠️ 不要拖 venv 的 bin/python3（macOS 拒绝符号链接）。
variant_label: macOS 版本
variants:
  ventura_plus:
    label: "macOS 13 Ventura+ (System Settings)"
    description: "System Settings → Privacy & Security → Accessibility"
  monterey_minus:
    label: "macOS 12 Monterey-"
    description: "System Preferences → Security & Privacy → Privacy → Accessibility（界面布局不同，但功能一致）"
```

- [ ] **Step 2: Update macos_screen_recording.yaml**

```yaml
id: macos_screen_recording
title: 屏幕录制 (Screen Recording) 权限
description: |
  我已经触发了屏幕录制授权对话框。系统设置已自动打开到 隐私与安全性 → 屏幕录制。

  你应该看到 **Python** 已经出现在列表里 —— **只需打开开关**即可，然后按系统提示重启相关进程。
variant_label: macOS 版本
variants:
  ventura_plus:
    label: "macOS 13 Ventura+ (System Settings)"
    description: "System Settings → Privacy & Security → Screen Recording"
  monterey_minus:
    label: "macOS 12 Monterey-"
    description: "System Preferences → Security & Privacy → Privacy → Screen Recording"
```

- [ ] **Step 3: Update macos_automation.yaml**

```yaml
id: macos_automation
title: 自动化 (Automation) 权限
description: |
  我已经触发了自动化授权对话框。系统应该已经询问 "Terminal 想控制 System Events"。

  在弹出的对话框点击「好」(OK)。然后在自动打开的 System Settings → Privacy & Security → Automation 里，
  你会看到 Terminal 下面挂着 System Events —— 确保开关是打开的。
variant_label: macOS 版本
variants:
  ventura_plus:
    label: "macOS 13 Ventura+ (System Settings)"
    description: "System Settings → Privacy & Security → Automation"
  monterey_minus:
    label: "macOS 12 Monterey-"
    description: "System Preferences → Security & Privacy → Privacy → Automation"
```

- [ ] **Step 4: Update macos_full_disk_access.yaml**

```yaml
id: macos_full_disk_access
title: 完全磁盘访问 (Full Disk Access) 权限
description: |
  System Settings 已经自动打开到 隐私与安全性 → 完全磁盘访问。

  ⚠️ 这一项 macOS 没有 API 能预触发 —— 需要你手工添加 Python.app（拖入 + 号）或 Terminal。
    Intel:   /usr/local/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app
    ARM:     /opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app
  完全磁盘访问主要影响 ~/Documents, ~/Downloads, ~/Desktop 下的文件操作。不开通也可以用，但部分工具会拒绝读取这些位置。
variant_label: macOS 版本
variants:
  ventura_plus:
    label: "macOS 13 Ventura+ (System Settings)"
    description: "System Settings → Privacy & Security → Full Disk Access"
  monterey_minus:
    label: "macOS 12 Monterey-"
    description: "System Preferences → Security & Privacy → Privacy → Full Disk Access"
```

- [ ] **Step 5: Wire primer into cli.py:_run_guidance**

Replace `_run_guidance` in `cli/src/fleet/cli.py` (currently around lines 115-131):

```python
def _run_guidance(roles, ctx):
    """For each role, optionally invoke the macOS primer (registers Python.app
    in TCC + opens the Settings pane), then print the guidance step and wait
    for user keystroke."""
    from . import macos_perm
    from pathlib import Path

    # Map guidance YAML id → primer callable (mac-device only)
    macos_primer = {
        "macos_accessibility": lambda p: macos_perm.prime_accessibility(p),
        "macos_screen_recording": lambda p: macos_perm.prime_screen_recording(p),
        "macos_automation": lambda p: macos_perm.prime_automation(),
        "macos_full_disk_access": lambda p: macos_perm.prime_full_disk_access(),
    }

    for r in roles:
        steps = r.guidance_steps()
        if not steps:
            continue
        console.print(f"\n[bold magenta]🔓 Operation guidance for {r.role_id}[/bold magenta]")
        for i, s in enumerate(steps, 1):
            console.print(f"\n  [bold]Step {i}/{len(steps)}: {s.title}[/bold]")
            # Run primer if this is a mac-device guidance step we know about
            if r.role_id == "mac-device" and s.id in macos_primer:
                venv_py = Path(ctx.repo_root) / "platforms" / "macos" / "server" / ".venv" / "bin" / "python3"
                if venv_py.exists():
                    console.print(f"  [dim]↪ Triggering {s.id} ...[/dim]")
                    macos_primer[s.id](venv_py)
                else:
                    console.print(f"  [yellow]↪ venv not found at {venv_py}; skipping primer.[/yellow]")
            console.print(f"  {s.default_description}")
            if s.variants:
                console.print(f"\n  [dim]{s.variant_label} 变体：[/dim]")
                for vid, v in s.variants.items():
                    console.print(f"    [cyan]{v.label}[/cyan]: {v.description}")
            questionary.press_any_key_to_continue("  ↩ 完成后回车继续").ask()
```

Update call site in `cmd_setup` (around line 155):

```python
    if args.dry_run:
        console.print("\n[dim]↪ Skipping operation guidance (dry-run).[/dim]")
    else:
        _run_guidance(roles, ctx)
```

This requires `ctx` (the InstallContext) which `cmd_setup` already has.

Also need to add `id` to `GuidanceStep` dataclass — verify:

```bash
grep -n "class GuidanceStep" cli/src/fleet/types.py
```

If `id` field is missing, add it. Check guidance YAMLs already have `id: macos_accessibility` etc. Confirm via:

```bash
grep -nE '^id:' cli/src/fleet/guidance/*.yaml
```

If `id` is in YAML but not in dataclass, update `cli/src/fleet/guidance/__init__.py` loader to populate the `id` field.

- [ ] **Step 6: Run all macos_perm + guidance + cli tests**

Run: `cd cli && uv run pytest tests/test_macos_perm.py tests/test_guidance_loader.py tests/test_cli_smoke.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add cli/src/fleet/cli.py cli/src/fleet/guidance/macos_*.yaml cli/src/fleet/types.py cli/src/fleet/guidance/__init__.py
git commit -m "feat(wizard): wire macos_perm primer into _run_guidance"
```

---

## Phase 2 — Rename role IDs (cli + tests)

### Task 7: Rename `macbox-gui` → `mac-device` in installers + cli

**Files:**
- Modify: `cli/src/fleet/installers/macos.py`
- Modify: `cli/src/fleet/installers/base.py`
- Modify: `cli/tests/test_installers_macos.py`
- Modify: `cli/tests/test_installers_registry.py`
- Modify: `cli/tests/test_wizard.py`
- Modify: `cli/tests/test_types.py`
- Modify: `cli/tests/test_frameworks_jsonhttp.py`
- Modify: `cli/tests/test_frameworks_other.py`
- Modify: `cli/src/fleet/cli.py:153` (macos_primer dispatch key was `mac-device` already from Task 6)

- [ ] **Step 1: Write the failing assertion**

In `cli/tests/test_installers_macos.py`, add:

```python
def test_macos_desktop_role_id_is_mac_device():
    from fleet.installers.macos import MacosDesktop
    assert MacosDesktop.role_id == "mac-device"
    assert MacosDesktop.display_name == "macOS desktop (mac-device)"
```

- [ ] **Step 2: Run — expect failure (still `macbox-gui`)**

Run: `cd cli && uv run pytest tests/test_installers_macos.py::test_macos_desktop_role_id_is_mac_device -v`
Expected: FAIL — `assert "macbox-gui" == "mac-device"`

- [ ] **Step 3: Update `cli/src/fleet/installers/macos.py`**

In class `MacosDesktop`:

```python
class MacosDesktop(BaseInstaller):
    role_id = "mac-device"
    display_name = "macOS desktop (mac-device)"
    port = 8767
```

(line 13-16 area; keep other methods unchanged)

In class `MacosAndroidBridge`:

```python
class MacosAndroidBridge(BaseInstaller):
    role_id = "android-device"
    display_name = "Android bridge on macOS (android-device)"
    port = 8768
```

- [ ] **Step 4: Update all other test files**

Global replace in `cli/tests/`:
- `"macbox-gui"` → `"mac-device"`
- `"winpc-gui"` → `"win-device"`
- `"android-gui"` → `"android-device"`

```bash
cd cli && find tests/ -name '*.py' -exec sed -i 's/"macbox-gui"/"mac-device"/g; s/"winpc-gui"/"win-device"/g; s/"android-gui"/"android-device"/g' {} +
```

Inspect git diff to verify only intended replacements:

```bash
git diff cli/tests/
```

- [ ] **Step 5: Run all CLI tests**

Run: `cd cli && uv run pytest -v 2>&1 | tail -20`
Expected: One test (test_macos_desktop_role_id_is_mac_device) PASS; some others may fail if they have local `macbox-gui` strings.

- [ ] **Step 6: Update other installer files**

In `cli/src/fleet/installers/windows.py`:

```python
class WindowsDesktop(BaseInstaller):
    role_id = "win-device"
    display_name = "Windows desktop (win-device)"
    port = 8766
```

```python
class WindowsAndroidBridge(BaseInstaller):
    role_id = "android-device"
    display_name = "Android bridge on Windows (android-device)"
    port = 8768
```

In `cli/src/fleet/installers/linux.py`:

```python
class LinuxAndroidBridge(BaseInstaller):
    role_id = "android-device"
    display_name = "Android bridge on Linux (android-device)"
    port = 8768
```

In `cli/src/fleet/installers/base.py`: update any role_id references in docstrings.

- [ ] **Step 7: Run full test suite**

Run: `cd cli && uv run pytest -v 2>&1 | tail -10`
Expected: All tests PASS (≥55).

- [ ] **Step 8: Commit**

```bash
git add cli/src/fleet/installers/ cli/tests/
git commit -m "refactor(cli): rename role_ids to <os>-device"
```

---

### Task 8: Update windows_postinstall.yaml + framework snippet templates

**Files:**
- Modify: `cli/src/fleet/guidance/windows_postinstall.yaml`
- Modify: `cli/src/fleet/frameworks/claude_code.py` (and other framework files if they have legacy strings)

- [ ] **Step 1: Find legacy strings**

Run:
```bash
grep -rn "macbox-gui\|winpc-gui\|android-gui" cli/src/fleet/
```

- [ ] **Step 2: Replace each occurrence with the corresponding `*-device` form**

Apply context-aware replacements. For YAML, expect prose like "你的 winpc-gui 已经在 8766 端口" → "你的 win-device 已经在 8766 端口".

- [ ] **Step 3: Run tests**

Run: `cd cli && uv run pytest -v 2>&1 | tail -5`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add cli/src/fleet/
git commit -m "refactor(cli): update YAML + framework prose for role rename"
```

---

### Task 9: Global regression test — no legacy naming in active code

**Files:**
- Create: `cli/tests/test_no_legacy_naming.py`

- [ ] **Step 1: Write the test**

```python
# cli/tests/test_no_legacy_naming.py
"""Global regression: legacy role-ID and service-identifier strings must not
appear in active code/config.  Allowlisted areas: CHANGELOG (historical),
docs/superpowers/plans/ (historical plans), docs/design/ (historical specs).
"""
from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

LEGACY = [
    # role IDs
    "macbox-gui", "winpc-gui", "android-gui",
    # service identifiers
    "cc.metahub.macbox-gui",
    "MCP-WindowsGui", "MCP-AndroidGui",
    "atb-android-gui",
    # skill dir names
    "using-macbox", "using-winpc",
]

# Areas we don't scan (historical, generated, or external).
ALLOW_PATH_PREFIXES = {
    "CHANGELOG.md",
    "docs/superpowers/plans/",
    "docs/design/",
    "docs/superpowers/specs/",
    "cli/.venv/",
    "cli/test_env/",
    ".git/",
    "__pycache__",
}

# Extensions we scan.
SCAN_EXTS = {".py", ".sh", ".ps1", ".yaml", ".yml", ".toml", ".json", ".md"}


def _is_allowlisted(rel: pathlib.Path) -> bool:
    s = str(rel)
    return any(s.startswith(p) or p in s for p in ALLOW_PATH_PREFIXES)


def test_no_legacy_naming_strings_in_active_code():
    failures: list[tuple[str, str, int]] = []  # (path, legacy_str, line_no)
    for f in REPO_ROOT.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix not in SCAN_EXTS:
            continue
        rel = f.relative_to(REPO_ROOT)
        if _is_allowlisted(rel):
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for legacy in LEGACY:
            for i, line in enumerate(text.splitlines(), 1):
                if legacy in line:
                    failures.append((str(rel), legacy, i))

    if failures:
        msg = "\nLegacy naming strings still present:\n"
        for path, legacy, ln in failures:
            msg += f"  {path}:{ln}  →  {legacy!r}\n"
        msg += "\nAllowlisted prefixes: " + ", ".join(sorted(ALLOW_PATH_PREFIXES))
        raise AssertionError(msg)
```

- [ ] **Step 2: Run — expect failures (platform scripts + docs not yet renamed)**

Run: `cd cli && uv run pytest tests/test_no_legacy_naming.py -v`
Expected: FAIL with a long list of remaining legacy occurrences (this is the rest of the rename work — Tasks 10-17).

- [ ] **Step 3: Commit the test (without expectation that it passes yet)**

```bash
git add cli/tests/test_no_legacy_naming.py
git commit -m "test: add no-legacy-naming regression test (will pass after rest of rename)"
```

The test is committed in failing state intentionally — subsequent tasks make it pass. Run it after each platform-scripts/doc task to track progress.

---

## Phase 3 — Rename platform scripts (Mac + Win + Android)

### Task 10: Rename launchd label + plist + launch script (macOS)

**Files:**
- Modify: `platforms/macos/scripts/setup-macos.sh`
- Rename: `platforms/macos/scripts/_launch-macos-gui.sh` → `_launch-mac-device.sh`
- Modify: `platforms/macos/scripts/_launch-mac-device.sh` (content references)
- Modify: `platforms/macos/server/macos_gui_mcp.py` (if log strings reference the role)

- [ ] **Step 1: Rename the launch wrapper file**

```bash
git mv platforms/macos/scripts/_launch-macos-gui.sh platforms/macos/scripts/_launch-mac-device.sh
```

- [ ] **Step 2: Update its content**

Open `platforms/macos/scripts/_launch-mac-device.sh`. Replace any reference to `macbox-gui` in comments/echo statements with `mac-device`.

- [ ] **Step 3: Update setup-macos.sh**

In `platforms/macos/scripts/setup-macos.sh`:

```bash
PLIST_PATH="$HOME/Library/LaunchAgents/cc.metahub.mac-device.plist"
LABEL="cc.metahub.mac-device"
```

And update the inline-heredoc plist:

```xml
<key>Label</key><string>cc.metahub.mac-device</string>
...
<key>ProgramArguments</key>
<array>
  <string>/bin/bash</string>
  <string>$SCRIPT_DIR/_launch-mac-device.sh</string>
</array>
```

Search for any other `macbox-gui` reference in setup-macos.sh and replace with `mac-device`.

- [ ] **Step 4: Verify shell parsing**

Run: `bash -n platforms/macos/scripts/setup-macos.sh`
Expected: No output (script is syntactically valid).

- [ ] **Step 5: Re-run the regression test (count fewer failures)**

Run: `cd cli && uv run pytest tests/test_no_legacy_naming.py -v 2>&1 | grep -cE 'platforms/macos'`
Expected: 0 (no remaining macos legacy strings).

- [ ] **Step 6: Commit**

```bash
git add platforms/macos/
git commit -m "refactor(macos): rename launchd label + launch script to mac-device"
```

---

### Task 11: Rename skill directory using-macbox → using-mac

**Files:**
- Move: `platforms/macos/skills/using-macbox/` → `platforms/macos/skills/using-mac/`
- Modify: `platforms/macos/skills/using-mac/SKILL.md`

- [ ] **Step 1: Move directory**

```bash
git mv platforms/macos/skills/using-macbox platforms/macos/skills/using-mac
```

- [ ] **Step 2: Update SKILL.md content**

In `platforms/macos/skills/using-mac/SKILL.md`:
- Replace `macbox-gui` → `mac-device` (role name references)
- Replace `using-macbox` → `using-mac` (self-references)
- Update the `name:` field in the frontmatter from `using-macbox` to `using-mac`

```yaml
---
name: using-mac
description: Drive the Mac device via the mac-device MCP server (screenshots, clicks, AppleScript)
---
```

- [ ] **Step 3: Search for cross-refs**

```bash
grep -rn "using-macbox" .
```

Update any matches (README, docs/, scripts/install-agent-side.py).

- [ ] **Step 4: Commit**

```bash
git add platforms/macos/skills/ docs/ scripts/ README.md
git commit -m "refactor(macos): rename skill using-macbox → using-mac"
```

---

### Task 12: Rename Task Scheduler MCP-WindowsGui → MCP-WinDevice + launch script

**Files:**
- Modify: `platforms/windows/scripts/setup-windows.ps1`
- Modify: `platforms/windows/scripts/diagnose.ps1`
- Rename: `platforms/windows/scripts/_launch-windows-gui.ps1` → `_launch-win-device.ps1`
- Modify: `platforms/windows/scripts/_launch-win-device.ps1` (content)

- [ ] **Step 1: Rename launch script**

```bash
git mv platforms/windows/scripts/_launch-windows-gui.ps1 platforms/windows/scripts/_launch-win-device.ps1
```

- [ ] **Step 2: Update setup-windows.ps1**

Global replace in `platforms/windows/scripts/setup-windows.ps1`:
- `"MCP-WindowsGui"` → `"MCP-WinDevice"`
- `_launch-windows-gui.ps1` → `_launch-win-device.ps1`
- `winpc-gui` (in echo/comments) → `win-device`

Also update the historical-stop block:

```powershell
Stop-ScheduledTask -TaskName "MCP-WindowsGui" -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName "MCP-DesktopCommander" -ErrorAction SilentlyContinue
# Add: migrate any old MCP-WindowsGui task if found, then unregister
$oldTask = Get-ScheduledTask -TaskName "MCP-WindowsGui" -ErrorAction SilentlyContinue
if ($oldTask) {
    Stop-ScheduledTask -TaskName "MCP-WindowsGui" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "MCP-WindowsGui" -Confirm:$false
    Write-Host "  removed legacy task MCP-WindowsGui" -ForegroundColor Yellow
}
```

This is a migration helper so re-running setup on an old install doesn't double-register.

- [ ] **Step 3: Update diagnose.ps1**

Replace `MCP-WindowsGui` → `MCP-WinDevice` and `winpc-gui` → `win-device`.

- [ ] **Step 4: Verify PowerShell parses**

If a Linux pwsh is available:
```bash
pwsh -Command "& { $err = $null; [ScriptBlock]::Create((Get-Content -Raw platforms/windows/scripts/setup-windows.ps1)) > $null }; if ($err) { exit 1 }"
```

If not, skip — visual inspection of the diff is acceptable.

- [ ] **Step 5: Run regression test**

Run: `cd cli && uv run pytest tests/test_no_legacy_naming.py -v 2>&1 | grep -cE 'platforms/windows'`
Expected: 0.

- [ ] **Step 6: Commit**

```bash
git add platforms/windows/
git commit -m "refactor(windows): rename Task Scheduler entry + launch script to win-device"
```

---

### Task 13: Rename skill using-winpc → using-win

**Files:**
- Move: `platforms/windows/skills/using-winpc/` → `platforms/windows/skills/using-win/`
- Modify: `platforms/windows/skills/using-win/SKILL.md`

- [ ] **Step 1: Move + update**

```bash
git mv platforms/windows/skills/using-winpc platforms/windows/skills/using-win
```

In `SKILL.md`:
- frontmatter `name: using-winpc` → `using-win`
- description references
- body: replace `winpc-gui` → `win-device`, `using-winpc` → `using-win`

- [ ] **Step 2: Update cross-refs**

```bash
grep -rn "using-winpc" .
```

Patch each.

- [ ] **Step 3: Commit**

```bash
git add platforms/windows/ docs/ scripts/ README.md
git commit -m "refactor(windows): rename skill using-winpc → using-win"
```

---

### Task 14: Android scripts — Win Task Scheduler + Linux systemd + Mac launchd

**Files:**
- Modify: `platforms/android/scripts/setup-android.ps1`
- Modify: `platforms/android/scripts/setup-android.sh`
- Modify: `platforms/android/scripts/setup-android-linux.sh`
- Modify: `platforms/android/scripts/_launch-android.sh`
- Modify: `platforms/android/scripts/_launch-android.ps1`
- Modify: `platforms/android/server/android_mcp.py`
- Modify: `platforms/android/README.md`

- [ ] **Step 1: setup-android.ps1 (Windows host)**

Replace `MCP-AndroidGui` → `MCP-AndroidDevice` (TaskName + diagnose helper).
Add migration helper:

```powershell
$oldTask = Get-ScheduledTask -TaskName "MCP-AndroidGui" -ErrorAction SilentlyContinue
if ($oldTask) {
    Stop-ScheduledTask -TaskName "MCP-AndroidGui" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "MCP-AndroidGui" -Confirm:$false
    Write-Host "  removed legacy task MCP-AndroidGui" -ForegroundColor Yellow
}
```

Replace `android-gui` in echo/comments → `android-device`.

- [ ] **Step 2: setup-android.sh (Mac host)**

Replace launchd LABEL `cc.metahub.android-gui` → `cc.metahub.android-device` (verify exact existing value via grep first).

Replace `android-gui` in echo/comments → `android-device`.

- [ ] **Step 3: setup-android-linux.sh**

Replace systemd unit name `atb-android-gui.service` → `agent-fleet-android-device.service`.
Replace unit file path `$HOME/.config/systemd/user/atb-android-gui.service` → `$HOME/.config/systemd/user/agent-fleet-android-device.service`.
Add migration block:

```bash
# Stop + remove legacy unit if present
if systemctl --user list-unit-files | grep -q atb-android-gui.service; then
    systemctl --user stop atb-android-gui.service 2>/dev/null || true
    systemctl --user disable atb-android-gui.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/atb-android-gui.service"
    systemctl --user daemon-reload
    echo "  removed legacy unit atb-android-gui.service"
fi
```

Replace `android-gui` in echo/comments → `android-device`.

- [ ] **Step 4: _launch-android.{sh,ps1}**

Open both; replace any `android-gui` references in comments/echos → `android-device`.

- [ ] **Step 5: android_mcp.py + android/README.md**

Replace user-facing strings (log lines, error messages) referencing `android-gui` → `android-device`.

- [ ] **Step 6: Run regression test**

Run: `cd cli && uv run pytest tests/test_no_legacy_naming.py -v 2>&1 | grep -cE 'platforms/android'`
Expected: 0.

- [ ] **Step 7: Commit**

```bash
git add platforms/android/
git commit -m "refactor(android): rename role to android-device + systemd unit + Task Scheduler"
```

---

### Task 15: Update examples + scripts/install-agent-side.py

**Files:**
- Modify: `examples/multi-platform-claude-settings.json`
- Modify: `platforms/macos/examples/claude-settings.json`
- Modify: `platforms/windows/examples/claude-settings.json`
- Modify: `platforms/android/examples/claude-settings.json`
- Modify: `scripts/install-agent-side.py`

- [ ] **Step 1: Update each JSON example**

In each `claude-settings.json`, the mcpServers keys:
- `"macbox-gui"` → `"mac-device"`
- `"winpc-gui"` → `"win-device"`
- `"android-gui"` → `"android-device"`

Verify JSON validity:

```bash
for f in examples/*.json platforms/*/examples/*.json; do
    python3 -m json.tool "$f" > /dev/null && echo "ok: $f" || echo "INVALID: $f"
done
```

- [ ] **Step 2: Update scripts/install-agent-side.py**

```bash
grep -n "macbox-gui\|winpc-gui\|android-gui\|using-macbox\|using-winpc" scripts/install-agent-side.py
```

Replace each occurrence consistently.  This script's CLI flag `--platform <name>` previously accepted `macbox-gui` etc. — update to accept the new names.  If backward compatibility matters: keep legacy names as aliases that print a deprecation warning. For alpha → alpha, just rename.

- [ ] **Step 3: Run regression test**

Run: `cd cli && uv run pytest tests/test_no_legacy_naming.py -v 2>&1 | tail -15`
Expected: only docs/* remaining in failures.

- [ ] **Step 4: Commit**

```bash
git add examples/ platforms/*/examples/ scripts/install-agent-side.py
git commit -m "refactor: update JSON examples + install-agent-side.py for role rename"
```

---

### Task 16: Update docs/ + READMEs

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/agent-host-setup.md`
- Modify: `docs/install-pattern.md`
- Modify: `docs/platforms/macos.md`
- Modify: `docs/platforms/windows.md`
- Modify: `docs/roadmap.md`
- Modify: `platforms/macos/README.md`
- Modify: `platforms/windows/README.md`

- [ ] **Step 1: Update CHANGELOG with v0.6.0-alpha entry**

Prepend to `CHANGELOG.md`:

```markdown
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
```

- [ ] **Step 2: Update README.md**

Replace in `README.md`:
- ASCII diagram labels: `winpc-gui   :8766` → `win-device  :8766`; `macbox-gui  :8767` → `mac-device  :8767`; `android-gui :8768` → `android-device :8768`
- Status table column "Component": replace each `<x>-gui` → `<x>-device`
- Any code/text snippet mentioning the role names

- [ ] **Step 3: Update remaining docs**

For each file in `docs/agent-host-setup.md`, `docs/install-pattern.md`, `docs/platforms/macos.md`, `docs/platforms/windows.md`, `docs/roadmap.md`, `platforms/*/README.md`:

```bash
grep -ln "macbox-gui\|winpc-gui\|android-gui\|using-macbox\|using-winpc\|MCP-WindowsGui\|MCP-AndroidGui\|atb-android-gui\|cc.metahub.macbox-gui" \
    docs/ platforms/*/README.md README.md \
    | while read f; do
        sed -i \
            -e 's/macbox-gui/mac-device/g' \
            -e 's/winpc-gui/win-device/g' \
            -e 's/android-gui/android-device/g' \
            -e 's/using-macbox/using-mac/g' \
            -e 's/using-winpc/using-win/g' \
            -e 's/MCP-WindowsGui/MCP-WinDevice/g' \
            -e 's/MCP-AndroidGui/MCP-AndroidDevice/g' \
            -e 's/atb-android-gui\.service/agent-fleet-android-device.service/g' \
            -e 's/cc\.metahub\.macbox-gui/cc.metahub.mac-device/g' \
            "$f"
        echo "updated: $f"
    done
```

Then visually inspect git diff for context-inappropriate replacements (e.g., a sentence "previously this was `macbox-gui`" in CHANGELOG might be intentional and should stay — but CHANGELOG is allowlisted so it won't be touched by the regression test).

- [ ] **Step 4: Run regression test**

Run: `cd cli && uv run pytest tests/test_no_legacy_naming.py -v 2>&1 | tail -10`
Expected: PASS — no remaining legacy strings outside allowlist.

- [ ] **Step 5: Run full test suite**

Run: `cd cli && uv run pytest 2>&1 | tail -3`
Expected: all tests PASS (~60+ tests after additions).

- [ ] **Step 6: Commit**

```bash
git add README.md CHANGELOG.md docs/ platforms/*/README.md
git commit -m "docs: update README + CHANGELOG + platform docs for role rename"
```

---

### Task 17: Bump version to 0.6.0-alpha + update install.sh default

**Files:**
- Modify: `cli/src/fleet/__init__.py`
- Modify: `cli/pyproject.toml`
- Modify: `install.sh`
- Modify: `install.ps1`

- [ ] **Step 1: Bump version**

In `cli/src/fleet/__init__.py`:

```python
__version__ = "0.6.0a1"
```

In `cli/pyproject.toml`:

```toml
version = "0.6.0a1"
```

- [ ] **Step 2: Update installer defaults**

In `install.sh`:

```bash
AGENT_FLEET_VERSION="${AGENT_FLEET_VERSION:-v0.6.0-alpha}"
```

In `install.ps1`:

```powershell
$AGENT_FLEET_VERSION = if ($env:AGENT_FLEET_VERSION) { $env:AGENT_FLEET_VERSION } else { "v0.6.0-alpha" }
```

Also update any inline doc/help text mentioning `v0.5.0-alpha` → `v0.6.0-alpha`. And in `README.md` quick-start commands.

- [ ] **Step 3: Run smoke test**

Run: `cd cli && uv run pytest tests/test_cli_smoke.py -v`
Expected: `test_cli_version_flag` PASS and the captured output should now show `0.6.0a1`.

- [ ] **Step 4: Commit**

```bash
git add cli/ install.sh install.ps1 README.md
git commit -m "chore: bump version to 0.6.0-alpha + update installer defaults"
```

---

## Phase 4 — Final integration + retag

### Task 18: Final full-suite test + manual smoke

**Files:**
- (no file changes)

- [ ] **Step 1: Run full test suite**

Run: `cd cli && uv run pytest -v 2>&1 | tail -10`
Expected: all tests PASS.

- [ ] **Step 2: Smoke-test the installer**

```bash
rm -rf /tmp/agent-fleet-smoke && mkdir /tmp/agent-fleet-smoke && cd /tmp/agent-fleet-smoke
AGENT_FLEET_CLONE_DIR=/tmp/agent-fleet-smoke/clone bash /<this-repo>/install.sh --help
```

Expected output: install.sh fetches uv (or skips), clones from local repo to `/tmp/agent-fleet-smoke/clone`, runs `agent-fleet setup --help`, prints help.

(Note: smoke runs `--help` because `setup` is interactive; we just verify the CLI launches.)

- [ ] **Step 3: Verify dry-run wizard reaches end without crash**

Cannot fully test on Linux (no Tailscale/launchd), but `--dry-run` should at minimum print the dry-run skip messages:

```bash
cd /tmp/agent-fleet-smoke/clone
echo -e "" | uvx --from "git+file:///<this-repo>@HEAD#subdirectory=cli" agent-fleet setup --dry-run < /dev/null
```

If this errors with EOFError on stdin (expected — there's no TTY in agent harness), that's the right answer for dry-run with no TTY. Document this as: smoke validates "cli launches", not "wizard completes".

- [ ] **Step 4: Commit any cleanups**

If smoke test surfaced issues, fix and commit them with `fix: ...` messages.

---

### Task 19: Push branch, open PR, request review

**Files:**
- (no file changes)

- [ ] **Step 1: Push**

```bash
git push -u origin <feature-branch>
```

(Use a token-inlined URL since this repo's `origin` is password-less in the agent harness.)

- [ ] **Step 2: Open PR via gh or REST**

PR title: `feat(v0.6.0-alpha): rename roles to <os>-device + macOS permission primer`

PR body sketch:
```
## Breaking
- role IDs: macbox-gui → mac-device, winpc-gui → win-device, android-gui → android-device
- service labels: cc.metahub.macbox-gui → cc.metahub.mac-device; MCP-WindowsGui → MCP-WinDevice; MCP-AndroidGui → MCP-AndroidDevice; atb-android-gui → agent-fleet-android-device
- skill dirs: using-macbox → using-mac, using-winpc → using-win

## Added
- macOS TCC permission primer (cli/src/fleet/macos_perm.py): wizard auto-pops Accessibility / Screen Recording / Automation dialogs so Python.app pre-appears in System Settings (toggle the switch — no manual drag).
- Setup scripts auto-migrate legacy services on re-run.

## Tests
- 6 new tests in test_macos_perm.py (each primer fn mocked)
- 1 new global regression test (test_no_legacy_naming.py)
- Updated fixtures across 8 test files

## Migration
Migrate paths called out in CHANGELOG. Setup scripts run on existing v0.5.0-alpha installs detect-and-clean.
```

- [ ] **Step 3: Squash-merge via REST after self-review**

```bash
PR_NUM=<from PR creation>
curl -X PUT https://api.github.com/repos/metahub-tech/agent-fleet/pulls/${PR_NUM}/merge \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"merge_method\":\"squash\",\"commit_title\":\"feat(v0.6.0-alpha): rename roles + permission primer (#${PR_NUM})\"}"
```

- [ ] **Step 4: Cut new tag v0.6.0-alpha**

After merge, get the new head sha from origin/main:

```bash
NEW_SHA=$(git rev-parse origin/main)
curl -X POST https://api.github.com/repos/metahub-tech/agent-fleet/git/refs \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"ref\":\"refs/tags/v0.6.0-alpha\",\"sha\":\"${NEW_SHA}\"}"
```

Optionally create a GitHub Release for the tag with copy-pasted CHANGELOG entry.

- [ ] **Step 5: Verify**

```bash
curl -s https://api.github.com/repos/metahub-tech/agent-fleet/git/refs/tags/v0.6.0-alpha \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['ref'], '→', d['object']['sha'])"
```

Expected: `refs/tags/v0.6.0-alpha → <NEW_SHA>`.

---

## Self-Review Notes

After writing the plan, applied the checklist from writing-plans:

**1. Spec coverage:** All renames in the identifier mapping table have a corresponding task. Permission primer has tasks 1-6. Regression test (Task 9) catches accidental misses. Version bump (Task 17) and release flow (Task 19) cover delivery.

**2. Placeholder scan:** No TBDs. Code blocks are complete (importable functions, full YAML bodies). Where global text replacement is appropriate, the `sed -i` invocation is shown verbatim.

**3. Type consistency:**
- `SettingsPane` enum members used consistently in Tasks 1-5.
- `prime_*` function signatures: 3 take `venv_python: Path`, `prime_automation()` and `prime_full_disk_access()` take no args — documented in each task.
- `_run_guidance(roles, ctx)` signature change in Task 6 — call site update specified.
- `GuidanceStep.id` field — Task 6 explicitly checks and adds if missing.

**Scope edges noted:**
- `ATB_ANDROID_*` env vars and `~/.atb-android/` config dir stay (would multiply blast radius without proportional value).
- Server entry-point file names (`*_gui_mcp.py`) stay (internal, would require import-path coordination).
- `platforms/<os>/` dir layout stays.

These exclusions are explicit in the identifier mapping table.
