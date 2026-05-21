# Extension Foundation — P3 CORE (tool-name alignment to canonical) Plan

> **For agentic workers:** Mixed: server/doc edits + Linux AST/conformance/no-legacy verification; **behavior of changed tools is validated on the real machines** (test-win11 `win-device`, macmini `mac-device`, android-device, ios-device). superpowers:subagent-driven-development for the code tasks. Steps use `- [ ]`.

**Goal (CORE batch):** Make every platform expose the canonical CORE tool names directly, delete the `[tools.aliases]` maps, and add a `test_no_legacy_naming` tool guard — **breaking** (agents must reconnect; SKILL.md is framework-cached → reopen the agent). OPTIONAL renames (`run_shell`/`launch_app`) are a separate later batch.

**Architecture / rename strategy (per user decision "真对齐：改行为"):**
- **Pure renames** (old name has no independent value → renamed, old gone): `acquire_<p>`→`acquire`, `release_<p>`→`release`, `get_<p>_status`→`get_status` (all 4); android `dump_ui_hierarchy`→`dump_ui` + `kill_app`→`terminate_app`; ios `acquire/release/status` + `press_button`→`press_key` (param `button`→`key`, docstring notes iOS physical-button subset) + `dump_ui_hierarchy`→`dump_ui` (add optional `max_depth`).
- **win/mac leaky CORE tools → ADD the canonical tool, KEEP the richer one as a PLATFORM-EXTENSION** (no capability lost):
  - ADD `dump_ui(max_depth=None)` that dumps the **foreground window** (win) / **frontmost app** (mac) UI tree; KEEP `inspect_window(title_substring,…)` (win) / `list_ui_elements(app,…)` (mac) as extensions (and have the new `dump_ui` reuse their internals with a foreground default).
  - ADD `terminate_app(target)` that terminates by **app identifier** (process name / path); KEEP `kill_process(pid)` as an extension.
- **Delete all `[tools.aliases]`** — conformance then passes via direct canonical names (AST), Linux-verifiable.
- **`click`/`kill_process`/`inspect_window`/`list_ui_elements` stay** (extensions / EXTENSION names) → NOT added to the legacy guard. (`click`→`tap` IS a rename though — see below.)

> **`tap`:** win/mac alias `tap←click`. Decision: **rename `click`→`tap`** (canonical), keeping its extra optional `button`/`clicks` params (superset of `tap(x,y)` — arity-OK). `click` gone. (If you'd rather keep `click` as an extension alias too, that's an OPTIONAL-batch call — for CORE, rename.)

**Convergence table (CORE), current → canonical:**
| platform | pure renames | add-canonical (keep old as ext) |
|---|---|---|
| win | click→tap, acquire_winpc→acquire, release_winpc→release, get_winpc_status→get_status | +dump_ui (keep inspect_window), +terminate_app (keep kill_process) |
| mac | click→tap, acquire_mac→acquire, release_mac→release, get_mac_status→get_status | +dump_ui (keep list_ui_elements), +terminate_app (keep kill_process) |
| android | acquire_android→acquire, release_android→release, get_android_status→get_status, dump_ui_hierarchy→dump_ui, kill_app→terminate_app | — |
| ios | acquire_ios→acquire, release_ios→release, get_ios_status→get_status, press_button→press_key, dump_ui_hierarchy→dump_ui(+max_depth) | — |

**Source:** design §五P3 + §九; the P3 impact-inventory (this session) — it has the full per-file occurrence checklist; re-grep each name before editing.

---

## ⚠ REWORK — apply these (from plan review; supersede the body where they conflict)

