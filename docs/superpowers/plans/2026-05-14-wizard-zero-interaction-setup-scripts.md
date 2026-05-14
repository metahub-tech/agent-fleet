# wizard 模式下 setup 脚本零交互 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 android-device 的 ADB-mode / config-reuse 交互、以及 setup-windows.ps1 的 Tailscale-not-installed 暂停点，从 setup 脚本上提到 Python wizard，用环境变量驱动脚本，根治 wizard 管道捕获与脚本内 `Read-Host` 冲突导致的卡死/错乱。

**Architecture:** wizard（`cli/src/fleet/cli.py`）在跑 installer 前用 questionary 收集 android 选择，存进 `InstallContext`。一个新 helper `installers/_env.py:setup_env()` 把选择转成 env dict（`ATB_WIZARD_MANAGED` + `ATB_ANDROID_MODE`/`ATB_ANDROID_REUSE_CONFIG`），三个 installer 的 `subprocess.Popen` 加 `env=`。4 个 setup 脚本改成"env var 有值就用、没值 fallback 到原交互"。

**Tech Stack:** Python 3.10+（questionary, subprocess, dataclasses）、PowerShell、bash。

**Spec:** `docs/superpowers/specs/2026-05-14-wizard-zero-interaction-setup-scripts-design.md`

---

## File Structure

**新建:**
- `cli/src/fleet/installers/_env.py` — `setup_env(ctx, role_id) -> dict[str,str]`：构造传给 setup 脚本的环境变量
- `cli/tests/test_installers_env.py` — `setup_env` 的单元测试

**修改:**
- `cli/src/fleet/types.py` — `InstallContext` 加 `android_mode` / `android_reuse_config` 字段
- `cli/src/fleet/wizard.py` — `build_install_context` 加对应参数
- `cli/src/fleet/cli.py` — 新增 `_select_android_config()`；`cmd_setup` 在 installer 前调用它
- `cli/src/fleet/installers/windows.py` — `_run_setup_ps1` 的 Popen 加 `env=setup_env(...)`
- `cli/src/fleet/installers/macos.py` — 两处 Popen 加 `env=setup_env(...)`
- `cli/src/fleet/installers/linux.py` — Popen 加 `env=setup_env(...)`
- `platforms/android/scripts/setup-android.ps1` — ADB mode 步骤参数驱动 + fallback
- `platforms/android/scripts/setup-android.sh` — 同上
- `platforms/android/scripts/setup-android-linux.sh` — 同上
- `platforms/windows/scripts/setup-windows.ps1` — L109 `Read-Host` 在 wizard 模式下改 `exit 1`
- `cli/pyproject.toml`, `cli/src/fleet/__init__.py`, `cli/tests/test_smoke.py`, `install.sh`, `install.ps1` — 版本 0.6.13 → 0.6.14
- `CHANGELOG.md` — 新增 `[0.6.14-alpha]` entry

**测试命令说明:** 项目标准是 `uv run pytest`。若环境无 `uv`，用 `python3 -m pytest`（需先 `pip install pytest`）。本 plan 各步统一写 `python3 -m pytest`；执行者按环境调整。

---

## Task 1: `InstallContext` 加 android 字段

**Files:**
- Modify: `cli/src/fleet/types.py:47-53`
- Modify: `cli/src/fleet/wizard.py:9-19`

- [ ] **Step 1: 给 `InstallContext` 加两个字段**

`cli/src/fleet/types.py` 的 `InstallContext` dataclass（当前 L47-53）改成：

```python
@dataclass
class InstallContext:
    repo_root: str             # absolute path to agent-fleet repo
    os_info: OSInfo
    dry_run: bool = False
    selected_network: Literal["lan", "tailscale"] = "tailscale"
    tailscale_hostname: Optional[str] = None
    android_mode: Optional[str] = None        # "usb"/"wireless"/"hybrid", collected by wizard
    android_reuse_config: bool = False        # True = reuse existing ~/.atb-android/config.toml
```

- [ ] **Step 2: 给 `build_install_context` 加对应参数**

`cli/src/fleet/wizard.py` 的 `build_install_context`（当前 L9-19）改成：

