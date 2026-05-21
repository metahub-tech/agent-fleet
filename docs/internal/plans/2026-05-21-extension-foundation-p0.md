# Extension Foundation — P0 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task (fresh subagent per task + two-stage review, per our review-gate charter). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Lay the additive, low-regression foundation for fast/isolated platform onboarding: a per-platform SSOT manifest, a code-level canonical tool contract, and an AST-based conformance + manifest test gate — all green today via alias declarations (no tool renames yet; those are P3).

**Architecture:** `platforms/common/` becomes an importable local package holding the canonical contract (`_canonical_tools.py`) and manifest loader (`_manifest.py`). Each platform ships a `platform.toml` declaring its identity + a `[tools.aliases]` map (current tool name → canonical name). A repo-level `platforms/tests/` suite statically parses each server's `@mcp.tool` defs with `ast` (never importing them — win/mac/android can't import on Linux CI) and asserts every canonical CORE tool is covered (directly or via alias) with compatible arity, plus port-uniqueness and version consistency.

**Tech Stack:** Python 3.10+ (servers run 3.12), `ast` (stdlib), `tomllib` (3.11+; `tomli` fallback for 3.10), pytest.

Source of truth for this plan: `docs/internal/design/2026-05-21-extension-foundation.md` (§三支柱1/2/4, §五P0, §九).

---

## File map

**Create**
- `platforms/common/__init__.py` — makes `common` an importable package.
- `platforms/common/_canonical_tools.py` — canonical CORE/OPTIONAL contract (names + param specs).
- `platforms/common/_manifest.py` — `platform.toml` loader → `PlatformManifest` dataclass.
- `platforms/{windows,macos,android,ios}/platform.toml` — per-platform SSOT + `[tools.aliases]`.
- `platforms/tests/__init__.py`, `platforms/tests/conftest.py` — repo-level test package + path setup.
- `platforms/tests/test_canonical_tools.py` — contract well-formedness.
- `platforms/tests/test_manifests.py` — load all manifests; port-unique; host_os valid; version consistency.
- `platforms/tests/test_conformance.py` — AST: every CORE canonical tool covered per platform.
- `platforms/tests/_ast_tools.py` — helper: extract `@mcp.tool` function names + params from a server file via `ast`.
- `platforms/ios/server/tests/test_ios_devices.py` — Linux-runnable iOS helper tests.

**Modify**
- `platforms/android/server/android_device_mcp.py:51-54` — `sys.path`/import → `common.` package form.
- `platforms/ios/server/ios_device_mcp.py:52-55` — same.
- `platforms/ios/server/_ios_devices.py` — same import form (it imports `_aliases`).
- `platforms/android/server/tests/conftest.py:5-6` — path setup for package form.
- `platforms/ios/server/ios_device_mcp.py:399-403` — `take_screenshot` add `region=None`.
- `cli/pyproject.toml` — add `tomli; python_version < "3.11"` to `dev` extras (test dep).

> **Deferred to P1 (not P0):** win/mac server unit tests for the holder/process/file/search blocks. Reason: those servers import `pyautogui`/`pywinauto`/`pyobjc` and **cannot be imported on Linux CI**; their core logic moves into testable `platforms/common/` modules during P1's extraction and gets covered there. P0 covers the cross-platform contract via AST (no import) + adds the iOS helper tests that *are* Linux-runnable.

---

## Task 1: Make `platforms/common/` an importable package

**Files:**
- Create: `platforms/common/__init__.py`
- Modify: `platforms/android/server/android_device_mcp.py:51-54`, `platforms/ios/server/ios_device_mcp.py:52-55`, `platforms/ios/server/_ios_devices.py`, `platforms/android/server/tests/conftest.py:5-6`

- [ ] **Step 1: Baseline — run existing tests green**

Run: `cd platforms/common && python -m pytest -q; cd ../android/server && python -m pytest -q`
Expected: all PASS (this is a refactor; record the baseline).

- [ ] **Step 2: Create the package marker**

Create `platforms/common/__init__.py`:

```python
"""Shared bridge core for agent-fleet platform servers (local package; not published)."""
```

- [ ] **Step 3: Switch android server to package imports**

In `platforms/android/server/android_device_mcp.py`, replace lines 51-54:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))