1. **Sequencing — keep every commit green (Issue I1):** delete each platform's `[tools.aliases]` block **in the same task as that platform's server rename** (Task 1 = win rename + delete win aliases; Task 2 = mac; Task 3 = android; Task 4 = ios). Run `python3 -m pytest platforms/tests -q` at the end of EACH of Tasks 1-4 → conformance must be green after each (the renamed canonical names are now direct; no dangling alias). Task 5 then only does smoke hooks + a final cross-platform conformance pass. (Do NOT leave aliases pointing at renamed-away functions across tasks.)
2. **Update the tests that reference old names — these run on real machines / Linux and WILL break (Issues B1, B3, I4):**
   - **Task 1** also updates `platforms/windows/server/tests/test_win_server.py`: `srv.get_winpc_status`→`srv.get_status`, `srv.acquire_winpc`→`srv.acquire`, `srv.release_winpc`→`srv.release`.
   - **Task 2** also updates `platforms/macos/server/tests/test_mac_server.py`: `srv.get_mac_status`→`srv.get_status`, `srv.acquire_mac`→`srv.acquire`, `srv.release_mac`→`srv.release`.
   - **Task 3** also updates `platforms/android/server/tests/test_tool_signatures.py` (rewrite the hardcoded `tool_names` list: `acquire_android`→`acquire`, `release_android`→`release`, `get_android_status`→`get_status`, `dump_ui_hierarchy`→`dump_ui`, `kill_app`→`terminate_app`; the count stays 25) AND `platforms/android/server/tests/test_multi_device_state.py` (all `m.acquire_android`/`m.release_android`/`m.get_android_status` → `m.acquire`/`m.release`/`m.get_status`).
3. **Internal callers (Issue B2) — verify the function-body call, not just the def:** Task 3 must change android `find_elements` body line ~1124 `dump_ui_hierarchy(device=serial)` → `dump_ui(device=serial)`. After each server rename, `grep -n "<old_name>(" <server>` must return zero (no internal call left). (mac `find_ui_element`→`list_ui_elements` stays since list_ui_elements is kept.)
4. **Server module docstrings (Issue I3):** Task 6's old-name sweep MUST include the `.py` server files' module-level docstrings (win ~L15-16, mac ~L14-15, android ~L15, ios ~L13 reference `acquire_winpc`/`get_mac_status`/etc.) — update them, else the Task 7 `test_no_legacy_tool_names` guard fires on them. The guard scans `.py` too.
5. **Confirm-in-execution (Issues I2, MINORs):** smoke hooks `get_*_status`→`get_status` in `_hooks.py`/`_android.py`/`_ios.py` (Task 5); win/mac counts go **38→40 / 39→41** (each adds dump_ui + terminate_app); android/ios counts unchanged (25/26). android already has NO `terminate_app` and ios already HAS `terminate_app` (no collision) — verified.
6. **no-legacy guard scope:** forbid the renamed-away names only (`acquire_winpc/release_winpc/get_winpc_status/acquire_mac/release_mac/get_mac_status/acquire_android/release_android/get_android_status/acquire_ios/release_ios/get_ios_status/dump_ui_hierarchy/kill_app/press_button`). Do NOT forbid `inspect_window`/`list_ui_elements`/`kill_process` (kept extensions) or the bare string `click` (renamed, but appears in prose — too noisy; the conformance/AST already proves `click` is gone as a tool).

**Verification:** Linux — `python3 -m pytest platforms/tests -q` (AST conformance must stay green after alias deletion); `cd cli && PYTHONPATH=src python3 -m pytest -q`; `python3 scripts/gen_docs.py --check`; the extended `test_no_legacy_naming`. Real-machine — restart each server, reconnect MCP, call the renamed/added tools.

---

## Task 1: win server renames + add dump_ui/terminate_app
**File:** `platforms/windows/server/win_device_mcp.py`. (Behavior of new dump_ui/terminate_app validated real-machine in Task 7.)
- [ ] Rename `@mcp.tool` defs: `click`→`tap`, `acquire_winpc`→`acquire`, `release_winpc`→`release`, `get_winpc_status`→`get_status`. Update any internal callers (grep within the file).
- [ ] ADD `tap` keeps current click body/params (x,y,button,clicks). ADD `dump_ui(max_depth: int|None=None, …)` — dump the foreground window's UI tree: reuse `inspect_window`'s walk but resolve the foreground window via win32 (`win32gui.GetForegroundWindow` → title) instead of a required `title_substring`; KEEP `inspect_window` as-is (extension). ADD `terminate_app(target: str, …)` — `target` is a process name (e.g. "notepad.exe") or path; find matching processes via psutil and terminate; KEEP `kill_process(pid)` as-is (extension).
- [ ] `python3 -c "import ast;ast.parse(open('platforms/windows/server/win_device_mcp.py').read());print('ok')"` + AST check: the server now exposes `tap`,`acquire`,`release`,`get_status`,`dump_ui`,`terminate_app` (and still `inspect_window`,`kill_process`,`click` GONE).
- [ ] Commit `feat(win)!: rename CORE tools to canonical (tap/acquire/release/get_status) + add dump_ui/terminate_app`.