```python
def build_install_context(
    *, repo_root: str, os_info: OSInfo, dry_run: bool,
    network: Literal["lan", "tailscale"], tailscale_hostname: str | None,
    android_mode: str | None = None, android_reuse_config: bool = False,
) -> InstallContext:
    return InstallContext(
        repo_root=repo_root,
        os_info=os_info,
        dry_run=dry_run,
        selected_network=network,
        tailscale_hostname=tailscale_hostname,
        android_mode=android_mode,
        android_reuse_config=android_reuse_config,
    )
```

- [ ] **Step 3: 跑现有测试确认没破坏**

Run: `cd cli && python3 -m pytest tests/test_types.py tests/test_smoke.py -v`
Expected: PASS（新字段都有默认值，现有构造点不受影响）

- [ ] **Step 4: Commit**

```bash
git add cli/src/fleet/types.py cli/src/fleet/wizard.py
git commit -m "feat: InstallContext carries android_mode / android_reuse_config"
```

---

## Task 2: `setup_env` helper（TDD）

**Files:**
- Create: `cli/src/fleet/installers/_env.py`
- Test: `cli/tests/test_installers_env.py`

- [ ] **Step 1: 写失败的测试**

创建 `cli/tests/test_installers_env.py`:

```python
from fleet.types import InstallContext, OSInfo
from fleet.installers._env import setup_env


def _ctx(**kw):
    osi = OSInfo(system="Linux", version="6.1", arch="x86_64", is_apple_silicon=False)
    return InstallContext(repo_root="/tmp/repo", os_info=osi, **kw)


def test_win_device_only_gets_wizard_managed():
    env = setup_env(_ctx(), "win-device")
    assert env["ATB_WIZARD_MANAGED"] == "1"
    assert "ATB_ANDROID_MODE" not in env
    assert "ATB_ANDROID_REUSE_CONFIG" not in env


def test_android_reuse_config():
    env = setup_env(_ctx(android_reuse_config=True), "android-device")
    assert env["ATB_WIZARD_MANAGED"] == "1"
    assert env["ATB_ANDROID_REUSE_CONFIG"] == "1"
    assert "ATB_ANDROID_MODE" not in env


def test_android_mode():
    env = setup_env(_ctx(android_mode="usb"), "android-device")
    assert env["ATB_WIZARD_MANAGED"] == "1"
    assert env["ATB_ANDROID_MODE"] == "usb"
    assert "ATB_ANDROID_REUSE_CONFIG" not in env


def test_android_reuse_wins_over_mode():
    # wizard never sets both, but reuse must take precedence if it ever happens
    env = setup_env(_ctx(android_mode="usb", android_reuse_config=True), "android-device")
    assert env["ATB_ANDROID_REUSE_CONFIG"] == "1"
    assert "ATB_ANDROID_MODE" not in env


def test_android_no_choice_only_wizard_managed():
    # android-device selected but no mode collected (shouldn't happen via wizard,
    # but setup_env must not crash) — scripts will fall back to interactive
    env = setup_env(_ctx(), "android-device")
    assert env["ATB_WIZARD_MANAGED"] == "1"
    assert "ATB_ANDROID_MODE" not in env
    assert "ATB_ANDROID_REUSE_CONFIG" not in env


def test_inherits_parent_env():
    env = setup_env(_ctx(), "win-device")
    assert "PATH" in env  # parent process env preserved
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd cli && python3 -m pytest tests/test_installers_env.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.installers._env'`

- [ ] **Step 3: 实现 `_env.py`**

创建 `cli/src/fleet/installers/_env.py`:

```python
"""Environment variables passed from the wizard to platform setup scripts.

The wizard captures all interactive choices (ADB mode, config reuse) up front
via questionary, then hands them to the setup scripts as env vars so the
scripts never block on Read-Host/read inside the wizard's piped stdout.

See docs/superpowers/specs/2026-05-14-wizard-zero-interaction-setup-scripts-design.md
"""
from __future__ import annotations

import os

from ..types import InstallContext


def setup_env(ctx: InstallContext, role_id: str) -> dict[str, str]:
    """Build the env dict for a setup-script subprocess.

    ATB_WIZARD_MANAGED=1 is always set so scripts skip every Read-Host/read
    pause point. android-device additionally gets the mode / reuse choice.
    Built on top of os.environ so PATH and friends survive.
    """
    env = {**os.environ, "ATB_WIZARD_MANAGED": "1"}
    if role_id == "android-device":
        if ctx.android_reuse_config:
            env["ATB_ANDROID_REUSE_CONFIG"] = "1"
        elif ctx.android_mode:
            env["ATB_ANDROID_MODE"] = ctx.android_mode
    return env
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd cli && python3 -m pytest tests/test_installers_env.py -v`
Expected: PASS（6 个测试全过）

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/installers/_env.py cli/tests/test_installers_env.py
git commit -m "feat: setup_env helper builds wizard→script env vars"
```

---

## Task 3: 三个 installer 接入 `setup_env`

**Files:**
- Modify: `cli/src/fleet/installers/windows.py:1-10,28-32`
- Modify: `cli/src/fleet/installers/macos.py:1-11,36-40,106`
- Modify: `cli/src/fleet/installers/linux.py:1-9,30`

- [ ] **Step 1: `windows.py` — import + Popen 加 env**

`cli/src/fleet/installers/windows.py` 顶部 import 区加一行（在现有 `from .base import BaseInstaller` 附近）：

```python
from ._env import setup_env
```

把 `_run_setup_ps1` 里的 `subprocess.Popen(...)`（当前 L28-32）改成：

```python
    proc = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_wrapped],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
        encoding="utf-8", errors="replace",
        env=setup_env(ctx, role_id),
    )