from _aliases import DeviceInfo, derive_alias, load_aliases, resolve_aliases
from _device_state import DeviceStateRegistry
```

with (insert `platforms/`, import via `common.` namespace):

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # platforms/

from common._aliases import DeviceInfo, derive_alias, load_aliases, resolve_aliases
from common._device_state import DeviceStateRegistry
```

- [ ] **Step 4: Switch ios server + `_ios_devices.py` to package imports**

In `platforms/ios/server/ios_device_mcp.py` lines 52-55, apply the identical change (insert `parent.parent.parent` = `platforms/`, import `from common._aliases import ...` / `from common._device_state import ...`).

In `platforms/ios/server/_ios_devices.py`, find its `sys.path.insert(... / "common")` + `from _aliases import ...` and apply the same `common.` form. (Run `grep -n "_aliases\|sys.path" platforms/ios/server/_ios_devices.py` to locate.)

- [ ] **Step 5: Update android test conftest**

In `platforms/android/server/tests/conftest.py`, replace lines 5-6:

```python
sys.path.insert(0, str(_here.parent))                           # server dir
sys.path.insert(0, str(_here.parent.parent.parent / "common"))  # platforms/common
```

with:

```python
sys.path.insert(0, str(_here.parent))                    # server dir
sys.path.insert(0, str(_here.parent.parent.parent.parent))  # platforms/ (for `common` package)
```

(Verify `_here.parent.parent.parent.parent` resolves to `platforms/`: conftest is at `platforms/android/server/tests/conftest.py` → parent=tests, .parent=server, .parent=android, .parent=platforms. Correct.)

- [ ] **Step 6: Update common's own test conftest if it imports bare modules**

Run `grep -rn "from _aliases\|from _device_state\|import _aliases" platforms/common/tests/`. If found, change to `from common._aliases import ...` and ensure `platforms/common/tests/conftest.py` inserts `platforms/` (`_here.parent.parent.parent`). If common tests already use a path that works, leave them.

- [ ] **Step 7: Run all affected tests — still green**

Run: `cd platforms/common && python -m pytest -q; cd ../android/server && python -m pytest -q`
Expected: same PASS count as Step 1 baseline. (Pure refactor — no behavior change.)

- [ ] **Step 8: Commit**

```bash
git add platforms/common/__init__.py platforms/android/server/android_device_mcp.py platforms/ios/server/ios_device_mcp.py platforms/ios/server/_ios_devices.py platforms/android/server/tests/conftest.py platforms/common/tests/
git commit -m "refactor(common): make platforms/common an importable package (common.*)"
```

---

## Task 2: Canonical tool contract (`_canonical_tools.py`)

**Files:**
- Create: `platforms/common/_canonical_tools.py`
- Test: `platforms/tests/test_canonical_tools.py` (+ `platforms/tests/__init__.py`)

- [ ] **Step 1: Write the failing test**

Create `platforms/tests/__init__.py` (empty) and `platforms/tests/test_canonical_tools.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # platforms/
from common import _canonical_tools as ct


def test_core_has_expected_tools():
    assert set(ct.CORE) == {
        "get_screen_size", "take_screenshot", "tap", "swipe", "type_text",
        "press_key", "dump_ui", "current_app", "terminate_app",
        "list_devices", "set_default_device", "get_default_device",
        "acquire", "release", "get_status",
    }


def test_param_specs_are_lists_of_str():
    for spec in {**ct.CORE, **ct.OPTIONAL}.values():
        assert isinstance(spec, list)
        assert all(isinstance(p, str) for p in spec)


def test_required_params_helper_strips_optional_marker():
    # "x", "y", "duration_ms?" -> required {"x","y"}
    assert ct.required_params(["x", "y", "duration_ms?"]) == {"x", "y"}


def test_allowed_extra_contains_plumbing():
    assert {"device", "ctx"} <= ct.ALLOWED_EXTRA
```

- [ ] **Step 2: Run it — fails (module missing)**

Run: `python -m pytest platforms/tests/test_canonical_tools.py -q`
Expected: FAIL (`ModuleNotFoundError: common._canonical_tools`).

- [ ] **Step 3: Implement the contract**