## Task 2: mac server (mirror Task 1)
**File:** `platforms/macos/server/mac_device_mcp.py`.
- [ ] Rename `click`→`tap`, `acquire_mac`→`acquire`, `release_mac`→`release`, `get_mac_status`→`get_status`.
- [ ] ADD `dump_ui(max_depth=None,…)` dumping the **frontmost app**'s AX tree (reuse `list_ui_elements` internals with the frontmost app via `NSWorkspace.frontmostApplication()` as default); KEEP `list_ui_elements` (extension). ADD `terminate_app(target)` (by app name/bundle) ; KEEP `kill_process(pid)`. **Fix internal callers**: `find_ui_element` calls `list_ui_elements(app=…)` (unchanged — list_ui_elements stays); ensure no call referenced the renamed acquire/etc.
- [ ] ast.parse + AST check (`tap`/`acquire`/`release`/`get_status`/`dump_ui`/`terminate_app` present; `click`/`acquire_mac`/etc gone; `list_ui_elements`/`kill_process` kept).
- [ ] Commit `feat(mac)!: rename CORE tools to canonical + add dump_ui/terminate_app`.

## Task 3: android server (pure renames)
**File:** `platforms/android/server/android_device_mcp.py`.
- [ ] Rename `acquire_android`→`acquire`, `release_android`→`release`, `get_android_status`→`get_status`, `dump_ui_hierarchy`→`dump_ui`, `kill_app`→`terminate_app` (param `package`→`target`, keep behavior). **Fix internal caller** `find_elements` which calls `dump_ui_hierarchy(device=…)` → `dump_ui(device=…)`.
- [ ] ast.parse + AST check (canonical names present; old gone; internal call updated).
- [ ] Commit `feat(android)!: rename CORE tools to canonical (acquire/release/get_status/dump_ui/terminate_app)`.

## Task 4: ios server (renames + press_key + dump_ui max_depth)
**File:** `platforms/ios/server/ios_device_mcp.py`.
- [ ] Rename `acquire_ios`→`acquire`, `release_ios`→`release`, `get_ios_status`→`get_status`, `dump_ui_hierarchy`→`dump_ui` (add optional `max_depth: int|None=None` param — accept; implement truncation if easy else accept+ignore with a docstring TODO), `press_button`→`press_key` (param `button`→`key`; docstring: "iOS supports the physical buttons home/volume_up/volume_down/lock only").
- [ ] ast.parse + AST check.
- [ ] Commit `feat(ios)!: rename CORE tools to canonical (acquire/release/get_status/dump_ui/press_key)`.