```

- [ ] **Step 2: `macos.py` — import + 两处 Popen 加 env**

`cli/src/fleet/installers/macos.py` 顶部 import 区加：

```python
from ._env import setup_env
```

`MacosDesktop.install` 里的 Popen（当前 L36-40）改成：

```python
        proc = subprocess.Popen(
            ["bash", str(setup)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=1, encoding="utf-8", errors="replace",
            env=setup_env(ctx, self.role_id),
        )
```

`MacosAndroidBridge.install` 里的 Popen（当前 L106）改成：

```python
        proc = subprocess.Popen(["bash", str(setup)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, encoding="utf-8", errors="replace", env=setup_env(ctx, self.role_id))
```

- [ ] **Step 3: `linux.py` — import + Popen 加 env**

`cli/src/fleet/installers/linux.py` 顶部 import 区加：

```python
from ._env import setup_env
```

`LinuxAndroidBridge.install` 里的 Popen（当前 L30）改成：

```python
        proc = subprocess.Popen(["bash", str(setup)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, encoding="utf-8", errors="replace", env=setup_env(ctx, self.role_id))
```

- [ ] **Step 4: 跑 installer 相关测试确认没破坏**

Run: `cd cli && python3 -m pytest tests/test_installers_base.py tests/test_installers_windows.py tests/test_installers_macos.py tests/test_installers_linux.py tests/test_installers_registry.py -v`
Expected: PASS（这些测试不实际跑 subprocess；加 `env=` 不影响它们）

- [ ] **Step 5: Commit**

```bash
git add cli/src/fleet/installers/windows.py cli/src/fleet/installers/macos.py cli/src/fleet/installers/linux.py
git commit -m "feat: installers pass setup_env() to setup-script subprocesses"
```

---

## Task 4: wizard 端 — `_select_android_config` + cmd_setup 集成

**Files:**
- Modify: `cli/src/fleet/cli.py:1-20`（import）, 新增函数, `cli/src/fleet/cli.py:245-261`（cmd_setup）

- [ ] **Step 1: 确认 import 齐全**

`cli/src/fleet/cli.py` 顶部已有 `import questionary`、`from pathlib import Path`、`from rich.panel import Panel`、`console = Console()`。无需新增 import（`_select_android_config` 用到的都在）。

- [ ] **Step 2: 新增 `_select_android_config` 函数**

在 `cli/src/fleet/cli.py` 中，`_select_network` 函数之后、`_select_frameworks` 之前，插入：

```python
def _select_android_config(repo_root: str) -> tuple[Optional[str], bool]:
    """Collect android-device's ADB-mode / config-reuse choice up front.

    Returns (android_mode, android_reuse_config). Called only when
    android-device is among the selected roles, BEFORE installers run, so the
    setup scripts receive the answer as an env var and never block on a
    Read-Host/read inside the wizard's piped stdout.

    repo_root is accepted for signature symmetry with other wizard helpers;
    the android config lives under the user's home, not the repo.
    """
    config_path = Path.home() / ".atb-android" / "config.toml"
    if config_path.exists():
        console.print(f"\n[bold]Existing android-device config[/bold] [dim]({config_path})[/dim]:")
        console.print(Panel(config_path.read_text(encoding="utf-8", errors="replace").rstrip()))
        if questionary.confirm("Reuse this config?", default=True).ask():
            return None, True
    mode = questionary.select(
        "ADB connection mode:",
        choices=[
            questionary.Choice("USB only  (cable required; per-plug auth on phone)", value="usb"),
            questionary.Choice("Wireless Debugging  (Android 11+ / HarmonyOS 4 native pairing)", value="wireless"),
            questionary.Choice("Hybrid  (USB enroll then adb tcpip 5555; Android 5-10)", value="hybrid"),
        ],
    ).ask()
    return (mode or "usb"), False
```

- [ ] **Step 3: 在 `cmd_setup` 里调用它**

`cli/src/fleet/cli.py` 的 `cmd_setup`（当前 L245-260）改成：

```python
def cmd_setup(args: argparse.Namespace) -> int:
    osi, ts = _banner()
    roles = _select_roles(osi)
    if not roles:
        console.print("[yellow]No roles selected — exiting.[/yellow]")
        return 0
    network = _select_network(ts)
    hostname = ts.hostname if ts else None

    # android-device's ADB-mode / config-reuse choice is collected here, up
    # front, so the setup script gets it as an env var (ATB_ANDROID_MODE /
    # ATB_ANDROID_REUSE_CONFIG) instead of blocking on Read-Host inside the
    # wizard's piped stdout.
    android_mode = None
    android_reuse_config = False
    if any(r.role_id == "android-device" for r in roles):
        android_mode, android_reuse_config = _select_android_config(str(Path.cwd()))

    ctx = build_install_context(
        repo_root=str(Path.cwd()),
        os_info=osi,
        dry_run=args.dry_run,
        network=network,
        tailscale_hostname=hostname,
        android_mode=android_mode,
        android_reuse_config=android_reuse_config,
    )
```

（`cmd_setup` 的其余部分 L262 起不变。）

- [ ] **Step 4: 跑 cli smoke 测试确认 import / 语法 OK**

Run: `cd cli && python3 -m pytest tests/test_cli_smoke.py tests/test_smoke_module.py -v`
Expected: PASS（这些测试 import `fleet.cli` 不实际跑 questionary；新函数加进去不破坏 import）

- [ ] **Step 5: 手动冒烟 — dry-run 不应卡住**

Run: `cd cli && python3 -m fleet setup --dry-run </dev/null` （或 `python3 -c "from fleet.cli import _select_android_config"` 确认可 import）
Expected: 能 import，`_select_android_config` 是可调用对象。完整交互需真机验证（见 Task 7 之后）。

- [ ] **Step 6: Commit**

```bash
git add cli/src/fleet/cli.py
git commit -m "feat: wizard collects android ADB-mode / config-reuse before installers run"
```

---

## Task 5: 三个 android setup 脚本参数驱动 + fallback

**Files:**
- Modify: `platforms/android/scripts/setup-android.ps1:143-184`
- Modify: `platforms/android/scripts/setup-android.sh:188-231`
- Modify: `platforms/android/scripts/setup-android-linux.sh:121-164`

- [ ] **Step 1: 改 `setup-android.ps1` 的 ADB connection mode 步骤**

把 `platforms/android/scripts/setup-android.ps1` 当前 L143-184（`# ---------- 5. ADB connection mode ----------` 到该 if 块结束）整段替换为：

```powershell
# ---------- 5. ADB connection mode ----------
# Priority:
#   1. ATB_ANDROID_REUSE_CONFIG=1  -> keep existing config, skip everything
#   2. ATB_ANDROID_MODE=<mode>     -> wizard already asked; use it non-interactively
#   3. interactive fallback        -> standalone run (no wizard); stdout is a real terminal
Write-Host ""
Write-Host "[5/9] ADB connection mode" -ForegroundColor Cyan

$modeName = $null
$reuseConfig = $false

if ($env:ATB_ANDROID_REUSE_CONFIG -eq "1") {
    if (Test-Path $ConfigPath) {
        Write-Host "  ok  reusing existing config $ConfigPath"
        $reuseConfig = $true
    } else {
        Write-Host "  ATB_ANDROID_REUSE_CONFIG=1 but $ConfigPath missing -- selecting mode instead" -ForegroundColor Yellow
    }
}

if (-not $reuseConfig) {
    if ($env:ATB_ANDROID_MODE) {
        $modeName = $env:ATB_ANDROID_MODE
        if ($modeName -notin @("usb", "wireless", "hybrid")) {
            Write-Host "  ERROR: ATB_ANDROID_MODE='$modeName' invalid (expected usb/wireless/hybrid)" -ForegroundColor Red
            exit 1
        }
        Write-Host "  using ADB mode from wizard: $modeName"
    } else {
        # interactive fallback -- standalone run
        if (Test-Path $ConfigPath) {
            Write-Host "  existing $ConfigPath found:"
            Get-Content $ConfigPath | ForEach-Object { Write-Host "    $_" }
            $reuse = Read-Host "  reuse it? [Y/n]"
            if ($reuse -ne "n" -and $reuse -ne "N") {
                Write-Host "  ok  using existing config"
                $reuseConfig = $true
            }
        }
        if (-not $reuseConfig) {
            Write-Host "  Choose ADB connection mode:"
            Write-Host "    1) USB only             (cable always required; per-plug authorization on phone)"
            Write-Host "    2) Wireless Debugging   (Android 11+ / HarmonyOS 4 native pairing)"
            Write-Host "    3) Hybrid (USB enroll)  (Android 5-10 -- adb tcpip 5555; reconnect after each phone reboot)"
            do { $m = Read-Host "  mode [1/2/3]" } while ($m -notin @("1", "2", "3"))
            $modeName = switch ($m) { "1" {"usb"} "2" {"wireless"} "3" {"hybrid"} }
        }
    }
}

if (-not $reuseConfig) {
    if (-not (Test-Path $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir | Out-Null }
    $config = @"
# agent-fleet / android-device server config
# Generated by setup-android.ps1
mode = "$modeName"

[host]
os = "windows"
adb_path = "$($adbCmd.Source.Replace('\','\\'))"
"@
    if ($modeName -eq "wireless") {
        $config += @"

[wireless]
# After pairing, set device_address to "<phone-ip>:<port>"
# device_address = "192.168.1.42:5555"
"@
    }
    Set-Content -Path $ConfigPath -Value $config -Encoding UTF8
    Write-Host "  ok  wrote $ConfigPath (mode=$modeName)"
}
```

- [ ] **Step 2: 改 `setup-android.sh` 的 ADB connection mode 步骤**

把 `platforms/android/scripts/setup-android.sh` 当前 L188-231（`# ---------- 5. ADB connection mode ----------` 到 `fi` + 该步骤的 `echo` 结束）整段替换为：

```bash
# ---------- 5. ADB connection mode ----------
# Priority:
#   1. ATB_ANDROID_REUSE_CONFIG=1  -> keep existing config, skip everything
#   2. ATB_ANDROID_MODE=<mode>     -> wizard already asked; use it non-interactively
#   3. interactive fallback        -> standalone run (no wizard)
LAST_STEP="[5/8] ADB connection mode"
echo "$LAST_STEP"
mkdir -p "$CONFIG_DIR"
REUSE=0
MODE_NAME=""

if [ "$ATB_ANDROID_REUSE_CONFIG" = "1" ]; then
    if [ -f "$CONFIG_PATH" ]; then
        echo "  ok reusing existing config $CONFIG_PATH"
        REUSE=1
    else
        echo "  ATB_ANDROID_REUSE_CONFIG=1 but $CONFIG_PATH missing -- selecting mode instead"
    fi
fi

if [ "$REUSE" -eq 0 ]; then
    if [ -n "$ATB_ANDROID_MODE" ]; then
        case "$ATB_ANDROID_MODE" in
            usb|wireless|hybrid) MODE_NAME="$ATB_ANDROID_MODE" ;;
            *) echo "  ERROR: ATB_ANDROID_MODE='$ATB_ANDROID_MODE' invalid (expected usb/wireless/hybrid)"; exit 1 ;;
        esac
        echo "  using ADB mode from wizard: $MODE_NAME"
    else
        # interactive fallback -- standalone run
        if [ -f "$CONFIG_PATH" ]; then
            echo "  existing $CONFIG_PATH found:"
            cat "$CONFIG_PATH"
            echo "  Press Enter to keep this config, or 'n' to switch ADB mode (USB/Wireless/Hybrid):"
            read -r ans
            if [[ "$ans" != "n" && "$ans" != "N" ]]; then
                REUSE=1
                echo "  ok using existing config"
            fi
        fi
        if [ "$REUSE" -eq 0 ]; then
            echo "  Choose ADB connection mode:"
            echo "    1) USB only             (cable always required)"
            echo "    2) Wireless Debugging   (Android 11+ / SDK 30+ -- some HarmonyOS 4 phones report Android 10, in which case use 3)"
            echo "    3) Hybrid (USB enroll)  (Android 5-10 -- adb tcpip 5555; reconnect after each phone reboot)"
            while true; do
                echo "  mode [1/2/3]:"
                read -r mode
                case "$mode" in
                    1) MODE_NAME="usb"; break ;;
                    2) MODE_NAME="wireless"; break ;;
                    3) MODE_NAME="hybrid"; break ;;
                    *) echo "  invalid; pick 1/2/3" ;;
                esac
            done
        fi
    fi
fi

if [ "$REUSE" -eq 0 ]; then
    cat > "$CONFIG_PATH" <<EOF
# agent-fleet / android-device server config (macOS host)
mode = "$MODE_NAME"

[host]
os = "macos"
adb_path = "$ADB_PATH"
EOF
    echo "  ok wrote $CONFIG_PATH (mode=$MODE_NAME)"
fi
echo
```

- [ ] **Step 3: 改 `setup-android-linux.sh` 的 ADB connection mode 步骤**

把 `platforms/android/scripts/setup-android-linux.sh` 当前 L121-164（`# ---------- 5. ADB connection mode ----------` 到 `fi` + `echo`）整段替换为：

```bash
# ---------- 5. ADB connection mode ----------
# Priority:
#   1. ATB_ANDROID_REUSE_CONFIG=1  -> keep existing config, skip everything
#   2. ATB_ANDROID_MODE=<mode>     -> wizard already asked; use it non-interactively
#   3. interactive fallback        -> standalone run (no wizard)
LAST_STEP="[5/8] ADB connection mode"
echo "$LAST_STEP"
mkdir -p "$CONFIG_DIR"
REUSE=0
MODE_NAME=""

if [ "$ATB_ANDROID_REUSE_CONFIG" = "1" ]; then
    if [ -f "$CONFIG_PATH" ]; then
        echo "  ok reusing existing config $CONFIG_PATH"
        REUSE=1
    else
        echo "  ATB_ANDROID_REUSE_CONFIG=1 but $CONFIG_PATH missing -- selecting mode instead"
    fi
fi

if [ "$REUSE" -eq 0 ]; then
    if [ -n "$ATB_ANDROID_MODE" ]; then
        case "$ATB_ANDROID_MODE" in
            usb|wireless|hybrid) MODE_NAME="$ATB_ANDROID_MODE" ;;
            *) echo "  ERROR: ATB_ANDROID_MODE='$ATB_ANDROID_MODE' invalid (expected usb/wireless/hybrid)"; exit 1 ;;
        esac
        echo "  using ADB mode from wizard: $MODE_NAME"
    else
        # interactive fallback -- standalone run
        if [ -f "$CONFIG_PATH" ]; then
            echo "  existing $CONFIG_PATH found:"
            cat "$CONFIG_PATH"
            echo "  Press Enter to keep this config, or 'n' to switch ADB mode (USB/Wireless/Hybrid):"
            read -r ans
            if [[ "$ans" != "n" && "$ans" != "N" ]]; then
                REUSE=1
                echo "  ok using existing config"
            fi
        fi
        if [ "$REUSE" -eq 0 ]; then
            echo "  Choose ADB connection mode:"
            echo "    1) USB only             (cable always required)"
            echo "    2) Wireless Debugging   (Android 11+ / SDK 30+ -- some HarmonyOS 4 phones report Android 10, in which case use 3)"
            echo "    3) Hybrid (USB enroll)  (Android 5-10 -- adb tcpip 5555; reconnect after each phone reboot)"
            while true; do
                echo "  mode [1/2/3]:"
                read -r mode
                case "$mode" in
                    1) MODE_NAME="usb"; break ;;
                    2) MODE_NAME="wireless"; break ;;
                    3) MODE_NAME="hybrid"; break ;;
                    *) echo "  invalid; pick 1/2/3" ;;
                esac
            done
        fi
    fi
fi

if [ "$REUSE" -eq 0 ]; then
    cat > "$CONFIG_PATH" <<EOF
# agent-fleet / android-device server config (Linux host)
mode = "$MODE_NAME"

[host]
os = "linux"
adb_path = "$ADB_PATH"
EOF
    echo "  ok wrote $CONFIG_PATH (mode=$MODE_NAME)"
fi
echo
```

- [ ] **Step 4: bash 语法检查**

Run: `bash -n platforms/android/scripts/setup-android.sh && bash -n platforms/android/scripts/setup-android-linux.sh && echo "bash syntax OK"`
Expected: `bash syntax OK`

- [ ] **Step 5: bash fallback 路径冒烟（无 env var → 走交互；有 env var → 不交互）**

Run:
```bash
ATB_ANDROID_MODE=usb bash -c '
ATB_ANDROID_REUSE_CONFIG=""; ATB_ANDROID_MODE="usb"; CONFIG_PATH=/tmp/atbtest.toml; CONFIG_DIR=/tmp; ADB_PATH=/usr/bin/adb; REUSE=0; MODE_NAME=""
if [ -n "$ATB_ANDROID_MODE" ]; then case "$ATB_ANDROID_MODE" in usb|wireless|hybrid) MODE_NAME="$ATB_ANDROID_MODE";; *) exit 1;; esac; fi
echo "resolved MODE_NAME=$MODE_NAME"
'
```
Expected: `resolved MODE_NAME=usb`（验证 env-var 分支逻辑；完整脚本需真机跑）

- [ ] **Step 6: Commit**

```bash
git add platforms/android/scripts/setup-android.ps1 platforms/android/scripts/setup-android.sh platforms/android/scripts/setup-android-linux.sh
git commit -m "feat: android setup scripts are env-var driven, fall back to interactive when run standalone"
```

---

## Task 6: `setup-windows.ps1` L109 — wizard 模式下 exit 而非 Read-Host

**Files:**
- Modify: `platforms/windows/scripts/setup-windows.ps1:105-110`

- [ ] **Step 1: 改 Tailscale-not-installed 分支**

把 `platforms/windows/scripts/setup-windows.ps1` 当前 L105-110 替换为：

```powershell
if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    Write-Host "  installing Tailscale..."
    winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
    Write-Host "  -> Open the Tailscale tray icon, click Login, then come back." -ForegroundColor Magenta
    if ($env:ATB_WIZARD_MANAGED -eq "1") {
        # Under the wizard, stdout is a pipe — a Read-Host prompt would hang
        # invisibly. Exit cleanly instead; the wizard surfaces the rc=1 and the
        # message above tells the user to log in to Tailscale and re-run.
        Write-Host "  Tailscale was just installed. Log in via the tray icon, then re-run the wizard." -ForegroundColor Yellow
        exit 1
    }
    Read-Host "  Press Enter to continue"
}
```

- [ ] **Step 2: 人工核对**

Read `platforms/windows/scripts/setup-windows.ps1:105-116`，确认替换后 `$tsRaw = tailscale status --json` 那行（原 L111）仍紧跟在 `}` 之后，缩进与语法完整。

Expected: 替换段后面无缝接上原有的 `$tsRaw = tailscale status --json 2>$null` 逻辑。

- [ ] **Step 3: Commit**

```bash
git add platforms/windows/scripts/setup-windows.ps1
git commit -m "fix: setup-windows.ps1 exits cleanly instead of Read-Host under the wizard"
```

---

## Task 7: 版本 bump 0.6.13 → 0.6.14 + CHANGELOG

**Files:**
- Modify: `cli/pyproject.toml`, `cli/src/fleet/__init__.py`, `cli/tests/test_smoke.py`, `install.sh`, `install.ps1`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: bump 5 个版本文件**

Run:
```bash
for f in cli/pyproject.toml cli/src/fleet/__init__.py cli/tests/test_smoke.py install.sh install.ps1; do
  sed -i 's/0\.6\.13/0.6.14/g' "$f"
done
grep -rn "0\.6\.1[34]" cli/pyproject.toml cli/src/fleet/__init__.py cli/tests/test_smoke.py install.sh install.ps1
```
Expected: 所有匹配都是 `0.6.14` / `0.6.14a1` / `v0.6.14-alpha`，无 `0.6.13` 残留。

- [ ] **Step 2: CHANGELOG 加 entry**

在 `CHANGELOG.md` 的 `## [0.6.13-alpha] - 2026-05-14` 这一行**之前**插入：

```markdown
## [0.6.14-alpha] - 2026-05-14

### Fixed

- **`agent-fleet setup` wizard no longer hangs or garbles prompts when a platform setup script needs user input.** The wizard captures setup-script output through a pipe (`subprocess.Popen(stdout=PIPE)`) to render it as progress. But a script's `Read-Host`/`read` prompt has no trailing newline, so it stalls in the pipe buffer — and the script shares the wizard's stdin, so typed input went nowhere. On Windows this fully broke `setup-android.ps1`'s "reuse config?" and "ADB mode [1/2/3]" prompts. Fix: all interactive choices are now collected **up front by the wizard** via questionary (same arrow-key UI as role selection) and handed to the scripts as env vars (`ATB_WIZARD_MANAGED`, `ATB_ANDROID_MODE`, `ATB_ANDROID_REUSE_CONFIG`). The setup scripts are env-var driven under the wizard and fall back to their original interactive prompts when run standalone. `setup-windows.ps1`'s lone `Read-Host "Press Enter"` (Tailscale-not-installed branch) now exits cleanly under the wizard instead of hanging.

```

- [ ] **Step 3: 跑全套 cli 测试**

Run: `cd cli && python3 -m pytest -v`
Expected: PASS（含新的 `test_installers_env.py`、更新后的 `test_smoke.py` 断言 `0.6.14a1`、`test_no_legacy_naming.py`）

- [ ] **Step 4: Commit**

```bash
git add cli/pyproject.toml cli/src/fleet/__init__.py cli/tests/test_smoke.py install.sh install.ps1 CHANGELOG.md
git commit -m "chore(v0.6.14-alpha): bump version + CHANGELOG for wizard zero-interaction fix"
```

---

## 收尾（plan 执行完之后）

- 全套 `python3 -m pytest` 通过、`bash -n` 三个 bash 脚本通过。
- 派 reviewer agent 审整个 diff（重点：env 传递正确性、4 个脚本的三分支逻辑、fallback 路径未被破坏、PowerShell `$env:` 读取语法）。
- 出 PR、squash-merge、打 `v0.6.14-alpha` tag。
- 真机验证：在 `win-personal-qjl` 上跑完整 `install.ps1` wizard 流程，确认三个原始现象（reuse prompt 错位 / 输入无响应 / 裸 1/2/3）全部消失，questionary 箭头选择正常。

---

## Self-Review

**1. Spec coverage:**
- 传参机制（env var）→ Task 2（`setup_env`）+ Task 3（installer 接入）✓
- wizard 端 questionary → Task 4 ✓
- 3 个 android 脚本参数驱动 + fallback → Task 5 ✓
- setup-windows.ps1 L109 → Task 6 ✓
- `InstallContext` 载体 → Task 1 ✓
- 版本 + CHANGELOG → Task 7 ✓
- 测试策略（setup_env 可单元测，其余手动+reviewer）→ Task 2 单元测 + 收尾真机验证 ✓
- 无遗漏。

**2. Placeholder scan:** 每个改代码的 step 都给了完整代码块，无 TBD/TODO/"similar to"。Task 5 的三个脚本虽相似但各自给了完整代码（含平台差异：`os = "windows/macos/linux"`、`adb_path` 来源、注释里的 host 标注）。

**3. Type consistency:**
- `InstallContext.android_mode: Optional[str]` / `android_reuse_config: bool`（Task 1）↔ `build_install_context` 参数（Task 1）↔ `setup_env` 读 `ctx.android_reuse_config` / `ctx.android_mode`（Task 2）↔ `cmd_setup` 传 `android_mode=` / `android_reuse_config=`（Task 4）— 一致。
- env var 名 `ATB_WIZARD_MANAGED` / `ATB_ANDROID_MODE` / `ATB_ANDROID_REUSE_CONFIG`：Task 2 写入 ↔ Task 5 脚本 `$env:ATB_ANDROID_MODE` / `$ATB_ANDROID_MODE` 读取 ↔ Task 6 `$env:ATB_WIZARD_MANAGED` 读取 — 一致。
- `setup_env(ctx, role_id)` 签名：Task 2 定义 ↔ Task 3 三处调用 `setup_env(ctx, role_id)` / `setup_env(ctx, self.role_id)` — 一致。
