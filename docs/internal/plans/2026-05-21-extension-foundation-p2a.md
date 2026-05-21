# Extension Foundation — P2a (manifest-driven CLI: auto-discovery + de-hardcode) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (fresh subagent per task + two-stage review). Steps use checkbox (`- [ ]`). All Linux-testable (`cli/` has no GUI deps).

**Goal:** Make the installer registry build itself by scanning `platforms/*/platform.toml`, and remove android-specific hardcoding — so adding a platform needs **zero edits to `INSTALLER_REGISTRY` or the CLI's option/env code**. (P2b, separate plan, does `gen-docs.py`.)

**Architecture:** A generic `ManifestInstaller(BaseInstaller)` is constructed per `(manifest, host_os)` and reads role_id/display_name/port/guidance/host_os/setup-script from the `PlatformManifest`; platform-specific `preflight`/`smoke_tests` come from an optional per-role **hooks** table (keyed by role_id) rather than per-platform subclasses. `INSTALLER_REGISTRY` becomes `discover_installers()` (scan manifests × their host_os, attach hooks). The android-specific `InstallContext` fields + `_select_android_config()` + `_env.py` android branch are replaced by a generic `platform_options: dict[str,str]` driven by manifest `[install.options]` + `[install.config_reuse]`.

**Tech Stack:** Python 3.11, `cli/` (questionary/pyyaml/rich/httpx/mcp), `platforms/common/_manifest.py` (P0 loader). Run tests with `PYTHONPATH=src` from `cli/`.

**Source:** design §支柱5 + §五P2 + §九; code-explorer map (file:line refs below).

**Baseline:** `cd cli && PYTHONPATH=src python -m pytest -q` → **95 passed, 1 pre-existing fail** (`test_smoke_module.py::test_has_device_in_result_rejects_unauthorized` — unrelated to P2; do NOT count it as a regression, but do NOT break the other 95).

---

## File map

**Modify**
- `platforms/common/_manifest.py` — add `setup_script_by_os: dict[str,str]` to `PlatformManifest` + load `[install.setup_script_by_os]`; helper `setup_script_for(host_os) -> str`.
- `platforms/android/platform.toml` — add `[install.setup_script_by_os]` (windows→setup-android.ps1, linux→setup-android-linux.sh; macos uses the default `setup_script`).
- `cli/src/fleet/types.py:48-55` — drop `android_mode`/`android_reuse_config`; add `platform_options: dict[str,str] = field(default_factory=dict)`.
- `cli/src/fleet/installers/base.py` — add a `collect_options(ctx)`/`preflight`/`smoke_tests` extension surface if not already present (read current ABC first).
- `cli/src/fleet/installers/__init__.py:9-16` — replace the manual `INSTALLER_REGISTRY` list with `discover_installers()` (+ keep `INSTALLER_REGISTRY = discover_installers()` for back-compat consumers).
- `cli/src/fleet/installers/_env.py:24-28` — replace android branch with generic `for k,v in ctx.platform_options.items(): env[k]=v`.
- `cli/src/fleet/cli.py` — delete `_select_android_config()` (74-103); replace android option-collection (312-328) with a generic loop over the selected roles' manifest options; drop the android smoke-fail special branch (206-208) or generalize to a manifest hint.
- `cli/src/fleet/wizard.py:12,20-21` — drop the android params from `build_install_context()`; thread `platform_options`.
- `cli/tests/` — update `test_types.py`, `test_wizard.py`, `test_installers_registry.py`, `test_cli_smoke.py`, and the per-OS installer tests for the new shapes; add tests for `ManifestInstaller` + `discover_installers` + generic option collection.

**Create**
- `cli/src/fleet/installers/_manifest_installer.py` — `ManifestInstaller(BaseInstaller)`.
- `cli/src/fleet/installers/_hooks.py` — per-role `preflight`/`smoke_tests` hook registry (wires the existing `_android_bridge_smoke_tests`/`_ios_bridge_smoke_tests` + the mac/ios preflight + win/mac desktop smoke).

> **Read before editing:** `cli/src/fleet/installers/base.py` (the `BaseInstaller` ABC — its exact abstract methods + `InstallEvent` shape), one full existing installer (e.g. `cli/src/fleet/installers/macos.py` `MacosDesktop` + `MacosIosBridge`) to see preflight/smoke/install/guidance signatures, and `_env.py`/`cli.py`/`wizard.py` at the cited lines. The hooks must reproduce the EXACT current preflight/smoke behavior per platform (this is a refactor — no behavior change to install/verify/smoke).

---

## Task 1: Manifest per-host-OS setup script (SSOT for the 3 android scripts)

**Files:** `platforms/common/_manifest.py`, `platforms/android/platform.toml`; test `platforms/tests/test_manifest_loader.py`.