## Task 5: delete aliases + conformance + smoke hooks (Linux-verifiable)
**Files:** 4 `platform.toml` (`[tools.aliases]`), `cli/src/fleet/installers/_hooks.py`/`_android.py`/`_ios.py` (smoke tool_names), maybe `platforms/tests/test_conformance.py`.
- [ ] Delete the `[tools.aliases]` block from all 4 `platform.toml`.
- [ ] Smoke hooks: `get_winpc_status`/`get_mac_status`/`get_android_status`/`get_ios_status` → `get_status` (in `_hooks.py`, `_android.py`, `_ios.py`). (Leave `run_powershell`/`run_zsh` — OPTIONAL batch.)
- [ ] Run `python3 -m pytest platforms/tests -q` — AST conformance must be GREEN (each CORE canonical name now a direct `@mcp.tool`; `test_aliases_point_at_real_tools` trivially passes with empty aliases; `KNOWN_P1_GAPS` still `{}`). If a CORE tool is reported missing, a rename was missed — fix the server, don't re-add an alias.
- [ ] `python3 scripts/gen_docs.py --check` — tool COUNTS unchanged (renames don't change counts; win/mac +1 each for the new dump_ui & terminate_app → counts go up by the number of ADDED tools; update README counts accordingly OR run after Task 6). NB: win adds dump_ui+terminate_app = +2 (38→40); mac +2 (39→41); android/ios renames only (no count change). Recompute via AST + fix the 9-README win/mac numbers + commit in Task 6.
- [ ] Commit `feat!: delete [tools.aliases] (canonical names direct) + smoke hooks → get_status`.

## Task 6: sync SKILL.md ×4 + README ×4 + docs + tool counts
**Files:** `platforms/*/skills/using-*/SKILL.md`, `platforms/*/README.md`, `docs/agent-host-setup.md`, `docs/platforms/{windows,macos,android}.md`, `docs/architecture.md`, 9 `README*.md` (counts).
- [ ] In each SKILL.md + platform README + docs, replace the renamed tool names with canonical (per the convergence table). Use the inventory's per-file checklist; grep each old name after to confirm zero in active files (excluding kept extensions inspect_window/list_ui_elements/kill_process/click-as-prose). For win/mac, document the new `dump_ui`/`terminate_app` + that inspect_window/list_ui_elements/kill_process remain as extensions.
- [ ] Recompute AST tool counts (`python3 scripts/gen_docs.py --check` will name mismatches) + fix the win/mac numbers in all 9 READMEs (win 38→40, mac 39→41 — verify exact via AST). `gen_docs.py --check` → green.
- [ ] Commit `docs!: align SKILL.md/README/docs to canonical tool names + update win/mac tool counts`.

## Task 7: test_no_legacy_naming guard + Linux final green
**File:** `cli/tests/test_no_legacy_naming.py`.
- [ ] Add a `LEGACY_TOOL_NAMES` list (forbidden in active code/docs): `acquire_winpc`,`release_winpc`,`get_winpc_status`,`acquire_mac`,`release_mac`,`get_mac_status`,`acquire_android`,`release_android`,`get_android_status`,`acquire_ios`,`release_ios`,`get_ios_status`,`dump_ui_hierarchy`,`kill_app`,`press_button`. **Do NOT** add `inspect_window`/`list_ui_elements`/`kill_process` (kept as extensions) or `click` (appears in prose; it's renamed but the string is noisy — optionally add `click(` but safer to omit). Reuse the existing scan/allowlist machinery (allow `docs/internal/`, `CHANGELOG.md`, the test file itself; the `[tools.aliases]` blocks are deleted so no toml exclusion needed). Add a `test_no_legacy_tool_names()`.
- [ ] Run it → green (after Tasks 1-6 removed all active occurrences). Fix any straggler it names.
- [ ] Full Linux green: `python3 -m pytest platforms/tests -q`; `(cd cli && PYTHONPATH=src python3 -m pytest -q)` (the 1 pre-existing fail aside); `python3 scripts/gen_docs.py --check`.
- [ ] Commit `test!: forbid legacy CORE tool names (test_no_legacy_tool_names)`.

## Task 8: real-machine validation + merge
> Per machine, **confirm before each restart**. SKILL.md cache: after merge, reopen the agent to clear cached skills.
- [ ] Push branch. Deploy to each of the 4 servers (git checkout the branch; android server runs on test-win11 or macmini — locate it). 
- [ ] Restart each server (win: MCP-WinDevice via the detached killer pattern; mac/ios: `launchctl kickstart -k`; android: its service) — **confirm each**. Reconnect MCP (`/mcp`).
- [ ] MCP smoke the renamed/added tools: `get_status` (each), `tap` (win/mac), `acquire`/`release` (each), `dump_ui` (each — win/mac dump foreground, android/ios dump tree), `terminate_app` (a safe target), ios `press_key`. Confirm old names are GONE (calling `get_winpc_status` should fail / not exist).
- [ ] Final whole-impl review (Linux static + machine smoke evidence). Merge to main; re-verify Linux suites; push. Update phasing memory (P3 CORE done; OPTIONAL batch + P4 remain).

---

## Definition of Done (P3 CORE)
- All 4 servers expose canonical CORE names directly (`get_screen_size`/`take_screenshot`/`tap`/`swipe`/`type_text`/`press_key`/`dump_ui`/`current_app`/`terminate_app`/`list_devices`/`set_default_device`/`get_default_device`/`acquire`/`release`/`get_status`); win/mac additionally keep `inspect_window`/`list_ui_elements`/`kill_process` as extensions.
- All `[tools.aliases]` deleted; AST conformance green via direct names; `KNOWN_P1_GAPS=={}`.
- SKILL.md/README/docs use canonical names; win/mac tool counts updated; `gen_docs.py --check` green.
- `test_no_legacy_tool_names` forbids the renamed-away names; green.
- 4 servers restarted + MCP-smoke-validated on real machines; old names gone.

## Out of scope (later)
OPTIONAL renames `run_powershell`/`run_zsh`/`adb_shell`→`run_shell`, `open_app`/`start_app`→`launch_app` (separate batch); the pre-existing `test_has_device_in_result_rejects_unauthorized` cli failure; reconciling macmini's `fix/ios-afc-pushpull`.
