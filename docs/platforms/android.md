# Android Device Setup Guide

This guide covers everything you need to get an Android phone or tablet visible to `adb` on your host machine, ready to be driven by the `android-device` MCP server.

There are three ways to connect; pick the one that matches your phone + workflow:

| Method | Best for | Trade-offs |
|---|---|---|
| [USB](#method-usb) | Daily driver — fastest, most reliable | Cable required |
| [Wireless](#method-wireless) | Android 11+ / SDK 30+ | Native pairing UI; per-network re-pair needed |
| [Hybrid](#method-hybrid) | Android 5–10 (incl. **HarmonyOS 4 phones that report Android 10**, e.g. Huawei P30 Pro) | Re-tether via USB after every phone reboot |

Whichever method you pick, you'll first need to enable [Developer Options](#step-1-enable-developer-options).

---

## Step 1 — Enable Developer Options

Developer Options is hidden by default on every Android. The unlock gesture varies by OEM. **Find the "Build number" (or 版本号) row in Settings and tap it 7 times**; the system will then unlock a "Developer options" submenu.

Exact path per OEM:

| OEM / ROM | Path |
|---|---|
| **Huawei / HarmonyOS / EMUI** | Settings → About phone → tap **"Build number" / "版本号"** 7× |
| **Xiaomi / MIUI / HyperOS** | Settings → My device → All specs → tap **"MIUI version"** 7× |
| **Samsung / One UI** | Settings → About phone → Software information → tap **"Build number"** 7× |
| **OPPO / realme / ColorOS** | Settings → About device → tap **"Version"** 7× |
| **vivo / OriginOS / Funtouch** | Settings → My device → tap **"Software version"** 7× |
| **Pixel / AOSP** | Settings → About phone → tap **"Build number"** 7× |
| **OnePlus / OxygenOS** | Settings → About device → Version → tap **"Build number"** 7× |
| **Other** | Look for the "Build number" / "版本号" field anywhere under About; tap 7× |

You'll see "You are now a developer!" toast. Developer options now appears either in Settings root or under Settings → System → Developer options.

---

## Step 2 — Enable USB Debugging

Inside **Developer Options**:

1. Toggle **USB debugging** ON
2. (Optional) **Stay awake** while charging — useful for long-running automation
3. (Optional, Pixel/AOSP) **Default USB configuration → File transfer** — avoids the per-cable prompt

OEM-specific quirks:

- **Huawei**: On Windows, you may need the HiSuite USB driver before `adb devices` recognises the phone. On macOS/Linux this works out-of-the-box.
- **Xiaomi/MIUI**: Sign in to your Mi Account before USB debugging is selectable. Also enable **"USB debugging (Security settings)"** (a second toggle inside the same submenu) — many on-device automation actions require it.
- **OPPO/Vivo**: USB debugging may auto-disable after rebooting or after a few hours of inactivity. Re-enable as needed.
- **Pixel / OnePlus**: No quirks. Default flow works.

---

## Step 3 — Pick a Connection Method

### Method: USB

The simplest. Plug the phone into the host with a working USB cable.

```bash
adb devices
```

First time: an "Allow USB debugging" dialog appears on the phone. **Check "Always allow from this computer"** and tap **Allow**. Then `adb devices` shows your phone as `device`.

```
List of devices attached
MQS0219A10009471       device usb:20-1 product:VOG-AL00 model:VOG_AL00 ...
```

If it shows `unauthorized` instead — the on-phone dialog was dismissed; unplug + replug + accept.

### Method: Wireless

**Requires Android 11+ (SDK 30+)** with native wireless debugging support. Watch out: some HarmonyOS 4 phones report `ro.build.version.release=10` even though they look like newer Android; for those, use [Hybrid](#method-hybrid).

On the phone:

1. Developer options → **Wireless debugging** ON
2. Tap **Pair device with pairing code**
3. The phone shows a 6-digit pairing code + an `IP:port` (the *pairing* port, e.g. `192.168.1.42:37123`)

On the host (your Mac / Linux box / Windows PC):

```bash
adb pair 192.168.1.42:37123
# (prompts you for the 6-digit code)
adb connect 192.168.1.42:5555
# (this port is shown on the Wireless debugging main screen, NOT the pairing port)
```

Pairing is permanent until you wipe the phone or remove the host from the paired-devices list. Connections survive phone reboots (you may need to re-run `adb connect <IP>:<port>` once after a reboot).

### Method: Hybrid

For phones that don't expose native wireless debugging but can still run `adb` over TCP. Used for **Android 5–10** and the **HarmonyOS 4 family that reports Android 10**.

```bash
# One-time, with USB cable plugged in:
adb tcpip 5555
adb connect <phone-IP>:5555
# Now you can unplug the cable.
```

Caveat: **`adb tcpip` mode is lost on every phone reboot.** When the phone restarts, plug USB back in and re-run `adb tcpip 5555` to re-arm wireless.

---

## Step 4 — Verify

Whichever method you used:

```bash
adb devices -l
```

You should see exactly one line per phone, with `state=device`. If you see `unauthorized`, accept the on-phone dialog. If you see `offline`, run `adb kill-server && adb start-server` and retry.

```bash
# Quick sanity:
adb shell getprop ro.product.model
adb shell wm size
```

These should return your phone's model and screen resolution. If they do, `android-device` MCP server is ready to drive it.

---

---

## 多设备模式

v0.7.0-alpha 起，单台主机可同时挂多台 Android 手机，通过同一个 MCP 入口控制。

### 使用场景

- **USB hub 接多机**：一台 Linux/macOS/Windows PC 同时接 2–4 台测试机
- **并行测试**：多个 Claude 会话同时操作不同手机，互不干扰
- **A/B 截图对比**：同一个 app 在两款手机上跑，Agent 直接对比截图
- **多端联调**：一台手机发消息，另一台手机收通知，验证端到端流程

### 别名配置文件

别名存储在 `~/.agent-fleet/android-aliases.json`，由安装向导自动推断并写入。格式示例：

```json
{
  "R5CW903LNJK": "samsung-galaxy-s23",
  "emulator-5554": "pixel-8-emulator",
  "192.168.1.42:5555": "huawei-p30"
}
```

推断规则（按优先级）：
1. `{brand}-{slug(model)}`（空格转 `-`，全小写），例如 `samsung-galaxy_s23` → `samsung-galaxy-s23`
2. 重名时按 serial 字典序追加 `-1` / `-2`（不影响 serial 本身）
3. 推断失败时 fallback 到 `phone-1` / `phone-2`

手动写入 `~/.agent-fleet/android-aliases.json` 也可；server 启动时读取，更改后需重启服务。

### wizard 多设备交互式 prompt

`agent-fleet setup` 安装时，如果检测到多台设备，向导会逐台询问别名（pre-fill 推断值，回车接受）。也可单独运行：

```bash
python3 platforms/android/scripts/setup_aliases.py
```

### MCP 协议层暴露

| 机制 | 说明 |
|---|---|
| `instructions=` | MCP initialize 握手时自动注入，Claude 无需调工具即可看到所有已连设备 |
| `androidfleet://devices` | MCP resource，随时可读，返回实时设备 JSON |
| `list_devices()` | 兜底工具，主动刷新（含 hot-plug 后新出现的设备） |

### `device` 参数解析顺序

每个工具调用的 `device` 参数按以下顺序解析：

1. **显式 device** — 调用时传入的 alias 或 serial
2. **会话 sticky 默认** — 之前调 `set_default_device()` 设置的值
3. **1 部时自动** — 当前恰好只有 1 台设备，自动选择
4. **MultipleDevicesError** — 以上均不满足时抛出，提示需要指定 device

### 并发场景示例

两个 Claude 会话同时操作不同手机，互不干扰：

```python
# 会话 A
acquire_android(device="samsung-galaxy-s23", holder_name="agent-A")
take_screenshot(device="samsung-galaxy-s23")
tap(x=540, y=1170, device="samsung-galaxy-s23")
release_android(device="samsung-galaxy-s23", holder_name="agent-A")

# 会话 B（同时进行）
acquire_android(device="pixel-8-emulator", holder_name="agent-B")
take_screenshot(device="pixel-8-emulator")
release_android(device="pixel-8-emulator", holder_name="agent-B")
```

### 注意事项

> **多设备模式仍使用一个 MCP 入口**。`~/.claude.json` 里仍然只写一条 `android-device` 配置；server 自己按 `device` 参数路由到对应手机。不需要为每台手机注册独立 MCP server。

- **单机用户无需修改任何配置**：未传 `device` 且只插 1 部手机时自动路由，行为与 v0.6.x 完全兼容。
- **hot-plug 通知未实现**：新插入/拔出的设备不会主动推送，调 `list_devices()` 主动刷新。
- **server 启动时查询 adb** 以生成 `instructions=`；若 adb hang 可能导致最多 10s 的冷启动延迟。

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `no permissions` on Linux | Add yourself to the `plugdev` group, or write a udev rule for your phone's USB vendor ID. |
| `device offline` after reboot (USB) | Unplug + replug, accept the "Allow USB debugging" prompt. |
| `device offline` after reboot (Wireless) | Wireless: re-run `adb connect <IP>:<port>`. Hybrid: re-tether via USB, `adb tcpip 5555` again. |
| Phone disappears mid-session | USB cable / port flaky, or phone's USB-debugging auto-disabled (Xiaomi/OPPO security). Re-enable in Developer options. |
| `adb` not found on Mac | `brew install --cask android-platform-tools` |
| `adb` not found on Windows | Install via the agent-fleet setup script, or download Google's official platform-tools zip. |
| Auth prompt never appears | Some OEM ROMs need you to flip "USB debugging (Security settings)" inside Developer options. |

For wizard-driven setup, run `agent-fleet setup` and pick the **android-device** role — it'll guide you through Developer options + drive `adb` for you.

---

## Server 管理：启动 / 停止 / 重启 / 看 log

`agent-fleet setup` 已经为你注册了 OS-原生服务（Task Scheduler / launchd / systemd），登录/开机时自动起。日常运维：

### Windows host（Task Scheduler，task 名 `MCP-AndroidDevice`）

```powershell
# 看状态
Get-ScheduledTaskInfo -TaskName MCP-AndroidDevice
Get-NetTCPConnection -LocalPort 8768 -State Listen

# 重启（停 + 起，<2s）
Stop-ScheduledTask  -TaskName MCP-AndroidDevice
Start-ScheduledTask -TaskName MCP-AndroidDevice

# 看 log
Get-Content "$env:USERPROFILE\agent-fleet\platforms\android\logs\android-device.log" -Tail 50
```

> ⚠️ **不要用 `Start-Process -RedirectStandardOutput`** 手动起 server！该 cmdlet 让父 PowerShell 持有 child process 的 stdout/stderr handle，server 不退出 → 父进程不退出 → 看似 hang。Task Scheduler 内部用 `cmd /c start /b` 真正 detach，不会有这个问题。如果一定要手动起（无 Task Scheduler），用 `Start-Process ... -WindowStyle Hidden`（不带 -Redirect*）让默认 stdio 走系统 NUL，或者把 server 包到 `.bat` 里再 `cmd /c start /b cmd /c your.bat`。

### macOS host（launchd，label `cc.metahub.android-device`）

```bash
# 看状态
launchctl list | grep android-device
lsof -iTCP:8768 -sTCP:LISTEN

# 重启（推荐 kickstart -k，比 unload/load 安全）
launchctl kickstart -k "gui/$(id -u)/cc.metahub.android-device"

# 看 log
tail -f ~/agent-fleet/platforms/android/logs/android-device.log
```

> ⚠️ macOS `launchctl bootout` 单独写 `gui/$(id -u)` 会卸载该用户域**所有** LaunchAgent → 立刻注销 + 黑屏。必须带 plist 路径，且整条命令单行。详见 [`docs/platforms/macos.md`](macos.md)。

### Linux host（systemd user service，unit `agent-fleet-android.service`）

```bash
systemctl --user status agent-fleet-android
systemctl --user restart agent-fleet-android
journalctl --user -u agent-fleet-android -f
```

### 三平台通用：log 文件为空但 server 在跑

Server 启动时 fastmcp 自带 banner 会抢占 stdout 句柄，若 launcher 用 `>` overwrite 重定向 log 可能写不进去（log 文件 0 bytes）。`>>` append 模式或 `Out-File -Append` 可绕过。三个 launcher 脚本都已用 append 模式，但手动重启时如果你自己写 redirect，注意这点。
