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

1. `human_browser_open(url, profile=...)` — launches the real Chrome. **默认不抢前台**（`activate=False`）；只有即将在浏览器里动手时才传 `activate=True` 把该 profile 的 Chrome 拉前台。To get DOM precision on a dedicated profile, install the human_dom extension into it once (Load-unpacked — see using-human-dom).
2. **动手前先查前台（查→不对才拉；按【组】非逐帧）** — OS 输入（`tap`/`type_text`/`press_key`/`paste_text`/`swipe`/`move_mouse`/`hover_preview`）打在**当时的前台窗口**，前台不是目标浏览器就会误点/往别的应用敲字（数据错发）。规则：**一组无中断的连续动作（如 `cmd+l`→输网址→回车）组首查一次；任何等待/加载/跳页/重试之后必须重查**（用户很可能就在你等的那几秒切走了应用）：
   - `human_dom_focused(profile=...)` → `focused=true` 直接操作；
   - `focused=false` → `human_browser_open(profile=..., activate=True)` 拉回 → 复查 → 操作；
   - `focused=None` / 拿不到（未连/`chrome://`/非 Chrome）/ **该工具不存在或调用报错（旧 server 未升级）** → 回落 `take_screenshot` 目测前台，**别卡住、别重试**。
3. `take_screenshot` (core) — SEE the page. Screenshot pixels == `tap` pixels (logical/point space). 也是前台检查拿不到信号时的兜底判断手段。
4. `tap(x, y)` / `type_text` / `press_key` (e.g. `cmd+l` → address bar, `enter`) — operate.
5. Re-`take_screenshot` after each action to confirm and locate the next target.

There is **no `browser_snapshot` / ref model here** — that is agent_browser. Web page elements are not in the UIA/AX tree, so `find_elements`/`tap_element` only see Chrome's own chrome (tabs, address bar), not page content. For page content: **`human_dom`** (read-only DOM locator → exact coordinates; see using-human-dom) or screenshot + coordinates.

To navigate by address bar without `human_browser_open`: `press_key("cmd+l")` (mac) / `press_key("ctrl+l")` (win) → `type_text("https://...")` → `press_key("enter")`.

## What to know

- **Real identity / profile**: this is the human's actual Chrome (real cookies, logins, extensions). Acting here acts as the person — only do so on the user's own device with their own/authorized accounts, for legitimate purposes.
- **Shared screen aware（别假设独占屏幕）**: human_browser 驱动物理鼠标/键盘，而这台机器**用户可能正在同时用**。**不要例行抢前台**；每组动作动手前按 Workflow step 2 先查前台是不是你的目标浏览器（`human_dom_focused`，拿不到回落 `take_screenshot`），不对才 `activate=True` 拉回。走错窗口＝往别的应用敲字（比抢焦点更糟，是数据错发）。拉前台首选 `human_browser_open(..., activate=True)`（按 profile 定位到正确那个窗口），`focus_window` 退兜底（目标非 Chrome 时）。
- **Zero traces is real but not magic**: no CDP/webdriver to detect, and OS input is genuinely `isTrusted`. BUT behavioral signals (instant moves, timing) can still be sampled by aggressive bot-detection — human_browser is far stealthier than agent_browser, not an undetectable cloak. CAPTCHAs can still appear (humans get them too).
- **Headed only**: needs an active GUI/desktop session on the host. If Chrome isn't installed or no GUI session, `list_capabilities` shows human_browser as `unavailable` with the reason.
