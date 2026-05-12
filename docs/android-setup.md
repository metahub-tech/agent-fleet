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
