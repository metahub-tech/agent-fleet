---
name: using-fleet-browser
description: Use when driving a web browser through an agent-fleet device server's agent_browser capability (grafted Playwright MCP) -- navigating pages, reading content via accessibility snapshots, clicking/typing in web apps, end-to-end web testing, or browsing to gather information. Covers the snapshot+ref workflow and when to use agent_browser vs human_browser.
---

# Using agent_browser

`agent_browser` is a **proxied** capability: an agent-fleet device server (e.g. `mac-device`) grafts **Playwright MCP** and drives a **real, headed Chrome** on that host. Its `browser_*` tools are re-exposed under their own names. Discover it via `list_capabilities` (origin `proxied`, status `enabled`); load the tools you need by name.

`agent-fleet` never runs headless — the browser is a real window on the host's GUI session, suitable for end-to-end testing.

## agent_browser vs human_browser (routing)

- **agent_browser** (this skill): DOM/semantic control via Playwright. Fast, precise, token-efficient. **Has automation traces** (CDP / `navigator.webdriver`). Use for: end-to-end web testing, scraping/reading, browsing to learn, automation where traces are fine.
- **human_browser** (separate capability, when available): drives the host's real daily Chrome via OS-level input + screenshots, **zero automation traces**, real logged-in identity. Use when **acting as the human** on real accounts (login, account/config changes).

Rule: touching a **real personal account / identity** → human_browser. Otherwise → agent_browser.

## The snapshot+ref workflow (do NOT guess coordinates)

Playwright's model is **accessibility snapshot + element refs**, not pixels:

1. `browser_navigate(url)` — open the page.
2. `browser_snapshot()` — returns the page's a11y tree as YAML with a `ref` on each element, e.g. `- heading "Example Domain" [level=1] [ref=e3]`. This is the semantic, token-cheap view — read it instead of screenshotting.
3. Act by **ref**: `browser_click(ref="e3", element="Example heading")`, `browser_type(ref="e5", text="...", element="search box")`.
4. **After the DOM changes** (navigation, click that re-renders), the old refs are stale → call `browser_snapshot()` again to get fresh refs.

`browser_take_screenshot` exists for visual confirmation, but prefer `browser_snapshot` for locating/reading — it is semantic and cheaper.

## Common tools

| Task | Tool |
|---|---|
| Open / go back | `browser_navigate`, `browser_navigate_back` |
| Read page (a11y tree + refs) | `browser_snapshot` |
| Click / type / hover | `browser_click`, `browser_type`, `browser_hover` |
| Form fill | `browser_fill_form`, `browser_select_option` |
| Keys / wait | `browser_press_key`, `browser_wait_for` |
| Tabs | `browser_tabs` |
| Read network / console | `browser_network_requests`, `browser_console_messages` |
| Run JS (⚠ arbitrary code) | `browser_evaluate`, `browser_run_code_unsafe` |
| Visual check | `browser_take_screenshot` |
| Close (⚠ kills the SHARED Chrome) | `browser_close` |

## What to know

- **Shared singleton**: the host runs ONE Chrome (isolated fleet profile) for the server's lifetime. Multiple agents share it — don't assume a private session; navigate to set up your own state. Chrome launches lazily on the first `browser_*` call (first call is slower; subsequent calls are fast).
- **Isolated profile** (`~/.fleet/agent-browser-profile`) — NOT the human's real Chrome/identity. To act as the human, use human_browser.
- **State persists across calls** within the session (navigate → snapshot reflects the page), so build flows step by step.
- **`browser_close` kills the shared Chrome** — it does NOT just end "your" session; every other agent on this host loses the browser and their next `browser_*` call pays a relaunch. Don't call it unless you mean to tear down the shared browser.
- **`browser_evaluate` / `browser_run_code_unsafe` execute arbitrary JavaScript** in the page. Never pass untrusted page content into them; prefer the typed `browser_*` tools for normal interaction.
- If `browser_*` tools are missing, the host may not have node / `@playwright/mcp` installed → `list_capabilities` shows agent_browser as `unavailable` with the reason.