- [ ] **Step 1: Failing test.** In `platforms/tests/test_manifest_loader.py` add a test (using the existing `tmp_path` `_write` helper pattern) that a manifest with `[install.setup_script_by_os]` loads into `m.setup_script_by_os` and `m.setup_script_for("windows")` returns the windows entry while `m.setup_script_for("macos")` falls back to `m.setup_script`.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3: Implement.** Add to `PlatformManifest`: `setup_script_by_os: dict[str, str] = field(default_factory=dict)` and:
```python
    def setup_script_for(self, host_os: str) -> str:
        return self.setup_script_by_os.get(host_os, self.setup_script)
```
In `load_manifest`, read `setup_script_by_os=dict(install.get("setup_script_by_os", {}))`.
- [ ] **Step 4:** Add to `platforms/android/platform.toml`:
```toml
[install.setup_script_by_os]
windows = "scripts/setup-android.ps1"
linux   = "scripts/setup-android-linux.sh"
# macos falls back to the default setup_script (scripts/setup-android.sh)
```
Verify those two script files exist (`platforms/android/scripts/setup-android.ps1`, `setup-android-linux.sh` — both confirmed present in the explorer map).
- [ ] **Step 5:** Run loader + manifests + conformance tests green. Commit `feat(manifest): per-host-OS setup_script_by_os (android's 3 scripts)`.

---

## Task 2: `ManifestInstaller` + per-role hooks

**Files:** create `cli/src/fleet/installers/_manifest_installer.py`, `cli/src/fleet/installers/_hooks.py`; test `cli/tests/test_manifest_installer.py`.

- [ ] **Step 1:** Read `base.py` (the ABC) + `macos.py`/`windows.py`/`linux.py` to learn the exact `BaseInstaller` interface (`role_id`, `display_name`, `port`, `is_supported_on(os_info)`, `preflight(ctx)`, `install(ctx)` generator yielding `InstallEvent`, `verify()`, `guidance_steps()`, `smoke_tests(...)` — confirm real names/signatures).
- [ ] **Step 2: Failing test** (`cli/tests/test_manifest_installer.py`): construct `ManifestInstaller(manifest=<loaded android manifest>, host_os="linux")` and assert `role_id=="android-device"`, `port==8768`, `is_supported_on` true for linux / false for an unsupported OS, `guidance_steps()` loads the manifest's guidance yamls, and a `dry_run` `install()` references `setup-android-linux.sh`. Assert `collect_options()` reads android's `[install.options].mode` + `[install.config_reuse]`.
- [ ] **Step 3: Implement `ManifestInstaller`.** Constructor `(manifest: PlatformManifest, host_os: str, preflight_hook=None, smoke_hook=None)`. Map: `role_id=manifest.id`, `display_name=manifest.display_name`, `port=manifest.port`; `is_supported_on` ← `host_os in manifest.host_os` (matched against `os_info`); `install()` runs `manifest.setup_script_for(host_os)` via the host-OS-appropriate shell (windows → the existing PowerShell wrapper used by `windows.py`; else bash) — REUSE the existing run helpers (`_run_setup_ps1` / the bash runner) rather than reimplementing; `guidance_steps()` ← load each `manifest.guidance` yaml via `load_guidance_yaml`; `preflight()`/`smoke_tests()` ← delegate to the hooks if provided else `[]`; add `collect_options(ctx) -> dict[str,str]` that walks `manifest.config_reuse` (if `check_path` exists → ask reuse → set env var true/false) + `manifest.options` (prompt + choices → set env var) and returns the env-var→value dict.
- [ ] **Step 4: Implement `_hooks.py`** — a `dict[str, RoleHooks]` keyed by role_id wiring the EXISTING platform-specific logic: `mac-device`→preflight(brew check from `macos.py` MacosDesktop) + its smoke; `ios-device`→preflight(brew+python@3.12+Xcode from MacosIosBridge) + `_ios_bridge_smoke_tests`; `android-device`→`_android_bridge_smoke_tests`; `win-device`→its smoke. Move/import the existing functions; do NOT rewrite their logic.
- [ ] **Step 5:** Run → pass. Commit `feat(cli): ManifestInstaller + per-role preflight/smoke hooks`.

---

## Task 3: Auto-discovery registry

**Files:** `cli/src/fleet/installers/__init__.py`; test `cli/tests/test_installers_registry.py`.