Create `platforms/common/_canonical_tools.py`:

```python
"""Canonical Universal Tool Set — the single code-level source of truth.

Param specs list the canonical parameter NAMES; a trailing "?" marks an optional
param. `device`/`ctx` are multi-device plumbing allowed on any tool and never
required. P0 conformance checks tool COVERAGE + required-arity (not exact param
names — name canonicalization lands in P3 with the renames).
"""

CORE: dict[str, list[str]] = {
    "get_screen_size": [],
    "take_screenshot": ["region?"],
    "tap": ["x", "y"],
    "swipe": ["x1", "y1", "x2", "y2", "duration_ms?"],
    "type_text": ["text"],
    "press_key": ["key"],
    "dump_ui": ["max_depth?"],
    "current_app": [],
    "terminate_app": ["target"],
    "list_devices": [],
    "set_default_device": ["device"],
    "get_default_device": [],
    "acquire": ["holder_name?"],
    "release": [],
    "get_status": [],
}

OPTIONAL: dict[str, list[str]] = {
    "launch_app": ["target"],
    "find_elements": ["query"],
    "tap_element": ["query"],
    "run_shell": ["script", "timeout?"],
    "long_press": ["x", "y", "duration_ms?"],
    "install_app": ["path"],
    "uninstall_app": ["target"],
}

# Plumbing params that may appear on any tool and are never counted/required.
ALLOWED_EXTRA: set[str] = {"device", "ctx"}


def required_params(spec: list[str]) -> set[str]:
    """Param names without the optional `?` marker stripped of optionals."""
    return {p for p in spec if not p.endswith("?")}


def required_arity(spec: list[str]) -> int:
    """Count of required (non-optional) params."""
    return len(required_params(spec))
```

- [ ] **Step 4: Run it — passes**

Run: `python -m pytest platforms/tests/test_canonical_tools.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add platforms/common/_canonical_tools.py platforms/tests/__init__.py platforms/tests/test_canonical_tools.py
git commit -m "feat(common): canonical tool contract (_canonical_tools.py)"
```

---

## Task 3: Manifest loader (`_manifest.py`)

**Files:**
- Create: `platforms/common/_manifest.py`
- Test: `platforms/tests/test_manifest_loader.py`
- Modify: `cli/pyproject.toml` (add `tomli` fallback for py3.10)

- [ ] **Step 1: Add tomli fallback dep**

In `cli/pyproject.toml` under `[project.optional-dependencies]`, change the `dev` line to include tomli for 3.10:

```toml
dev = ["pytest>=8.0", "pytest-mock>=3.12", "tomli>=2.0; python_version < '3.11'"]
```

- [ ] **Step 2: Write the failing test**

Create `platforms/tests/test_manifest_loader.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # platforms/
from common._manifest import load_manifest, PlatformManifest

REPO = Path(__file__).resolve().parent.parent.parent  # repo root


def test_loads_ios_manifest():
    m = load_manifest(REPO / "platforms" / "ios" / "platform.toml")
    assert isinstance(m, PlatformManifest)
    assert m.id == "ios-device"
    assert m.port == 8769
    assert m.server_module == "ios_device_mcp"
    assert isinstance(m.aliases, dict)
    assert m.server_path.name == "ios_device_mcp.py"
    assert m.server_path.exists()


def test_aliases_map_canonical_to_current():
    m = load_manifest(REPO / "platforms" / "ios" / "platform.toml")
    # canonical "tap" is provided directly (ios already has tap)
    # canonical "acquire" is provided by current "acquire_ios"
    assert m.aliases.get("acquire") == "acquire_ios"
```

- [ ] **Step 3: Run it — fails**

Run: `python -m pytest platforms/tests/test_manifest_loader.py -q`
Expected: FAIL (`ModuleNotFoundError: common._manifest`).

- [ ] **Step 4: Implement the loader**

Create `platforms/common/_manifest.py`:

