# Extension Foundation — P1a (Linux-testable shared core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task (fresh subagent per task + two-stage review, per our review-gate charter). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the bug-fixed, **Linux-testable** shared-core modules (`_fsops`/`_proc`/`_search`) in `platforms/common/` plus a `DeviceStateRegistry` enhancement, each with full unit tests — **without touching the win/mac servers** (they keep their inline copies until P1b wires them). Strangler pattern: prove the shared implementation correct on Linux *before* the real-machine swap.

**Architecture:** New pure-stdlib modules in `platforms/common/`. We parameterize the one legitimate win/mac difference (shell handling, via a `ShellSpec`) and fix the one latent bug the diff-audit found (Windows is missing `Path.expanduser()` in 8 places). Extracted functions are **plain** (no `@mcp.tool`/`Field`/`ctx`/`with_touch`); P1b's server tools will wrap them. Tests run on Linux (`tmp_path` / Linux `sh`). The win/mac servers are unchanged this phase, so the conformance gate + all P0 suites stay green.

**Tech Stack:** Python 3.11, stdlib (`pathlib`/`shutil`/`subprocess`/`threading`/`shlex`/`re`/`collections`), pytest.

**Source of truth:** design `docs/internal/design/2026-05-21-extension-foundation.md` §五P1 + §九; the code-explorer map (win/mac line ranges + the win-vs-mac diff). **The macOS server is the extraction reference** — it already has the correct `expanduser()`; the Windows versions are byte-identical *except* the missing `expanduser()` (the bug) and shell handling (the legitimate diff).

**Scope boundary (critical):** P1a is **additive** — NO existing server file is modified except `_device_state.py`. Wiring win/mac to consume these modules + the single-device tools + the `swipe` decision are **P1b** (real-machine validation on test-win11/macmini).

---

## File map

**Create**
- `platforms/common/_fsops.py` — 7 file ops as plain, path-expanded, platform-agnostic functions.
- `platforms/common/_proc.py` — process/session ops + `ShellSpec` parameterization (owns its `_processes` registry).
- `platforms/common/_search.py` — recursive content search (owns its `_searches` registry).
- `platforms/common/tests/test_fsops.py`, `test_proc.py`, `test_search.py` — Linux unit tests.

**Modify**
- `platforms/common/_device_state.py` — add `auto_release_in_seconds` to `status()` + `all_status()` in-use returns.
- `platforms/common/tests/test_device_state.py` — cover the new field.

> **Why build modules nobody imports yet:** this is the safe half of the architect's mandated "diff-audit + fix bugs, THEN extract" order. P1a produces the *canonical, bug-fixed, Linux-proven* implementations; P1b swaps the win/mac call sites onto them (the part that needs real machines). Building + testing first de-risks the only high-regression area.