- [ ] **Step 1: Update the registry test** to assert `discover_installers()` yields one installer per (manifest, host_os) — i.e. android on {windows,macos,linux}, ios on {macos}, mac on {macos}, win on {windows} — covering the full set incl. `MacosIosBridge`-equivalent (the old test omitted it). Assert `filter_for_os(...)` still works.
- [ ] **Step 2: Implement** `discover_installers(platforms_dir=...) -> list[BaseInstaller]`: for each `m in discover_manifests(platforms_dir)`, for each `host_os in m.host_os`, build `ManifestInstaller(m, host_os, **_HOOKS.get(m.id, {}))`. Set `INSTALLER_REGISTRY = discover_installers()` (module-level, back-compat). Delete the manual list + the now-unused per-platform installer classes (`MacosDesktop`/`MacosAndroidBridge`/`MacosIosBridge`/`WindowsDesktop`/`WindowsAndroidBridge`/`LinuxAndroidBridge`) — OR keep their files only if `_hooks.py` imports specific helpers from them (prefer moving helpers into `_hooks.py`/`_android.py`/`_ios.py` and deleting the classes).
- [ ] **Step 3:** Run → pass (registry has all expected role×os combos). Commit `feat(cli): auto-discover INSTALLER_REGISTRY from platform.toml manifests`.

---

## Task 4: Generic `platform_options` + `config_reuse` (de-android-hardcode)

**Files:** `cli/src/fleet/types.py`, `cli/src/fleet/installers/_env.py`, `cli/src/fleet/cli.py`, `cli/src/fleet/wizard.py`; tests `test_types.py`, `test_wizard.py`, `test_cli_smoke.py`.

- [ ] **Step 1: Update tests first** for the new shapes: `InstallContext` has `platform_options: dict[str,str]` (no android fields); `build_install_context()` takes `platform_options` not the android params; `_env.py` injects each `platform_options` k→v into env.
- [ ] **Step 2: types.py** — drop `android_mode`/`android_reuse_config` (lines 54-55), add `platform_options: dict[str, str] = field(default_factory=dict)`.
- [ ] **Step 3: _env.py** (24-28) — replace the android branch with `for k, v in ctx.platform_options.items(): env[k] = v` (keys are the manifest-declared env names, e.g. `ATB_ANDROID_MODE`/`ATB_ANDROID_REUSE_CONFIG`). Keep the generic `ATB_WIZARD_MANAGED=1`.
- [ ] **Step 4: cli.py** — delete `_select_android_config()` (74-103). In `cmd_setup` (312-328): replace the android-conditional collection with a generic loop: for each selected role, call its installer's `collect_options(ctx)` and merge into `platform_options`. Remove the android smoke-fail branch (206-208) or replace with a generic service hint. Pass `platform_options` (not android params) to `build_install_context`.
- [ ] **Step 5: wizard.py** (12,20-21) — `build_install_context()` signature: drop android params, accept `platform_options: dict[str,str] | None = None`; thread into `InstallContext`.
- [ ] **Step 6:** Run the FULL cli suite (`cd cli && PYTHONPATH=src python -m pytest -q`) → the 95 (minus any intentionally-changed tests, which you updated) green; the 1 pre-existing failure may remain (note it). Commit `refactor(cli): generic platform_options/config_reuse — drop android-specific fields/branches`.

---

## Task 5: Full suite green + dead-code sweep

- [ ] **Step 1:** `cd cli && PYTHONPATH=src python -m pytest -q` — all green except the 1 documented pre-existing failure. Grep for any remaining `android_mode`/`android_reuse_config`/`_select_android_config` references (should be zero). Grep for now-unused imports in the touched files.
- [ ] **Step 2:** Confirm `python -m pytest platforms/tests -q` (23) + `(cd platforms/common && python -m pytest -q)` still green (manifest loader change).
- [ ] **Step 3:** Final review + commit any cleanup.

---

## Definition of Done (P2a)

- `INSTALLER_REGISTRY` is `discover_installers()` — built by scanning manifests × host_os; adding a platform needs no edit here. All role×os combos present (incl. the previously-omitted ios-on-macos).
- `ManifestInstaller` reads port/script/guidance/host_os/options from the manifest; platform-specific preflight/smoke come from the `_hooks` table; install/verify/smoke behavior unchanged vs the old per-platform installers.
- Android's 3 setup scripts are SSOT'd via `[install.setup_script_by_os]`.
- `InstallContext` has generic `platform_options`; no `android_mode`/`android_reuse_config`; `_select_android_config()` deleted; `_env.py` injects options generically.
- `cd cli && PYTHONPATH=src python -m pytest -q` green except the 1 documented pre-existing failure; no regression in the 95; `platforms/` suites still green.
- No leftover android-specific branches/fields/functions in `cli.py`/`_env.py`/`types.py`/`wizard.py`.

## Out of scope (P2b, separate)
`scripts/gen-docs.py` (generate 9-lang README status tables + architecture port table from manifests + AST tool counts) + its up-to-date CI check. Also: fixing the pre-existing `test_has_device_in_result_rejects_unauthorized` failure (unrelated).
