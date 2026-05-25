---
name: using-human-browser
description: Use when you must act AS THE HUMAN in a real browser through an agent-fleet device server's human_browser capability -- operating real logged-in accounts, changing settings/config as the person, or any task where the website must see a genuine human (zero automation traces). Covers launching the host's real Chrome and operating it via screenshot + OS-level clicks. For testing/scraping/browsing-to-learn use agent_browser instead.
---

# Using human_browser

`human_browser` is a **self-built** capability: it launches the host's **real daily Google Chrome** with **no debug port and no automation flags**, so there are **zero automation traces** — `navigator.webdriver` stays false, there is no CDP interface to probe, and input is genuine OS-level input. You then operate the page the way a person does: **look at a screenshot, click coordinates, type**.

This is the moat: it reuses the device's OS-level control (core tools), not a browser-automation framework.

## human_browser vs agent_browser (routing)

- **human_browser** (this skill): real Chrome, real logged-in identity, zero traces, but **screenshot + coordinates only** (web content is NOT in the OS accessibility tree). Slower, less precise, higher token cost. Use when **acting as the human on real accounts / identity**: logging in, changing account settings, anything where the site must see a real person.
- **agent_browser**: Playwright-driven, DOM snapshot+ref, fast and precise, but **has automation traces** and uses an **isolated profile** (not the human's identity). Use for testing, scraping, browsing to learn.

Rule: touching a **real personal account / identity** → human_browser. Otherwise → agent_browser.

## Workflow (screenshot + OS input, NOT DOM)

1. `human_browser_open(url)` — launches/focuses the real Chrome and (optionally) navigates. Returns immediately.
2. `take_screenshot` (core tool) — SEE the page. Screenshot pixels == `tap` pixels (logical/point space).
3. `tap(x, y)` (core) — click where you see the target. `type_text` — type. `press_key` — keys (e.g. `cmd+l` to focus the address bar, `enter` to go).
4. Re-`take_screenshot` after each action to confirm and locate the next target.

There is **no `browser_snapshot` / ref model here** — that is agent_browser. Web page elements are not reliably in the UIA/AX tree, so `find_elements`/`tap_element` only see Chrome's own chrome (tabs, address bar), not page content. For page content: screenshot + coordinates.

To navigate by address bar without `human_browser_open`: `press_key("cmd+l")` (mac) / `press_key("ctrl+l")` (win) → `type_text("https://...")` → `press_key("enter")`.

## What to know

- **Real identity / profile**: this is the human's actual Chrome (real cookies, logins, extensions). Acting here acts as the person — only do so on the user's own device with their own/authorized accounts, for legitimate purposes.
- **Exclusive screen + input**: human_browser drives the physical mouse/keyboard. While you operate it, don't run other OS-input operations on this host concurrently — they fight over the cursor.
- **Zero traces is real but not magic**: no CDP/webdriver to detect, and OS input is genuinely `isTrusted`. BUT behavioral signals (instant moves, timing) can still be sampled by aggressive bot-detection — human_browser is far stealthier than agent_browser, not an undetectable cloak. CAPTCHAs can still appear (humans get them too).
- **Headed only**: needs an active GUI/desktop session on the host. If Chrome isn't installed or no GUI session, `list_capabilities` shows human_browser as `unavailable` with the reason.
