---
name: using-fleet-browser
description: Use when driving a web browser through an agent-fleet device server's agent_browser capability (grafted Playwright MCP) -- navigating pages, reading content via accessibility snapshots, clicking/typing in web apps, end-to-end web testing, or browsing to gather information. Covers the multi-profile lease model (profile/holder params, bind/release/quit/status), the snapshot+ref workflow, and when to use agent_browser vs human_browser.
---

# Using agent_browser

`agent_browser` is a **proxied** capability: an agent-fleet device server (e.g. `mac-device`) grafts **Playwright MCP** and drives **real, headed Chrome** on that host. Discover it via `list_capabilities` (origin `proxied`, status `enabled`); load the tools you need by name.

`agent-fleet` never runs headless — each browser is a real window on the host's GUI session, suitable for end-to-end testing. (It drives via CDP, so it does NOT need the screen to be awake.)

## agent_browser vs human_browser (routing)

- **agent_browser** (this skill): DOM/semantic control via Playwright. Fast, precise, token-efficient. **Has automation traces** (CDP / `navigator.webdriver`). Use for: end-to-end web testing, scraping/reading, browsing to learn, automation where traces are fine.
- **human_browser** (separate capability): drives the host's real daily Chrome via OS-level input + screenshots, **zero automation traces**, real logged-in identity. Use when **acting as the human** on real accounts (login, account/config changes).

Rule: touching a **real personal account / identity** → human_browser. Otherwise → agent_browser.

## Multi-profile + lease model (IMPORTANT — read before driving)

agent_browser supports **multiple profiles running truly in parallel** — each `profile` is a separate Chrome (own `user-data-dir`, own state/cookies/tabs). **Every `browser_*` tool takes two extra params**:

- `profile` (default `"isolated"`): which browser. Values:
  - `"isolated"` → the default isolated fleet profile (`~/.fleet/agent-browser-profile`); NOT a human identity.
  - a directory path (e.g. `"~/.fleet/work"`) → a dedicated profile dir.
  - `"dir@ProfileName"` → a `user-data-dir` + Chrome `--profile-directory` (a named sub-profile).
- `holder` (default `"agent"`): who holds the lease. Multiple agents on one host should pass distinct holders so the lease can tell them apart.

A profile is an **OS-exclusive resource** (one Chrome per `user-data-dir`), so the server uses an advisory **lease**:

- **auto-bind**: the first `browser_*` call on a free profile automatically starts its Chrome and binds it to your `holder`. You don't have to call `browser_bind` first — it's there for explicit pre-binding / checking.
- **busy**: if the profile is already held by **another holder**, your call returns `{"bound": false, "current_holder": ..., "auto_release_in_seconds": N}` instead of acting. Retry after it's released or idle-expires (don't spin tightly).
- **idle timeout (10 min)**: an untouched lease auto-closes its Chrome and frees the profile. Each `browser_*` call refreshes the timer.

### Lease tools

| Tool | What it does |
|---|---|
| `browser_bind(profile, holder)` | Explicitly bind/start a profile's browser (or reuse if yours / re-attach a kept one). Returns busy if another holder has it. |
| `browser_release(profile, holder)` | Detach **but keep the Chrome process warm** — a later bind on the same profile re-attaches instantly (no relaunch). Idle timeout still closes it eventually. |
| `browser_quit(profile, holder)` | Close that profile's Chrome process + drop the lease. (A detached/ownerless profile may be quit by anyone.) |
| `browser_status()` | List all leases (profile / engine / holder / state / idle_seconds / auto_release_in_seconds) — across agent AND human browsers. |

`browser_bind` defaults `profile` to `isolated`; `browser_release` / `browser_quit` require an explicit `profile`. The busy refusal field is `auto_release_in_seconds`.

Typical flow: just call `browser_navigate(profile="...", url=...)` (auto-binds) → work → `browser_release` if you might come back soon (warm reuse), or `browser_quit` when done. Use `browser_status` to see what's live.

## The snapshot+ref workflow (do NOT guess coordinates)

Playwright's model is **accessibility snapshot + element refs**, not pixels. Pass your `profile` to every call:

1. `browser_navigate(profile=P, url=...)` — open the page (auto-binds P on first use).
2. `browser_snapshot(profile=P)` — returns the page's a11y tree as YAML with a `ref` per element, e.g. `- heading "Example Domain" [level=1] [ref=e3]`. Read this instead of screenshotting — semantic and token-cheap.
3. Act by **ref**: `browser_click(profile=P, ref="e3", element="...")`, `browser_type(profile=P, ref="e5", text="...", element="...")`.
4. **After the DOM changes**, old refs go stale → `browser_snapshot(profile=P)` again for fresh refs.

## Common tools (all take `profile` + `holder`)

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
| Close current **page/tab** | `browser_close` |
| Quit the whole **profile browser** | `browser_quit` (lease tool) |

## What to know

- **`browser_close` vs `browser_quit`**: `browser_close` (native Playwright) closes the current **page/tab** of that profile; `browser_quit` (lease tool) tears down the whole **Chrome process** for that profile and frees the lease. To end your session and release the browser, use `browser_quit` (or `browser_release` to keep it warm).
- **Per-profile isolation**: different `profile` values are fully independent browsers — navigating one never affects another. Same profile + same holder reuses one Chrome; state persists across calls, so build flows step by step. First call on a profile is slower (Chrome launches); later calls are fast.
- **Isolated ≠ human**: the default `isolated` profile is NOT the human's real Chrome/identity. To act as the human, use human_browser.
- **`browser_evaluate` / `browser_run_code_unsafe` execute arbitrary JavaScript** in the page. Never pass untrusted page content into them; prefer the typed `browser_*` tools.
- If `browser_*` tools are missing, the host may lack node / `@playwright/mcp` → `list_capabilities` shows agent_browser as `unavailable` with the reason.