```python
"""Load a platform's platform.toml into a PlatformManifest (SSOT)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # py3.10
    import tomli as tomllib  # type: ignore


@dataclass
class PlatformManifest:
    id: str
    display_name: str
    port: int
    status: str
    multi_device: bool
    host_os: list[str]
    server_module: str
    setup_script: str
    guidance: list[str]
    options: dict = field(default_factory=dict)        # [install.options]
    config_reuse: dict = field(default_factory=dict)   # [install.config_reuse]
    aliases: dict[str, str] = field(default_factory=dict)  # canonical -> current
    toml_path: Path = field(default=Path("."))

    @property
    def dir(self) -> Path:
        return self.toml_path.parent

    @property
    def server_path(self) -> Path:
        return self.dir / "server" / f"{self.server_module}.py"


def load_manifest(path: str | Path) -> PlatformManifest:
    path = Path(path)
    with path.open("rb") as f:
        data = tomllib.load(f)
    p = data["platform"]
    install = data.get("install", {})
    return PlatformManifest(
        id=p["id"],
        display_name=p["display_name"],
        port=int(p["port"]),
        status=p["status"],
        multi_device=bool(p.get("multi_device", False)),
        host_os=list(p["host_os"]),
        server_module=data["server"]["module"],
        setup_script=install.get("setup_script", ""),
        guidance=list(install.get("guidance", [])),
        options=install.get("options", {}),
        config_reuse=install.get("config_reuse", {}),
        aliases=dict(data.get("tools", {}).get("aliases", {})),
        toml_path=path.resolve(),
    )


def discover_manifests(platforms_dir: str | Path) -> list[PlatformManifest]:
    platforms_dir = Path(platforms_dir)
    return [load_manifest(p) for p in sorted(platforms_dir.glob("*/platform.toml"))]
```

- [ ] **Step 5: Run it — fails differently**

Run: `python -m pytest platforms/tests/test_manifest_loader.py -q`
Expected: FAIL (`FileNotFoundError: .../ios/platform.toml`) — the loader works; the manifest file doesn't exist yet (Task 4 creates it).

- [ ] **Step 6: Commit**

```bash
git add platforms/common/_manifest.py platforms/tests/test_manifest_loader.py cli/pyproject.toml
git commit -m "feat(common): platform.toml loader (_manifest.py)"
```

---

## Task 4: Per-platform manifests (`platform.toml` ×4)

**Files:**
- Create: `platforms/windows/platform.toml`, `platforms/macos/platform.toml`, `platforms/android/platform.toml`, `platforms/ios/platform.toml`

> `[tools.aliases]` maps **canonical → current** for every CORE tool the platform does NOT already implement under its canonical name. Tools already named canonically (e.g. android/ios `tap`, `type_text`, `swipe`, `list_devices`) need no alias entry.

- [ ] **Step 1: Create `platforms/ios/platform.toml`**

```toml
[platform]
id           = "ios-device"
display_name = "iOS / iPadOS"
port         = 8769
status       = "released"
multi_device = true
host_os      = ["macos"]

[server]
module = "ios_device_mcp"

[install]
setup_script = "scripts/setup-ios.sh"
guidance     = ["ios_wda_deploy.yaml"]

[tools.aliases]
# canonical = current  (only where names differ)
acquire     = "acquire_ios"
release     = "release_ios"
get_status  = "get_ios_status"
press_key   = "press_button"   # iOS physical-button mapping
# tap, swipe, type_text, dump_ui->dump_ui_hierarchy, current_app, terminate_app,
# list_devices, set_default_device, get_default_device, get_screen_size, take_screenshot
dump_ui     = "dump_ui_hierarchy"
```

- [ ] **Step 2: Create `platforms/android/platform.toml`**

```toml
[platform]
id           = "android-device"
display_name = "Android"
port         = 8768
status       = "released"
multi_device = true
host_os      = ["windows", "macos", "linux"]

[server]
module = "android_device_mcp"

[install]
setup_script = "scripts/setup-android.sh"
guidance     = ["android_dev_options.yaml", "android_usb_debug.yaml", "android_wireless_pair.yaml"]

[install.config_reuse]
check_path = "~/.atb-android/config.toml"
env        = "ATB_ANDROID_REUSE_CONFIG"

[install.options]
mode = { prompt = "ADB connection mode", choices = ["usb", "wireless", "hybrid"], env = "ATB_ANDROID_MODE" }

[tools.aliases]
acquire        = "acquire_android"
release        = "release_android"
get_status     = "get_android_status"
dump_ui        = "dump_ui_hierarchy"
terminate_app  = "kill_app"
```

