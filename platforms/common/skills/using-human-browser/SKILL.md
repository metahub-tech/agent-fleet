---
name: using-human-browser
description: Use when you must act AS THE HUMAN in a real browser through an agent-fleet device server's human_browser capability -- operating real logged-in accounts, changing settings/config as the person, or any task where the website must see a genuine human (zero automation traces). Covers launching the host's real Chrome and operating it via screenshot + OS-level clicks. For testing/scraping/browsing-to-learn use agent_browser instead.
---

# Using human_browser

`human_browser` is a **self-built** capability: it launches the host's **real daily Google Chrome** with **no debug port and no automation flags**, so there are **zero automation traces** — `navigator.webdriver` stays false, there is no CDP interface to probe, and input is genuine OS-level input. You then operate the page the way a person does: **look at a screenshot, click coordinates, type**.

This is the moat: it reuses the device's OS-level control (core tools), not a browser-automation framework.

## human_browser vs agent_browser (routing)

- **human_browser** (this skill): real Chrome, **real logged-in identity**, zero automation traces. Page localization: **`human_dom`** (read-only DOM locator companion — exact coordinates, see using-human-dom) or screenshot+coordinates. Use when **acting as the human on real accounts / identity**.
- **agent_browser**: Playwright-driven, DOM snapshot+ref, fast — but **has automation traces** and uses an **isolated profile** (NOT the human's identity, NOT the user's login). Use for testing / scraping / browsing-to-learn on throwaway isolated profiles.

**★ Rule for real accounts (read this — it's the #1 footgun):** a **real account / identity** → **human_browser + human_dom, from the FIRST navigation (including the login scan) through every op. NEVER touch agent_browser for that account** — not even to "just browse and check" first. Why: agent_browser logs into its **isolated profile** (`~/.fleet/agent-browser-profile`), invisible to human_browser; if you scan/login there, your later human_browser runs see a logged-OUT browser → you re-login forever (this was a real bug: a publisher re-scanned every hour for 12h). human_dom now gives human_browser DOM-level precision, so there is **no reason** to use agent_browser on a real account.

## 登录态跨 run 持久 + resume（recurring operator 必读）

A recurring operator (an agent driving a real account every run / cron tick) must reuse ONE login across runs — the user scans **once**, not every run:

- **Pin a dedicated persistent profile**: `human_browser_open(url, profile="~/.fleet/<account-id>")` (a path, or `"dir@ProfileName"`). Launches real Chrome on a **dedicated persistent `--user-data-dir`** → login persists on disk across runs AND stays isolated from the user's personal daily browsing. **Use the SAME `profile` value every run** → first run the user scans QR into it, every later run reuses it (no re-login).
  - `profile` empty (default) = the user's **daily default Chrome** (also persistent on disk, but mixed with their personal browsing). Fine for one-off interactive acts; for an unattended recurring operator, prefer a pinned dedicated `profile`.
  - **Enable human_dom on this dedicated profile (DOM precision)**: a freshly-created dedicated profile has **no human_dom extension installed by default**. To get DOM-level locating on it, pass `with_human_dom=True` when opening: `human_browser_open(url, profile="~/.fleet/<account-id>", with_human_dom=True)` → on launch it `--load-extension`s the human_dom extension into this profile, **GUI-free**. Without it, this profile can't use human_dom (fall back to vision_locate). Takes effect only on a cold launch, shows a "developer-mode extension" banner, and still needs the host-level `~/.fleet/human-dom-ready` marker — see using-human-dom ("per-profile 启用", "两层启用模型").
- **resume**: when interrupted (e.g., you asked the user to log in) and resuming in a NEW run, call `human_browser_open(profile="<same pinned profile>")` — it reopens the SAME logged-in profile. Do NOT open a fresh browser or switch browser mode (loses the login).
- **R4 (agent↔human, only if you truly must switch)**: pass agent_browser and human_browser the **same `profile` value** → same on-disk `user-data-dir` → same login. Chrome locks a user-data-dir to one process → **quit the other engine first** (`browser_quit(profile=...)`) before opening the same profile in the other; login is preserved (it's on disk). For real accounts you normally never switch — stay in human_browser + human_dom throughout.

## Workflow (screenshot + OS input, NOT DOM)

1. `human_browser_open(url, profile=..., with_human_dom=...)` — launches/focuses the real Chrome (optional `profile` = dedicated persistent profile for a recurring operator, see above; optional `with_human_dom=True` loads the human_dom extension into a NEW dedicated profile so you get DOM precision on it — see using-human-dom) and (optionally) navigates. Returns immediately.
2. `take_screenshot` (core tool) — SEE the page. Screenshot pixels == `tap` pixels (logical/point space).
3. `tap(x, y)` (core) — click where you see the target. `type_text` — type. `press_key` — keys (e.g. `cmd+l` to focus the address bar, `enter` to go).
4. Re-`take_screenshot` after each action to confirm and locate the next target.

There is **no `browser_snapshot` / ref model here** — that is agent_browser. Web page elements are not in the UIA/AX tree, so `find_elements`/`tap_element` only see Chrome's own chrome (tabs, address bar), not page content. For page content: **`human_dom`** (read-only DOM locator → exact coordinates; see using-human-dom) or screenshot + coordinates.

To navigate by address bar without `human_browser_open`: `press_key("cmd+l")` (mac) / `press_key("ctrl+l")` (win) → `type_text("https://...")` → `press_key("enter")`.

## What to know

- **Real identity / profile**: this is the human's actual Chrome (real cookies, logins, extensions). Acting here acts as the person — only do so on the user's own device with their own/authorized accounts, for legitimate purposes.
- **Exclusive screen + input**: human_browser drives the physical mouse/keyboard. While you operate it, don't run other OS-input operations on this host concurrently — they fight over the cursor.
- **Zero traces is real but not magic**: no CDP/webdriver to detect, and OS input is genuinely `isTrusted`. BUT behavioral signals (instant moves, timing) can still be sampled by aggressive bot-detection — human_browser is far stealthier than agent_browser, not an undetectable cloak. CAPTCHAs can still appear (humans get them too).
- **Headed only**: needs an active GUI/desktop session on the host. If Chrome isn't installed or no GUI session, `list_capabilities` shows human_browser as `unavailable` with the reason.
