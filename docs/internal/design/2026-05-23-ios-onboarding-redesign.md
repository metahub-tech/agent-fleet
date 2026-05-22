# iOS Onboarding Redesign — guided, idempotent, version-aware

**Date:** 2026-05-23
**Status:** approved (design), implementing
**Supersedes parts of:** `2026-05-20-ios-onboarding-optimization.md` (the per-device prep UX)

## Problem

The current per-device onboarding (`platforms/ios/scripts/ios-device-prep.sh`, invoked by `setup-ios.sh` step 6) was written for an iOS-developer audience and breaks for non-specialists. Real failures hit during a live MacBook Pro + iPhone 7 (iOS 15.8) onboarding:

1. **iOS-version bug (blocker):** it unconditionally runs `pymobiledevice3 amfi developer-mode-status / enable-developer-mode`. **iOS 15 has no Developer Mode** (that is iOS 16+). On iOS 15 the query returns nothing → it reports "OFF" → tells the user to enable a switch that does not exist → `exit 2` (dead end).
2. **Commands don't run as printed:** it prints `pymobiledevice3 …` and `xcodebuild …`, but `pymobiledevice3` is in the server venv (not on `PATH`) and the build line is raw — the user gets `command not found`.
3. **Wrong ordering:** "trust the developer cert" is listed before the WDA build, but the cert only appears **after** the first build installs the app — so the user looks for it and it is not there.
4. **No host-prereq checks:** never verifies full Xcode is installed (vs Command Line Tools) or that an Apple ID / signing identity exists. Both are hard requirements for the WDA build; their absence surfaces as cryptic failures later.
5. **Too dev-oriented:** the WDA step is a raw `xcodebuild` invocation; a programmer who has never done iOS is left guessing where the UDID comes from, what bundle id to use, etc.

## Goal

Rewrite `ios-device-prep.sh` into a single **interactive, idempotent, version-aware guided orchestrator**: automate everything that can be automated, and for the steps only the user can do (Apple ID + 2FA, on-device taps), pause with the exact Settings menu path, `open` the relevant screen where possible, wait for the user, then re-verify and continue. Re-running resumes from wherever it left off.

`setup-ios.sh` step 6 calls it; `build-wda.sh` stays the low-level build primitive it invokes.

## Flow

**Phase 0 — host prerequisites (auto-check, guide + exit if missing)**
1. **Full Xcode:** `xcode-select -p` resolves to an `Xcode.app` (not CLT) and `xcodebuild -version` works. If missing → `open "macappstore://apps.apple.com/app/xcode/id497799835"`, print the `sudo xcode-select -s …` + `sudo xcodebuild -license accept` follow-ups, and exit asking the user to re-run after install. Warn (don't block) if the Xcode major version is a poor match for the device's iOS (e.g. Xcode 26 cannot test iOS 15).
2. **Apple ID / signing identity:** `security find-identity -v -p codesigning | grep "Apple Development"`. If none → guide "Xcode → Settings (⌘,) → Accounts → add Apple ID (free is fine); enter the 2FA code on your phone", `open -a Xcode`, wait for Enter, re-check. Capture the 10-char Team ID for the build.

**Phase 1 — device detection (auto)**
3. **Pairing:** `<venv>/bin/pymobiledevice3 usbmux list`. If the target device is absent → guide "plug in via USB, tap Trust This Computer (+ passcode)", wait, re-check. **Auto-capture UDID, ProductVersion (iOS version), ProductType** (no manual UDID hunting).
4. **iOS-version branch:** parse ProductVersion major. `< 16` → skip Developer Mode entirely (print "iOS 15: no Developer Mode, skipping"). `>= 16` → run the Developer Mode sub-flow.

**Phase 2 — device settings (guided, version-aware)**
5. **Developer Mode** (iOS ≥ 16 only): query; if off, `amfi reveal/enable-developer-mode`, guide the reboot + on-device "Turn On" + passcode, wait, re-verify.
6. **Enable UI Automation:** Settings → Developer → Enable UI Automation → ON → **reboot** (without the reboot WDA times out "enabling automation mode"). Guide menu path, wait for confirm.
7. **Auto-Lock = Never** and **Screen Time install limit off:** guide menu paths, wait for confirm.

**Phase 3 — WDA build (auto + minimal prompts)**
8. **Bundle id:** prompt (default `com.<shortuser>.WebDriverAgentRunner`). On a GUI Terminal with the Apple ID added, `build-wda.sh`'s `xcodebuild -allowProvisioningUpdates` can mint the free-account profile directly (no separate Xcode-GUI mint needed — that constraint only bit the launchd context).
9. **Build:** assemble and run `build-wda.sh <auto-UDID> <bundle>` (the attached `xcodebuild test`, ~5–10 min, which also keeps WDA alive).
10. **Trust cert (now, after install):** once the first build has installed the runner, guide Settings → General → VPN & Device Management → <your Apple ID> → Trust; wait; the build/run then proceeds.
11. **Verify:** `pymobiledevice3 usbmux forward <p> 8100` + `curl /status` → confirm WDA reachable.

**Phase 4 — done:** print the Tailscale `ios-device` URL + "device ready; re-run list_devices()".

## Principles
- **Idempotent:** every step first checks "already satisfied?" and skips if so; safe to re-run to resume from any breakpoint.
- **Auto-first, guide-on-block:** do it automatically when possible; otherwise exact menu path + `open` the screen + wait for Enter + re-verify. No raw dev jargon.
- **Real commands:** always use the venv `pymobiledevice3` and inject the real UDID; never print a bare command the user must fix.
- **Version-aware:** the iOS-version branch is the spine (fixes the iPhone 7 dead-end).

## Files
- **Rewrite** `platforms/ios/scripts/ios-device-prep.sh` (the orchestrator; auto-detects the UDID when one device is attached, accepts an explicit UDID arg too).
- **Adjust** `platforms/ios/scripts/setup-ios.sh` step 6 to call the rewritten script (it already does; ensure it passes through interactively / doesn't suppress prompts).
- `build-wda.sh` unchanged (invoked as the build primitive).

## Out of scope
- WDA **persistence** on iOS 15 (survive reboot without an attached `xcodebuild test`). The iOS 17+ `install-wda-daemon.sh` (tunnel + go-ios) does not apply to iOS 15; a iOS-15 keep-alive is a separate follow-up. For now the attached build keeps WDA alive.
- Moving onboarding into the Python wizard (kept in bash, consistent with the existing scripts).
- Paid Apple Developer / ASC-API-key headless signing (already documented elsewhere).

## Verification
Run the rewritten script on test-macpro-12 against the real iPhone 7 (iOS 15.8): confirm Xcode/Apple-ID checks, the iOS-15 Developer-Mode skip, auto UDID capture, assembled commands, the guided pauses + re-checks, and (with the user completing Apple ID + on-device taps) a successful WDA build + reachable `/status`.