- [ ] **Step 3: Create `platforms/macos/platform.toml`**

```toml
[platform]
id           = "mac-device"
display_name = "macOS"
port         = 8767
status       = "released"
multi_device = false
host_os      = ["macos"]

[server]
module = "mac_device_mcp"

[install]
setup_script = "scripts/setup-macos.sh"
guidance     = ["macos_accessibility.yaml", "macos_screen_recording.yaml", "macos_automation.yaml", "macos_full_disk_access.yaml"]

[tools.aliases]
tap                = "click"
acquire            = "acquire_mac"
release            = "release_mac"
get_status         = "get_mac_status"
dump_ui            = "list_ui_elements"
terminate_app      = "kill_process"
# NOTE: single-device CORE tools (list_devices/set_default_device/
# get_default_device/current_app) don't exist on mac yet — added in P1
# (DeviceStateRegistry single-host). Do NOT alias them here; they are tracked in
# Task 5's KNOWN_P1_GAPS so the gate is green now and the gap stays visible.
```

> Verify the macOS guidance filenames against `cli/src/fleet/guidance/` (run `ls cli/src/fleet/guidance/ | grep macos`); use the actual filenames.

- [ ] **Step 4: Create `platforms/windows/platform.toml`**

```toml
[platform]
id           = "win-device"
display_name = "Windows 10/11"
port         = 8766
status       = "released"
multi_device = false
host_os      = ["windows"]

[server]
module = "win_device_mcp"

[install]
setup_script = "scripts/setup-windows.ps1"
guidance     = ["windows_postinstall.yaml"]

[tools.aliases]
tap            = "click"
acquire        = "acquire_winpc"
release        = "release_winpc"
get_status     = "get_winpc_status"
dump_ui        = "inspect_window"
terminate_app  = "kill_process"
```

> Verify `setup_script`/`guidance` names against `platforms/windows/scripts/` and `cli/src/fleet/guidance/`.

- [ ] **Step 5: Run the manifest-loader test — passes**

Run: `python -m pytest platforms/tests/test_manifest_loader.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add platforms/*/platform.toml
git commit -m "feat(platforms): per-platform platform.toml SSOT + canonical alias maps"
```

---

## Task 5: AST conformance test

**Files:**
- Create: `platforms/tests/_ast_tools.py`, `platforms/tests/test_conformance.py`

- [ ] **Step 1: Write the AST extractor helper + its failing test**

Create `platforms/tests/test_ast_tools.py`:

```python
import sys, textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ast_tools import extract_mcp_tools


def test_extracts_bare_and_called_decorator(tmp_path):
    src = textwrap.dedent('''
        @mcp.tool
        def tap(x, y, device=None, ctx=None): ...

        @mcp.tool()
        def type_text(text, device=None): ...

        def not_a_tool(z): ...
    ''')
    f = tmp_path / "s.py"; f.write_text(src)
    tools = extract_mcp_tools(f)
    assert set(tools) == {"tap", "type_text"}
    assert tools["tap"] == ["x", "y", "device", "ctx"]
    assert tools["type_text"] == ["text", "device"]
```

- [ ] **Step 2: Run it — fails**

Run: `python -m pytest platforms/tests/test_ast_tools.py -q`
Expected: FAIL (`ModuleNotFoundError: _ast_tools`).

- [ ] **Step 3: Implement the extractor**

Create `platforms/tests/_ast_tools.py`:

```python
"""Statically extract @mcp.tool function names + param names from a server file.

Never imports the module (win/mac/android servers can't import on Linux CI)."""
from __future__ import annotations

import ast
from pathlib import Path


def _is_mcp_tool(dec: ast.expr) -> bool:
    # matches @mcp.tool and @mcp.tool(...)
    node = dec.func if isinstance(dec, ast.Call) else dec
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "tool"
        and isinstance(node.value, ast.Name)
        and node.value.id == "mcp"
    )


def _param_names(fn: ast.FunctionDef) -> list[str]:
    a = fn.args
    names = [p.arg for p in (a.posonlyargs + a.args + a.kwonlyargs)]
    return names


def extract_mcp_tools(path: str | Path) -> dict[str, list[str]]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(_is_mcp_tool(d) for d in node.decorator_list):
                out[node.name] = _param_names(node)
    return out
```

