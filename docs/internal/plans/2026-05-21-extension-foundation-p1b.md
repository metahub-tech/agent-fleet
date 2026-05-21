# Extension Foundation — P1b (win/mac wiring + single-device tools) Implementation Plan

> **For agentic workers:** Mixed execution — the code edits + static conformance are done + verified on Linux; runtime validation happens on the real machines (test-win11 `win-device`, macmini `mac-device`). Steps use checkbox (`- [ ]`).

**Goal:** Consume the P1a shared core in the win/mac servers: replace their inline file/proc/search copies with thin delegations to `common._fsops`/`_proc`/`_search` (injecting each platform's `ShellSpec`), migrate the single-holder state to `DeviceStateRegistry("host")`, add the 4 single-device CORE tools (`current_app`/`list_devices`/`set_default_device`/`get_default_device`), implement `swipe` as a desktop click-drag, add Linux-importable-on-machine server unit tests, then shrink `KNOWN_P1_GAPS` to empty and re-green the AST conformance gate.

**Architecture:** Each `@mcp.tool` keeps its EXACT agent-facing signature (`Annotated`/`Field` preserved, incl. the validation bounds); the body becomes a one-line call into the shared `common` function. The ~520 lines of duplicated file/proc/search/holder logic per server are DELETED and replaced by imports + thin wrappers. acquire/release/get_status converge onto the `DeviceStateRegistry` return shapes (same as android/ios). **Static verification on Linux** (AST conformance proves the tools exist with right arity + lets us shrink `KNOWN_P1_GAPS`); **runtime verification on the real machines** (dry-import, new server unit tests in-venv, restart, MCP smoke test).

**Tech Stack:** Python 3.11 (win venv) / 3.10 (mac venv); the servers' existing deps (pyautogui/pywinauto/pyperclip/pyobjc/win32) + the pure-stdlib `common` modules.

**Source:** design §五P1 + §九; P1a plan's "Handoff to P1b" notes; code-explorer map (win holder ~62-101, file ops ~624-811, proc ~424-617, search ~818-956; mac equivalents per the map).

**Constraint:** win/mac servers cannot be imported on this Linux box → the Linux side edits + `ast.parse` + AST conformance only; all runtime checks run on the machines.

---

## File map

**Modify**
- `platforms/windows/server/win_device_mcp.py` — add `common` imports + `ShellSpec`; replace file/proc/search/holder bodies with delegations; add `current_app`/`list_devices`/`set_default_device`/`get_default_device`/`swipe`.
- `platforms/macos/server/mac_device_mcp.py` — same.
- `platforms/tests/test_conformance.py` — shrink `KNOWN_P1_GAPS` to `{}` (both desktops now cover all CORE).

**Create**
- `platforms/windows/server/tests/__init__.py`, `platforms/windows/server/tests/test_win_server.py` — run in the win venv on test-win11.
- `platforms/macos/server/tests/__init__.py`, `platforms/macos/server/tests/test_mac_server.py` — run in the mac venv on macmini.

> **Wiring rules (apply to both servers):**
> 1. Keep every `@mcp.tool` signature byte-for-byte (the agent API + `Field` bounds stay). Only the BODY changes to `return _fsops.X(...)` / `return _proc.X(..., shell_spec=_SHELL)` / `return _search.X(...)`.
> 2. Add near the top (after the existing imports), mirroring how android/ios reach common:
>    ```python
>    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))
>    import _fsops, _proc, _search
>    from _device_state import DeviceStateRegistry
>    ```
> 3. DELETE the now-shared inline definitions: the file ops bodies, the proc subsystem (`_pump_output`, `_processes`/lock/buffer-const, the 6 proc tool bodies), the search subsystem (`_run_search`, `_searches`/state, the 5 search tool bodies), and the holder block (`_Holder`/`_holder`/`_state_lock`/`_now`/`_check_idle_release_locked`/`_touch`). Keep the GUI tools (screenshot/mouse/keyboard/window/AX/app) and `run_powershell`/`run_zsh`/`run_applescript` UNTOUCHED.
> 4. `start_process` wrapper injects the platform `_SHELL` spec; keep the tool's `shell` default at the agent layer (`= "powershell"` win / `= "zsh"` mac) — do NOT expose the library default `"direct"`.
> 5. Surgical edits only — never touch the GUI tool code. After editing, `python3 -c "import ast; ast.parse(open(<server>).read())"` must pass on Linux.
> 6. **ATOMICITY (important):** do the holder-block replacement + the file/proc/search body delegations + the deletion of the now-orphaned helpers as **one editing pass, committed together**. The file is only required to be runnable AFTER the whole pass — not between sub-steps. Specifically: write the new `with_touch` (calling `_state_registry.touch`) BEFORE removing `_touch()` (every GUI tool uses `@with_touch`), and do NOT delete `_now()`/the holder block until the proc/search bodies that referenced `_now()` have been replaced with delegations. Easiest safe order within the single pass: (a) add imports + `_state_registry`/`_SHELL`; (b) replace the proc + search + file tool bodies with delegations; (c) replace the 3 holder tools + `with_touch`; (d) delete all now-unused inline helpers (`_Holder`/`_holder`/`_state_lock`/`_now`/`_check_idle_release_locked`/`_touch`/`_pump_output`/`_processes`/`_searches`/`_run_search` + their state); (e) `ast.parse` check; (f) single commit.

---

## Task 1: Wire the Windows server (`win_device_mcp.py`)

**Files:** Modify `platforms/windows/server/win_device_mcp.py`.

- [ ] **Step 1: Add common imports + the platform ShellSpec.** After the existing imports (the block ends ~line 47, `from pywinauto import Desktop`), add the sys.path insert + `import _fsops, _proc, _search` + `from _device_state import DeviceStateRegistry`, and define:
```python
_state_registry = DeviceStateRegistry()  # name matches android/ios servers
_SERIAL = "host"
_SHELL = _proc.ShellSpec(
    shells={
        "powershell": ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"],
        "pwsh": ["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command"],
        "cmd": ["cmd.exe", "/c"],
    },
    default_shell="powershell",
    shlex_posix=False,
)
```

- [ ] **Step 2: Replace the holder block (lines ~62-101) with the registry-backed version:**
```python
def with_touch(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _state_registry.touch(_SERIAL)
        return fn(*args, **kwargs)
    return wrapper
```
Then make the three holder tools delegate (KEEP their `@mcp.tool` signatures):
```python
@mcp.tool
def acquire_winpc(holder_name: Annotated[str, Field(...)] = "anonymous") -> dict:  # KEEP current default
    return _state_registry.acquire(_SERIAL, holder_name)

@mcp.tool
def release_winpc(holder_name: Annotated[str, Field(...)] = "anonymous") -> dict:  # KEEP current default
    return _state_registry.release(_SERIAL, holder_name)

@mcp.tool
def get_winpc_status() -> dict:
    return _state_registry.status(_SERIAL)
```
(Preserve the real `Field(description=...)` text from the current signatures — read them first. Delete `_Holder`/`_holder`/`_state_lock`/`_now`/`_check_idle_release_locked`/`_touch`.)

- [ ] **Step 3: Delegate the file ops.** For each of `read_file`, `write_file`, `edit_block`, `list_directory`, `create_directory`, `move_file`, `get_file_info`: keep the `@mcp.tool` + `@with_touch` + signature; replace the body with `return _fsops.<name>(<the plain args>)`. Delete the old inline logic.

- [ ] **Step 4: Delegate the proc ops.** `start_process` body → `return _proc.start_process(command, shell, shell_spec=_SHELL)`. `read_process_output`/`interact_with_process`/`force_terminate`/`list_sessions` bodies → `return _proc.<name>(...)`. Delete the inline `_pump_output`, `_processes`/lock/buffer constant.

- [ ] **Step 5: Delegate the search ops.** `start_search`/`get_more_search_results`/`list_searches`/`stop_search` bodies → `return _search.<name>(...)`. Delete inline `_run_search` + search state.

- [ ] **Step 6: Add the 4 single-device CORE tools + swipe.**
```python
import socket  # if not already imported

@mcp.tool
@with_touch
def list_devices() -> list[dict]:
    """Single-device platform: always one entry, the host machine itself."""
    st = _state_registry.status(_SERIAL)
    return [{"serial": _SERIAL, "device": _SERIAL, "model": socket.gethostname(),
             "status": "in_use" if st.get("in_use") else "available", "default": True}]

@mcp.tool
def set_default_device(device: Annotated[str, Field(description="ignored on single-device platforms")] = "host") -> dict:
    return {"default": _SERIAL, "note": "single-device platform; always targets the host"}

@mcp.tool
def get_default_device() -> dict:
    return {"default": _SERIAL}

@mcp.tool
@with_touch
def current_app() -> dict:
    """Foreground app on the Windows host."""
    import win32gui, win32process  # pywin32 (ships with pywinauto)
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        name = psutil.Process(pid).name()
    except Exception:
        name = None
    return {"app": name, "title": title, "pid": pid}

@mcp.tool
@with_touch
def swipe(
    x1: Annotated[int, Field(description="start x")],
    y1: Annotated[int, Field(description="start y")],
    x2: Annotated[int, Field(description="end x")],
    y2: Annotated[int, Field(description="end y")],
    duration_ms: Annotated[int, Field(description="drag duration in ms")] = 300,
) -> dict:
    """Desktop swipe = left-button click-drag from (x1,y1) to (x2,y2)."""
    pyautogui.moveTo(x1, y1)
    pyautogui.dragTo(x2, y2, duration=max(0.0, duration_ms / 1000.0), button="left")
    return {"ok": True, "from": [x1, y1], "to": [x2, y2], "duration_ms": duration_ms}
```

- [ ] **Step 7: Static check on Linux.** `python3 -c "import ast; ast.parse(open('platforms/windows/server/win_device_mcp.py').read()); print('parse OK')"`. Then confirm the AST extractor sees all CORE names:
```bash
python3 -c "import sys;sys.path.insert(0,'platforms/tests');from _ast_tools import extract_mcp_tools;t=extract_mcp_tools('platforms/windows/server/win_device_mcp.py');print(sorted(set(['get_screen_size','take_screenshot','click','swipe','type_text','press_key','inspect_window','current_app','kill_process','list_devices','set_default_device','get_default_device','acquire_winpc','release_winpc','get_winpc_status']) - set(t)) or 'all CORE-relevant tools present')"
```
Expected: `all CORE-relevant tools present`.

- [ ] **Step 7b: Make the `pywin32` dependency explicit.** `current_app` uses `win32gui`/`win32process`, which today come transitively via `pywinauto`. Add an explicit line to `platforms/windows/server/requirements.txt`: `pywin32>=303; sys_platform == "win32"` (idempotent — pywinauto already pulls it; this just removes the implicit dependency). Include this file in the commit.

- [ ] **Step 8: Commit.**
```bash
git add platforms/windows/server/win_device_mcp.py platforms/windows/server/requirements.txt
git commit -m "feat(win): wire server onto common _fsops/_proc/_search + DeviceStateRegistry; add single-device tools + swipe"
```

---

## Task 2: Wire the macOS server (`mac_device_mcp.py`)

**Files:** Modify `platforms/macos/server/mac_device_mcp.py`. Same as Task 1, adapted to mac:
- ShellSpec: `shells={"zsh":["/bin/zsh","-c"],"bash":["/bin/bash","-c"],"sh":["/bin/sh","-c"]}, default_shell="zsh", shlex_posix=True`.
- holder tools: `acquire_mac`/`release_mac`/`get_mac_status` → delegate to `_state` with `_SERIAL="host"`.
- file/proc/search: delegate identically.
- `current_app` (mac): use `osascript` (the server already shells AppleScript) —
```python
@mcp.tool
@with_touch
def current_app() -> dict:
    """Frontmost app on the macOS host."""
    import subprocess
    script = 'tell application "System Events" to get name of first application process whose frontmost is true'
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return {"app": None, "error": "osascript timeout"}
    except Exception as e:  # noqa: BLE001 — surface as a friendly dict, not a framework crash
        return {"app": None, "error": str(e)}
    return {"app": r.stdout.strip() or None}
```
- `list_devices`/`set_default_device`/`get_default_device`: identical to win (use `socket.gethostname()`).
- `swipe`: identical pyautogui click-drag.

- [ ] Steps mirror Task 1 (imports+ShellSpec → holder → file → proc → search → 4 tools+swipe → `ast.parse` + AST-extractor CORE check → commit `feat(mac): wire server onto common modules + DeviceStateRegistry; add single-device tools + swipe`).

---

## Task 3: Shrink `KNOWN_P1_GAPS` + re-green conformance (Linux, static)

**Files:** Modify `platforms/tests/test_conformance.py`.

- [ ] **Step 1:** Change `KNOWN_P1_GAPS` to `{}` (both desktop platforms now implement all CORE). Update `test_known_gaps_shrink()` to assert `KNOWN_P1_GAPS == {}`.
- [ ] **Step 2: Run the gate** `python3 -m pytest platforms/tests/test_conformance.py -q`. Expected: ALL 4 platforms green via direct names + aliases — win/mac now cover `swipe`/`current_app`/`list_devices`/`set_default_device`/`get_default_device` directly (no gaps). If a tool is reported missing/under-arity, the wiring in Task 1/2 didn't expose it correctly — fix the server, don't loosen the gate.
- [ ] **Step 3: Full Linux suite** (separately): `python3 -m pytest platforms/tests -q`; `(cd platforms/common && python3 -m pytest -q)`; `(cd platforms/android/server && python3 -m pytest -q)`. All green.
- [ ] **Step 4: Commit** `feat(tests): shrink KNOWN_P1_GAPS to empty — win/mac now cover all CORE`.

---

## Task 4: win/mac server unit tests (run in-venv on the real machines)

**Files:** Create `platforms/{windows,macos}/server/tests/__init__.py` + `test_{win,mac}_server.py`.

> **Floor + primary proof:** the minimum these tests guarantee is `import <server>` succeeds on the real OS (deps + syntax + the new `common` imports resolve) — that alone is valuable. Calling `@mcp.tool`-decorated functions depends on the fastmcp version (a bare `@mcp.tool` may yield a Tool object whose original is at `.fn`); use `.fn` if direct calls fail, and if a clean accessor isn't available, lean on **Task 5's MCP smoke test as the primary runtime proof** and keep these unit tests to the import + the plain (non-tool) helpers + the new tools' `.fn`.

These import the server module (only possible on the real OS) and exercise the wiring + new tools with light assertions. Keep them fast + non-destructive (no real file clobber outside tmp; no long processes). Cover, per platform:
- the delegation is wired: e.g. `read_file`/`write_file` round-trip in a tmp dir; `start_process` runs a trivial command and `read_process_output` returns it; `list_searches` works.
- holder: `acquire_*`/`get_*_status`/`release_*` round-trip (status shows in_use then free; includes `auto_release_in_seconds`).
- new tools: `list_devices()` returns a single host entry with `default=True`; `get_default_device()`/`set_default_device()` return host; `current_app()` returns a dict (don't assert a specific app — just that it returns without error and has the expected keys).
- (swipe is GUI/cursor-moving — DON'T run it in the unit test to avoid moving the real cursor; it's covered by the MCP smoke test in Task 5 if desired, gated on the machine being idle.)

- [ ] **Step 1:** Write `test_win_server.py` (importable only on Windows; that's fine — it runs in the win venv on test-win11). Path setup: insert the server dir; `import win_device_mcp as srv`; call the underlying functions. NOTE: `@mcp.tool`-decorated functions may be wrapped — call the FastMCP-registered callable or the plain function as the codebase allows (read how android server tests, if any, call tools; else call `srv.read_file.fn` / the registered tool — determine the right accessor on the machine and adapt).
- [ ] **Step 2:** Write `test_mac_server.py` analogously.
- [ ] **Step 3: Commit** `test(win,mac): in-venv server unit tests for wiring + single-device tools`.

> These are NOT run on Linux (they import GUI deps). They run in Task 5 on the machines.

---

## Task 5: Deploy + runtime-validate on the real machines

> Per-machine, do test-win11 then macmini. **Confirm with the human before each server restart** (it drops + reconnects MCP).

- [ ] **Step 1: Push the branch** `git push -u origin feat/extension-foundation-p1b`.
- [ ] **Step 2 (each machine): deploy.** Via `run_powershell`/`run_zsh`: `cd <repo>; git fetch origin feat/extension-foundation-p1b; git checkout -B feat/extension-foundation-p1b origin/feat/extension-foundation-p1b`. Confirm clean tree first (it's on main, clean).
- [ ] **Step 3 (each machine): install pytest into the venv** (runtime venvs lack it): `<venv python> -m pip install pytest`.
- [ ] **Step 4 (each machine): dry-import + run the new server tests in-venv** (no port bind): `<venv python> -c "import <server>; print('import OK')"` then `<venv python> -m pytest server/tests -q`. Green = wiring works on the real OS. Fix-forward on failures (edit on Linux, push, re-pull).
- [ ] **Step 5 (each machine): CONFIRM, then restart the server.** win: `Stop-ScheduledTask -TaskName MCP-WinDevice; Start-ScheduledTask -TaskName MCP-WinDevice` (and kill any stray duplicate `python311` win_device_mcp process first). mac: `launchctl kickstart -k gui/$(id -u)/cc.metahub.mac-device`. Wait for the MCP client to reconnect.
- [ ] **Step 6 (each machine): MCP smoke test** through the device tools: `get_winpc_status`/`get_mac_status` (shows `auto_release_in_seconds`), `list_devices` (single host entry), `current_app`, a `read_file`/`write_file` round-trip in a temp path, a `run_powershell`/`run_zsh` sanity, and (if the machine is idle/unlocked) one `swipe` in a safe screen region. Confirm no regression in the GUI tools (a `get_screen_size` + `take_screenshot`).
- [ ] **Step 7:** If all green on both machines, proceed to finish.

---

## Task 6: Finish

- [ ] Final whole-impl review (Linux static + the machine smoke-test evidence).
- [ ] Merge `feat/extension-foundation-p1b` → main; re-verify Linux suites on main; push.
- [ ] Update the project-phasing memory (P1 complete; next P2). Note `KNOWN_P1_GAPS` is now empty (P1 tripwire satisfied).

---

## Definition of Done (P1b)

- win/mac servers import file/proc/search from `common` (inline copies deleted); `start_process` uses the platform `ShellSpec`; tool signatures + `Field` bounds unchanged.
- Holders use `DeviceStateRegistry("host")`; acquire/release/get_status converge on the shared shapes (incl. `auto_release_in_seconds`).
- win/mac expose `current_app`/`list_devices`/`set_default_device`/`get_default_device`/`swipe`.
- `KNOWN_P1_GAPS == {}`; AST conformance green for all 4 platforms; android/common/P0 suites unchanged on Linux.
- New win/mac server unit tests pass **in-venv on the real machines**; both servers restart cleanly; MCP smoke test green on both.
- macmini's `fix/ios-afc-pushpull` iOS work remains untouched.
