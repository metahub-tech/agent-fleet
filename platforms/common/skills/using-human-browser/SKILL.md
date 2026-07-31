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
  - **Enable human_dom on this dedicated profile (DOM precision)**: a freshly-created dedicated profile has **no human_dom extension installed by default**, and the page localizer falls back to `vision_locate` until you install it. The extension is a per-profile copy; install it once via **chrome://extensions persistent Load-unpacked** (Chrome 137+ disabled the `--load-extension` command-line flag, so that's the only reliable path). A vision-agent can do this autonomously — see using-human-dom, section "为一个【新 profile】启用 human_dom" → "自助 Load-unpacked 装扩展（视觉 agent 流程）".
    - **★ Same `profile` string in three places (bridge routes by profile):** when using human_dom on this dedicated profile, `human_dom_locate/tap/fill` must take the **same `profile` string** you pass to `human_browser_open(profile=...)`, and the extension must be installed **into this same profile** (the bridge routes per profile — it no longer guesses the active tab). Omitting `profile` operates the **default everyday Chrome**, not this dedicated one. See using-human-dom for the per-profile install + routing rule.
- **resume**: when interrupted (e.g., you asked the user to log in) and resuming in a NEW run, call `human_browser_open(profile="<same pinned profile>")` — it reopens the SAME logged-in profile. Do NOT open a fresh browser or switch browser mode (loses the login).
- **R4 (agent↔human, only if you truly must switch)**: pass agent_browser and human_browser the **same `profile` value** → same on-disk `user-data-dir` → same login. Chrome locks a user-data-dir to one process → **quit the other engine first** (`browser_quit(profile=...)`) before opening the same profile in the other; login is preserved (it's on disk). For real accounts you normally never switch — stay in human_browser + human_dom throughout.

## Workflow (screenshot + OS input, NOT DOM)

1. `human_browser_open(url, profile=...)` — launches the real Chrome. **Does NOT grab foreground by default** (`activate=False`); pass `activate=True` only when you are about to operate in the browser, to bring that profile's Chrome to the front. To get DOM precision on a dedicated profile, install the human_dom extension into it once (Load-unpacked — see using-human-dom).
2. **Verify foreground before acting (check → pull only if wrong; per ACTION-GROUP, not per frame)** — OS input (`tap`/`type_text`/`press_key`/`paste_text`/`swipe`/`move_mouse`/`hover_preview`) lands on whatever window is currently in front; if that isn't your target browser you'll misclick or type into another app (data misdirection). Rule: check once at the start of an uninterrupted group of actions (e.g. `cmd+l` → type URL → enter); re-check after any wait / load / navigation / retry (the user may have switched away during those seconds):
   - `human_dom_focused(profile=...)` → `focused=true`: operate directly;
   - `focused=false` → `human_browser_open(profile=..., activate=True)` to pull it front → re-check → operate;
   - `focused=None` / can't tell (not connected / `chrome://` / non-Chrome) / **tool missing or call errors (older server not yet upgraded)** → fall back to `take_screenshot` and eyeball the foreground; **don't get stuck, don't retry**.
3. `take_screenshot` (core) — SEE the page. Screenshot pixels == `tap` pixels (logical/point space). Also the fallback foreground check when the out-of-band check returns no signal.
4. `tap(x, y)` / `type_text` / `press_key` (e.g. `cmd+l` → address bar, `enter`) — operate.
5. Re-`take_screenshot` after each action to confirm and locate the next target.

There is **no `browser_snapshot` / ref model here** — that is agent_browser. Web page elements are not in the UIA/AX tree, so `find_elements`/`tap_element` only see Chrome's own chrome (tabs, address bar), not page content. For page content: **`human_dom`** (read-only DOM locator → exact coordinates; see using-human-dom) or screenshot + coordinates.

To navigate by address bar without `human_browser_open`: `press_key("cmd+l")` (mac) / `press_key("ctrl+l")` (win) → `type_text("https://...")` → `press_key("enter")`.

## What to know

- **Real identity / profile**: this is the human's actual Chrome (real cookies, logins, extensions). Acting here acts as the person — only do so on the user's own device with their own/authorized accounts, for legitimate purposes.
- **Shared screen aware (do NOT assume an exclusive screen)**: human_browser drives the physical mouse/keyboard on a machine the user may be using at the same time. Do NOT routinely grab foreground; before each action-group verify the foreground is your target browser (Workflow step 2 — `human_dom_focused`, falling back to `take_screenshot`), and pull it front only if it isn't. Operating on the wrong window means typing into another app (worse than a focus-steal — it's data misdirection). To bring the browser front, prefer `human_browser_open(..., activate=True)` (targets the correct window by profile); `focus_window` is the fallback (when the target isn't Chrome).
- **Zero traces is real but not magic**: no CDP/webdriver to detect, and OS input is genuinely `isTrusted`. BUT behavioral signals (instant moves, timing) can still be sampled by aggressive bot-detection — human_browser is far stealthier than agent_browser, not an undetectable cloak. CAPTCHAs can still appear (humans get them too).
- **Headed only**: needs an active GUI/desktop session on the host. If Chrome isn't installed or no GUI session, `list_capabilities` shows human_browser as `unavailable` with the reason.