- [ ] **Step 4: Run it — passes**

Run: `python -m pytest platforms/tests/test_ast_tools.py -q`
Expected: PASS.

- [ ] **Step 5: Write the conformance test**

Create `platforms/tests/test_conformance.py`:

```python
import sys
from pathlib import Path

import pytest

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))                 # platforms/tests (for _ast_tools)
sys.path.insert(0, str(_here.parent))          # platforms/ (for common)
from _ast_tools import extract_mcp_tools
from common import _canonical_tools as ct
from common._manifest import discover_manifests

PLATFORMS_DIR = _here.parent
MANIFESTS = discover_manifests(PLATFORMS_DIR)
IDS = [m.id for m in MANIFESTS]


@pytest.mark.parametrize("m", MANIFESTS, ids=IDS)
def test_core_tools_covered(m):
    tools = extract_mcp_tools(m.server_path)            # {name: [params]}
    missing = []
    for canon, spec in ct.CORE.items():
        impl_name = canon if canon in tools else m.aliases.get(canon)
        if impl_name is None or impl_name not in tools:
            missing.append(canon)
            continue
        # arity: implementing fn must expose >= required (non-optional, non-plumbing) params
        actual = [p for p in tools[impl_name] if p not in ct.ALLOWED_EXTRA]
        if len(actual) < ct.required_arity(spec):
            missing.append(f"{canon} (arity: {impl_name} has {actual}, needs {ct.required_arity(spec)})")
    assert not missing, f"{m.id} missing/under-spec CORE tools: {missing}"


@pytest.mark.parametrize("m", MANIFESTS, ids=IDS)
def test_aliases_point_at_real_tools(m):
    tools = extract_mcp_tools(m.server_path)
    dangling = {canon: cur for canon, cur in m.aliases.items() if cur not in tools}
    assert not dangling, f"{m.id} aliases point at non-existent tools: {dangling}"
```

- [ ] **Step 6: Run it — expect failures that reveal real gaps**

Run: `python -m pytest platforms/tests/test_conformance.py -q`
Expected: FAILs that surface concrete gaps to resolve in this task, e.g.:
- `ios-device missing CORE tools: ['take_screenshot (arity...)']` if Task 7 not yet done → do Task 7, OR if running interleaved, expect this resolved by Task 7.
- `mac-device / win-device missing: ['list_devices','set_default_device','get_default_device','current_app']` — these single-device CORE tools genuinely don't exist on win/mac yet.

- [ ] **Step 7: Resolve the single-device CORE gap for win/mac (P0-minimal)**

win/mac genuinely lack `list_devices`/`set_default_device`/`get_default_device`/`current_app`. Full implementation is P1 (DeviceStateRegistry single-host). For P0, mark these as known-not-yet via an explicit allowlist in the test so the gate is green AND the gap is documented (not silently skipped). Edit `test_conformance.py` `test_core_tools_covered` to consult a `KNOWN_P1_GAPS` map:

```python
# CORE tools whose implementation is scheduled for P1 (single-device platforms).
# Tracked explicitly so the gate is green now but the gap is visible.
KNOWN_P1_GAPS = {
    "win-device": {"list_devices", "set_default_device", "get_default_device", "current_app"},
    "mac-device": {"list_devices", "set_default_device", "get_default_device", "current_app"},
}
```