> **Extraction rules (apply to Tasks 2-4):**
> 1. Read the **macOS** version of each function (`platforms/macos/server/mac_device_mcp.py`) as the reference; confirm the Windows version (`platforms/windows/server/win_device_mcp.py`) matches modulo the documented diffs.
> 2. Strip tool plumbing: remove `@mcp.tool`, `@with_touch`, `Annotated[...]`/`Field(...)` wrappers, any `ctx` param, and any `_touch(...)` / `_state_registry.touch(...)` call. The extracted function takes only the **logic** params and returns the **exact same shape** the tool returns today (so P1b wiring is transparent).
> 3. Apply `Path(...).expanduser()` **everywhere a path is taken** (this fixes the Windows bug; `expanduser()` is correct on all platforms).
> 4. Move any module-level state the functions need (registries/locks/constants) into the new module. **Also copy the `_now()` helper** (it returns `datetime.now(timezone.utc)`) into `_proc.py`/`_search.py`, or just inline `datetime.now(timezone.utc)` where used — it has no state.
> 5. Reproduce the body logic faithfully — do not "improve" beyond the expanduser fix + the `ShellSpec` parameterization. If you find a *second* genuine behavioral divergence between win and mac not documented here, STOP and report it (do not silently pick one). NB: `start_search` reads `_searches[search_id]["started_at"]` for its return value *just after* releasing the lock — this is a pre-existing harmless wart in BOTH servers; copy it faithfully (don't "fix" it), it's not a P1a regression.
> 6. **Test import style:** the new test files live in `platforms/common/tests/`, whose `conftest.py` puts `platforms/common` on `sys.path`. Match the existing sibling tests: an in-test `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` (= `platforms/common`) + a **bare** `import _fsops` / `import _proc` / `import _search`. Do NOT use `from common import _x` here (that needs `platforms/` on the path, which these tests don't add).

---

## Task 1: `DeviceStateRegistry.status()` — report `auto_release_in_seconds`

**Files:**
- Modify: `platforms/common/_device_state.py` (`status()` ~line 143, `all_status()` ~line 159)
- Test: `platforms/common/tests/test_device_state.py`

**Why:** win/mac `get_*_status` currently return `auto_release_in_seconds` (win `get_winpc_status` line 175). When P1b migrates them to `DeviceStateRegistry`, `status()` must return that field too, or the output regresses. `status()` and `all_status()` currently omit it.

- [ ] **Step 1: Write the failing test**

Add to `platforms/common/tests/test_device_state.py` (match the file's existing import/setup style — it already imports `DeviceStateRegistry`, `IDLE_TIMEOUT`; read the top of the file first):

```python
def test_status_reports_auto_release_in_seconds():
    from datetime import timedelta
    reg = DeviceStateRegistry(idle_timeout=timedelta(seconds=600))
    reg.acquire("host", "tester")
    st = reg.status("host")
    assert st["in_use"] is True
    # idle just-acquired ~0, so auto_release ~= the full timeout
    assert "auto_release_in_seconds" in st
    assert 0 <= st["auto_release_in_seconds"] <= 600
    assert st["auto_release_in_seconds"] == max(0, 600 - st["idle_seconds"])


def test_all_status_reports_auto_release_in_seconds():
    from datetime import timedelta
    reg = DeviceStateRegistry(idle_timeout=timedelta(seconds=600))
    reg.acquire("host", "tester")
    snap = reg.all_status()["host"]
    assert snap["auto_release_in_seconds"] == max(0, 600 - snap["idle_seconds"])
```

(If the registry constructor signature differs from `DeviceStateRegistry(idle_timeout=...)`, read `_device_state.py` lines 28-40 and adapt the construction — do NOT change the constructor.)

- [ ] **Step 2: Run → fail**

`(cd platforms/common && python3 -m pytest tests/test_device_state.py -q)` → expect FAIL (`KeyError: 'auto_release_in_seconds'`).

- [ ] **Step 3: Implement**

In `_device_state.py`, in the `status()` in-use return (the dict at ~lines 143-149) add, mirroring `acquire()`'s line 94-96:
```python
                "auto_release_in_seconds": max(
                    0, int(self._idle_timeout.total_seconds()) - idle
                ),
```
Add the identical key to the per-serial dict built in `all_status()` (~lines 159-165).

- [ ] **Step 4: Run → pass + no regression**

```bash
(cd platforms/common && python3 -m pytest tests/test_device_state.py -q)        # new tests pass
(cd platforms/common && python3 -m pytest -q)                                    # whole common suite (was 70)
(cd platforms/android/server && python3 -m pytest -q)                            # android uses the registry (was 34)
```
Expect all green. **If an android/common test fails because it asserted the old exact `status()`/`all_status()` shape**, update that test to include the new field (this is a deliberate additive enhancement) — and report which test you adjusted.

- [ ] **Step 5: Commit**
```bash
git add platforms/common/_device_state.py platforms/common/tests/test_device_state.py
git commit -m "feat(common): DeviceStateRegistry.status reports auto_release_in_seconds"
```

---

## Task 2: `_fsops.py` — shared file operations (+ expanduser bug fix)

**Files:**
- Create: `platforms/common/_fsops.py`, `platforms/common/tests/test_fsops.py`

Reference functions (read both, mac is canonical): `read_file`, `write_file`, `edit_block`, `list_directory`, `create_directory`, `move_file`, `get_file_info` — macOS `platforms/macos/server/mac_device_mcp.py` lines ~601-788; Windows `platforms/windows/server/win_device_mcp.py` lines ~624-811 (identical modulo missing `expanduser()` at win:636/678/698/724/763/779-780/798).

- [ ] **Step 1: Read the reference + write failing tests**

Read the mac versions of all 7 functions. Then create `platforms/common/tests/test_fsops.py` (path setup: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` then `from common import _fsops`). Cover, using `tmp_path`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # platforms/common
import _fsops  # bare import — matches existing common tests (test_device_state.py / test_aliases.py)


def test_write_then_read_roundtrip(tmp_path):
    f = tmp_path / "a.txt"
    _fsops.write_file(str(f), "hello\nworld\n")
    out = _fsops.read_file(str(f))
    # match the real return shape — adapt the assert to whatever read_file returns
    # (str content, or a dict with a content field). Read the reference to confirm.
    assert "hello" in (out if isinstance(out, str) else out["content"])


def _content(read_result):
    # read_file may return a str or a dict with a content field — normalize for asserts.
    return read_result if isinstance(read_result, str) else read_result["content"]


def test_edit_block_replaces(tmp_path):
    f = tmp_path / "b.txt"
    _fsops.write_file(str(f), "foo bar foo")
    _fsops.edit_block(str(f), "foo", "X", replace_all=True)
    assert "X bar X" in _content(_fsops.read_file(str(f)))


def test_list_directory(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "f.txt").write_text("x")
    res = _fsops.list_directory(str(tmp_path))
    names = str(res)  # listing shape varies; stringify and assert names present
    assert "f.txt" in names and "sub" in names


def test_create_directory(tmp_path):
    d = tmp_path / "made"
    _fsops.create_directory(str(d))
    assert d.exists()


def test_get_file_info(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x")
    info = _fsops.get_file_info(str(f))
    assert info  # non-empty dict describing the file


def test_move_file(tmp_path):
    src = tmp_path / "s.txt"; src.write_text("x")
    dst = tmp_path / "d.txt"
    _fsops.move_file(str(src), str(dst))
    assert dst.exists() and not src.exists()


def test_expanduser_is_applied(tmp_path, monkeypatch):
    # THE BUG FIX: a path with ~ must expand. Point HOME at tmp_path.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows home var
    _fsops.write_file("~/tilde.txt", "via tilde")
    assert (tmp_path / "tilde.txt").exists()
    content = _fsops.read_file("~/tilde.txt")
    assert "via tilde" in (content if isinstance(content, str) else content["content"])
```
> Before finalizing the asserts, read the mac reference to learn each function's EXACT return shape and adapt the assertions to match it precisely (don't guess — the test must reflect real behavior). Keep `test_expanduser_is_applied` as-is in intent: it is the regression test for the fixed Windows bug.

- [ ] **Step 2: Run → fail** (`ModuleNotFoundError: common._fsops`).
`(cd platforms/common && python3 -m pytest tests/test_fsops.py -q)`

- [ ] **Step 3: Implement `_fsops.py`**

Create `platforms/common/_fsops.py` with a module docstring, then the 7 functions extracted per the **Extraction rules** above: faithful copies of the mac bodies, **stripped** of `@mcp.tool`/`@with_touch`/`Annotated`/`Field`/`ctx`, with `Path(...).expanduser()` applied to every path argument (including both `src` and `dst` in `move_file`), and identical return shapes. Use only stdlib (`pathlib`, `shutil`, builtin `open`).

- [ ] **Step 4: Run → pass**
`(cd platforms/common && python3 -m pytest tests/test_fsops.py -q)` → all pass, including `test_expanduser_is_applied`.

- [ ] **Step 5: Commit**
```bash
git add platforms/common/_fsops.py platforms/common/tests/test_fsops.py
git commit -m "feat(common): shared _fsops file ops (fixes win missing expanduser bug)"
```

---

## Task 3: `_search.py` — shared recursive content search (+ expanduser fix)

**Files:**
- Create: `platforms/common/_search.py`, `platforms/common/tests/test_search.py`

Reference: macOS `mac_device_mcp.py` lines ~794-931 (`_run_search` internal, `start_search`, `get_more_search_results`, `list_searches`, `stop_search` + module-level search-state vars at ~794-797). Windows `win_device_mcp.py` lines ~818-956 — identical except win:869 `start_search` is missing `.expanduser()`.

- [ ] **Step 1: Read reference + write failing tests**

Create `platforms/common/tests/test_search.py` (bare `import _search` per Extraction rule 6). Cover with `tmp_path`: create a few files containing a known token, start a search, page through results, list active searches, stop a search; plus an expanduser regression test (token file under a fake HOME via `monkeypatch.setenv("HOME"/"USERPROFILE", str(tmp_path))`, search path `~/...`). Adapt assertions to the real return shapes after reading the reference (e.g. `start_search` likely returns a search id; `get_more_search_results` returns a page). Search runs in a background thread — **poll** with `time.sleep(0.05)` per iteration up to a 3s max (≈60 iterations) until results appear or the search reports done, rather than a single fixed sleep (avoids flakiness under load; a `tmp_path` search finishes in ms).

- [ ] **Step 2: Run → fail** (`ModuleNotFoundError: common._search`).

- [ ] **Step 3: Implement `_search.py`** per the Extraction rules: module-level `_searches`/lock/constants + the 5 functions (faithful mac bodies, stripped of tool plumbing, `.expanduser()` on the `start_search` path). Stdlib only (`re`, `threading`, `pathlib`, `collections`).

- [ ] **Step 4: Run → pass** (`(cd platforms/common && python3 -m pytest tests/test_search.py -q)`).

- [ ] **Step 5: Commit**
```bash
git add platforms/common/_search.py platforms/common/tests/test_search.py
git commit -m "feat(common): shared _search content search (fixes win missing expanduser bug)"
```

---

## Task 4: `_proc.py` — shared process/session ops + `ShellSpec`

**Files:**
- Create: `platforms/common/_proc.py`, `platforms/common/tests/test_proc.py`

Reference: macOS `mac_device_mcp.py` lines ~408-594 (`_pump_output`, `start_process`, `read_process_output`, `interact_with_process`, `force_terminate`, `list_sessions` + module state `_processes`/`_processes_lock`/`_PROCESS_BUFFER_LINES`). Windows `win_device_mcp.py` lines ~424-617. **Only `start_process` differs** (the shell table + `shlex.split(..., posix=...)`); everything else is byte-identical.

- [ ] **Step 1: Design the `ShellSpec` seam + write failing tests**

`ShellSpec` makes the one real difference injectable:
```python
@dataclass
class ShellSpec:
    shells: dict[str, list[str]]  # shell name -> argv prefix, e.g. {"bash": ["/bin/bash", "-c"]}
    default_shell: str
    shlex_posix: bool             # True on POSIX, False on Windows
```
`start_process(command, shell=..., shell_spec: ShellSpec)` uses `shell_spec` to build argv — direct mode: `shlex.split(command, posix=shell_spec.shlex_posix)`; shell mode: `shell_spec.shells[name] + [command]` (the shells value is the FULL argv prefix and the command is appended as the single last element). Read both `start_process` bodies and confirm this captures them.

The two platforms inject these specs (P1b will pass these; P1a only needs the seam + the Linux test spec). Document them in the module docstring so P1b is unambiguous — note especially that powershell/pwsh need the **multi-flag** prefix and cmd uses `/c`:
```python
# macOS:   ShellSpec(shells={"zsh": ["/bin/zsh","-c"], "bash": ["/bin/bash","-c"], "sh": ["/bin/sh","-c"]},
#                     default_shell="zsh", shlex_posix=True)
# Windows: ShellSpec(shells={
#              "powershell": ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"],
#              "pwsh":       ["pwsh.exe",       "-NoProfile", "-NonInteractive", "-Command"],
#              "cmd":        ["cmd.exe", "/c"],
#          }, default_shell="powershell", shlex_posix=False)
```

Create `platforms/common/tests/test_proc.py` (bare `import _proc` per Extraction rule 6). Use a **Linux** ShellSpec to test on this box:
```python
LINUX_SHELL = _proc.ShellSpec(shells={"bash": ["/bin/bash", "-c"], "sh": ["/bin/sh", "-c"]}, default_shell="bash", shlex_posix=True)
```
Cover: start a quick command (e.g. `echo hello` in shell mode, or a direct `["/bin/echo","hi"]`), poll `read_process_output` until the output contains the expected text, `list_sessions` shows it, then `force_terminate`. Also test a long-runner (`sleep 5`) + `interact_with_process` if applicable, then terminate it so the test doesn't hang (use small timeouts). Adapt to real return shapes after reading the reference.

- [ ] **Step 2: Run → fail** (`ModuleNotFoundError: common._proc`).

- [ ] **Step 3: Implement `_proc.py`** per Extraction rules: module state + the 6 functions; `start_process` parameterized by `ShellSpec` (the ONLY behavioral change vs the faithful copy). Everything else byte-faithful. Stdlib only (`subprocess`, `threading`, `shlex`, `collections`).

- [ ] **Step 4: Run → pass** (`(cd platforms/common && python3 -m pytest tests/test_proc.py -q)`). Ensure no test leaves a stray process (terminate in each test).

- [ ] **Step 5: Commit**
```bash
git add platforms/common/_proc.py platforms/common/tests/test_proc.py
git commit -m "feat(common): shared _proc process/session ops + ShellSpec parameterization"
```

---

## Task 5: Final green + collection check

- [ ] **Step 1: Run every Linux suite separately**
```bash
(cd platforms/common && python3 -m pytest -q)            # 70 + new fsops/proc/search/device_state tests
(cd platforms/android/server && python3 -m pytest -q)    # 34 (no regression)
python3 -m pytest platforms/tests -q                     # 23 (P0 conformance/manifests — unaffected)
(cd platforms/ios/server && python3 -m pytest -q)        # 1
```
Expect all green. The new common modules are NOT yet imported by any server (P1b does that), so conformance is unchanged.

- [ ] **Step 2: Sanity — new modules import clean + are pure stdlib**
```bash
python3 -c "import sys;sys.path.insert(0,'platforms');import common._fsops,common._proc,common._search;print('import OK')"
```
Expect `import OK` (no GUI deps pulled in).

---

## Definition of Done (P1a)

- `_fsops.py` / `_proc.py` / `_search.py` exist in `platforms/common/`, pure-stdlib, each with passing Linux unit tests.
- The Windows `expanduser` bug is fixed in the shared versions (regression test in `test_fsops.py`, and search path in `test_search.py`).
- `start_process`'s win/mac difference is captured in `ShellSpec` (injectable), tested with a Linux spec.
- `DeviceStateRegistry.status()`/`all_status()` report `auto_release_in_seconds`; android/common suites still green.
- **No win/mac/android/ios server file modified** (only `_device_state.py`); conformance gate + all P0 suites stay green.
- Extracted function bodies are faithful to the macOS reference except the documented `expanduser` fix + `ShellSpec` parameterization.

## Handoff to P1b (real machines — NOT this plan)

P1b (on test-win11 + macmini): replace win/mac inline file/proc/search copies with `from common._fsops/_proc/_search import ...` (inject each platform's `ShellSpec`); migrate win/mac holders to `DeviceStateRegistry("host")`; add single-device CORE tools (`current_app`/`list_devices`/`set_default_device`/`get_default_device`); decide `swipe` (desktop click-drag vs demote to OPTIONAL); then shrink `KNOWN_P1_GAPS` and re-run conformance. Each win/mac change validated by running that server on its real OS.

**P1b wiring notes (from the P1a code reviews — don't lose these when wrapping the shared functions as `@mcp.tool`s):**
- `_proc.start_process`'s library default is `shell="direct"`. The **per-platform user-facing default must stay at the tool layer** (`Annotated[str, Field(...)] = "zsh"` on mac, `= "powershell"` on win) — do NOT let the library's `"direct"` default become the MCP-exposed default.
- The FastMCP `Field` validation bounds that lived on the old tools (e.g. `read_process_output` `length` `ge=1, le=5000`; `offset` semantics) are transport-layer constraints stripped during extraction — **re-apply them at the tool wrapper layer** when wiring.
- The extracted functions return the exact same shapes as the old tools, so the wrappers are thin: `@mcp.tool` + `@with_touch` → call the `common.*` function → return. Inject `ShellSpec` for `start_process`; pass the fixed serial `"host"` to `DeviceStateRegistry` for the holder tools.