and in the loop, skip a canonical tool if `canon in KNOWN_P1_GAPS.get(m.id, set())`. Ensure the win/mac `[tools.aliases]` blocks contain **only** entries whose target tool actually exists (do NOT add aliases for the single-device CORE tools — they're covered by `KNOWN_P1_GAPS`, not aliases), so `test_aliases_point_at_real_tools` stays green. Add a `test_known_gaps_shrink()` that asserts `KNOWN_P1_GAPS` only contains exactly these documented entries (a tripwire forcing P1 to delete them once implemented).

- [ ] **Step 8: Run it — green**

Run: `python -m pytest platforms/tests/test_conformance.py -q`
Expected: PASS for all 4 platforms (real coverage via direct names + aliases; single-device gaps explicitly tracked; iOS `take_screenshot` covered after Task 7).

- [ ] **Step 9: Commit**

```bash
git add platforms/tests/_ast_tools.py platforms/tests/test_ast_tools.py platforms/tests/test_conformance.py platforms/windows/platform.toml platforms/macos/platform.toml
git commit -m "feat(tests): AST conformance gate — canonical CORE coverage per platform"
```

---

## Task 6: Manifest invariants test (ports / host_os / version)

**Files:**
- Create: `platforms/tests/test_manifests.py`

- [ ] **Step 1: Write the failing test**

Create `platforms/tests/test_manifests.py`:

```python
import sys
from pathlib import Path

import pytest

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))  # platforms/
from common._manifest import discover_manifests

MANIFESTS = discover_manifests(_here.parent)
VALID_HOST_OS = {"windows", "macos", "linux"}


def test_at_least_four_platforms():
    assert len(MANIFESTS) >= 4


def test_ports_are_unique():
    ports = [m.port for m in MANIFESTS]
    assert len(ports) == len(set(ports)), f"port collision: {ports}"


def test_ports_in_expected_band():
    for m in MANIFESTS:
        assert 8766 <= m.port <= 8799, f"{m.id} port {m.port} out of band"


def test_host_os_values_valid():
    for m in MANIFESTS:
        assert set(m.host_os) <= VALID_HOST_OS, f"{m.id} bad host_os {m.host_os}"
        assert m.host_os, f"{m.id} empty host_os"


def test_status_values_valid():
    for m in MANIFESTS:
        assert m.status in {"released", "beta", "planned"}, f"{m.id} status {m.status}"


def test_setup_script_exists():
    for m in MANIFESTS:
        if m.setup_script:
            assert (m.dir / m.setup_script).exists(), f"{m.id} missing {m.setup_script}"
```

- [ ] **Step 2: Run it**

Run: `python -m pytest platforms/tests/test_manifests.py -q`
Expected: PASS (4 manifests, unique ports 8766-8769, valid host_os/status, setup scripts exist). If `test_setup_script_exists` fails, fix the `setup_script` value in the offending manifest to the real filename.

- [ ] **Step 3: Commit**

```bash
git add platforms/tests/test_manifests.py
git commit -m "feat(tests): manifest invariants — unique ports, valid host_os/status, setup scripts exist"
```

---

## Task 7: iOS `take_screenshot` — add `region` param (CORE signature alignment)

**Files:**
- Modify: `platforms/ios/server/ios_device_mcp.py:399-403`

- [ ] **Step 1: Add the param (accept + ignore for now)**

Change the signature at line 399:

```python
@mcp.tool
def take_screenshot(
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> Image:
    """Capture a PNG screenshot of the device. Returns base64-embedded image."""
```

to:

```python
@mcp.tool
def take_screenshot(
    region: Annotated[list[int] | None, Field(description="[x,y,w,h] crop; None=full screen (crop not yet implemented)")] = None,
    device: Annotated[str | None, Field(description="udid or alias")] = None,
    ctx: Context = None,
) -> Image:
    """Capture a PNG screenshot of the device. Returns base64-embedded image.

    `region` accepted for canonical-contract parity; cropping is not implemented
    yet (full screen always returned). TODO: implement crop via PIL.
    """
```

(Leave the body unchanged — `region` is accepted but unused.)

- [ ] **Step 2: Verify conformance now passes for iOS take_screenshot**

Run: `python -m pytest platforms/tests/test_conformance.py -k ios -q`
Expected: PASS (`take_screenshot` now has `region` → satisfies canonical `take_screenshot(region?)`).

- [ ] **Step 3: Commit**

```bash
git add platforms/ios/server/ios_device_mcp.py
git commit -m "feat(ios): take_screenshot accepts region param (canonical parity; crop TODO)"
```

---

## Task 8: iOS Linux-runnable helper unit tests

**Files:**
- Create: `platforms/ios/server/tests/test_ios_devices.py`

> Scope: only the parts of the iOS bridge that import + run on Linux without a device. `_ios_devices.py` uses `pymobiledevice3` CLI via subprocess; its **parser** (turning CLI/JSON output into `DeviceInfo`) is pure and testable with a mocked subprocess. The WDA HTTP client and tool functions need a device/WDA and are out of P0 scope (covered by real-device runs).

- [ ] **Step 1: Inspect the parse seam**

Run: `grep -n "def \|subprocess\|json.loads\|DeviceInfo(" platforms/ios/server/_ios_devices.py`
Identify the function that parses `pymobiledevice3` output into `DeviceInfo` (e.g. `detect_ios_devices()` and/or an inner `_parse_*`). Note its exact name + how it invokes the CLI (so the test can monkeypatch that boundary).

- [ ] **Step 2: Write the test against the real parse function**

Create `platforms/ios/server/tests/test_ios_devices.py` (adapt the monkeypatch target + sample payload to what Step 1 found):

```python
import sys
from pathlib import Path

_here = Path(__file__).resolve()
sys.path.insert(0, str(_here.parent.parent))            # ios/server
sys.path.insert(0, str(_here.parent.parent.parent.parent))  # platforms/ (common pkg)

import _ios_devices as iod


def test_detect_parses_devices(monkeypatch):
    # Sample mirrors `pymobiledevice3 usbmux list -u` JSON output.
    sample = (
        '[{"Identifier":"00008120-AAA","DeviceName":"iPad",'
        '"ProductType":"iPad15,7","ProductVersion":"26.2.1","DeviceClass":"iPad"}]'
    )
    # Monkeypatch the CLI invocation seam identified in Step 1, e.g.:
    monkeypatch.setattr(iod, "_run_pmd", lambda *a, **k: sample, raising=False)
    devices = iod.detect_ios_devices()
    assert len(devices) == 1
    d = devices[0]
    assert d.serial == "00008120-AAA"
    assert d.brand == "apple"
    assert "iPad15,7" in (d.model or "")
```

> If the real function name / CLI seam differs from `_run_pmd`/`detect_ios_devices`, adjust to match Step 1 (do NOT invent names). If `_ios_devices` cannot be imported standalone on Linux (e.g., it imports `pymobiledevice3` at top level), gate the import with `pytest.importorskip("pymobiledevice3")` and instead unit-test the pure brand/model-slug helper from `common/_aliases.py` here, leaving a `# TODO P1: extract iOS parse seam for testability` note.

- [ ] **Step 3: Run it**

Run: `cd platforms/ios/server && python -m pytest tests/test_ios_devices.py -q`
Expected: PASS (or skipped-with-reason if `pymobiledevice3` isn't importable on the runner — acceptable for P0; the AST conformance test covers the contract regardless).

- [ ] **Step 4: Commit**

```bash
git add platforms/ios/server/tests/test_ios_devices.py
git commit -m "test(ios): Linux-runnable device-parse unit test"
```

---

## Task 9: Wire the new tests into the suite + final green

**Files:**
- Modify: (maybe) `cli/pyproject.toml` or a root pytest config so `platforms/tests/` is collected.

- [ ] **Step 1: Confirm collection**

Run from repo root: `python -m pytest platforms/tests -q`
Expected: all PASS (canonical, manifest-loader, manifests, ast_tools, conformance).

- [ ] **Step 2: Full additive suite green**

Run: `python -m pytest platforms/tests platforms/common/tests platforms/android/server/tests -q`
Expected: all PASS. (win/mac/ios server tests run on their own OS / are import-gated.)

- [ ] **Step 3: Commit any config**

```bash
git add -A
git commit -m "chore(tests): collect platforms/tests in the suite"
```

---

## Definition of Done (P0)

- `platforms/common/` is an importable package; android/ios import `common.*`; existing tests still green.
- `_canonical_tools.py` + `_manifest.py` exist and are tested.
- 4 `platform.toml` files with alias maps; manifest invariants (unique ports, valid host_os/status) tested.
- AST conformance gate green for all 4 platforms (coverage via direct names + aliases; single-device gaps tracked in `KNOWN_P1_GAPS` as a P1 tripwire).
- iOS `take_screenshot` accepts `region`.
- iOS Linux-runnable parse test added (or import-gated with a documented reason).
- No tool renames, no behavior changes to existing platforms (additive only) — `git diff` touches servers only for the 3 import-line changes + the iOS `region` param.
