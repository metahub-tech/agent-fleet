# Extension Foundation — P2b (gen-docs: drift check + port-table generation) Plan

> **For agentic workers:** superpowers:subagent-driven-development (fresh subagent per task + two-stage review). Linux-testable.

**Goal:** A `scripts/gen-docs.py` that (1) **checks** the manifest/AST-derived facts echoed in the docs stay consistent — per-server `@mcp.tool` counts vs the README's stated counts, and ports — failing (CI gate) on drift; and (2) **generates** the `docs/architecture.md` port table from the manifests (between codegen markers). It does NOT regenerate the curated, per-language README changelog tables (those are human prose). Also: fix the README tool counts that drifted when P1b added 5 tools each to win/mac (win 33→**38**, mac 34→**39**; android **25**/ios **26** unchanged).

**Architecture:** `gen-docs.py` reuses `platforms/common/_manifest.discover_manifests` + `platforms/tests/_ast_tools.extract_mcp_tools`. The architecture port table is generated as `| 平台 | 设备主机 OS | 端口 |` from each manifest's `display_name` + `host_os` (rendered to a label) + `port`, plus a small `PLANNED` constant for HarmonyOS (no manifest yet), wrapped in `<!-- gen:port-table -->` / `<!-- /gen:port-table -->` markers (curated prose stays outside). The tool-count check parses the **English** `README.md` (canonical, robust) — the 8 translations get their numbers fixed but aren't continuously parsed (localized formats differ).

**Tech Stack:** Python 3.11 stdlib + `tomllib`; `_manifest.py` + `_ast_tools.py`. Run: `python3 scripts/gen-docs.py --check`.

**Source:** design §支柱5 + §五P2 + §六/§八; user decision (2026-05-21): "drift check + generate port table" (NOT regenerate the curated 9-lang README tables).

**Current facts (verified):** AST tool counts — win-device **38**, mac-device **39**, android-device **25**, ios-device **26**. README.md states 33/34/25/26 → win/mac STALE. Ports 8766/8767/8768/8769.

---

## Task 1: `scripts/gen-docs.py` (generate port table + --check)

**Files:** Create `scripts/gen-docs.py`; test `scripts/tests/__init__.py` + `scripts/tests/test_gen_docs.py`.

- [ ] **Step 1: Read** `scripts/install-agent-side.py` (how it finds repo root + imports manifest logic — mirror its path setup), `platforms/common/_manifest.py` (`discover_manifests`, `PlatformManifest.server_path`/`display_name`/`host_os`/`port`), `platforms/tests/_ast_tools.py` (`extract_mcp_tools`), and `docs/architecture.md` lines ~56-66 (the port table) + `README.md` lines ~43-52 (the status table with the `(role_id, N tools, …)` prose).

> **Module name:** use `scripts/gen_docs.py` (underscore — importable + testable). First `grep -rn "gen-docs\|gen_docs" .` to confirm nothing already references a hyphen name; if something does, add a thin `scripts/gen-docs.py` shim. Otherwise just use `gen_docs.py`.

- [ ] **Step 2: Failing test** `scripts/tests/__init__.py` (empty) + `scripts/tests/test_gen_docs.py`:
```python
import subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import gen_docs


def test_render_port_table_contains_all_manifest_ports():
    table = gen_docs.render_port_table()
    for port in (8766, 8767, 8768, 8769):
        assert str(port) in table
    assert "8770" in table  # HarmonyOS planned row


def test_check_passes_on_fresh_docs():
    # After Task 2 fixes counts + writes the table, --check must exit 0.
    r = subprocess.run([sys.executable, "scripts/gen_docs.py", "--check"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
```
(`test_check_passes_on_fresh_docs` will fail until Task 2 fixes the counts + writes the table — that's expected; `test_render_port_table_contains_all_manifest_ports` should pass once Step 3 implements `render_port_table`.)

- [ ] **Step 3: Implement `scripts/gen_docs.py`** with:
  - Repo-root + manifest discovery (mirror install-agent-side.py). `tool_count(m) = len(extract_mcp_tools(m.server_path))` (insert `platforms/tests` on path for `_ast_tools`).
  - `HOST_OS_LABEL = {"windows":"Windows","macos":"macOS","linux":"Linux"}`; `host_label(m) = " / ".join(HOST_OS_LABEL[o] for o in m.host_os)`.
  - `PLANNED = [("HarmonyOS（鸿蒙，规划中）", "任意", 8770)]` (rendered after manifest rows).
  - `render_port_table()` → markdown `| 平台 | 设备主机 OS | 端口 |` header + one row per manifest (sorted by port): `| {display_name} | {host_label} | {port} |`, then the PLANNED rows. Returns the string (no surrounding markers).
  - `MARK_BEGIN="<!-- gen:port-table -->"`, `MARK_END="<!-- /gen:port-table -->"`. `write_architecture()` replaces the text between the markers in `docs/architecture.md` with `\n{table}\n`. Error clearly if markers absent.
  - **README tool-count check** `check_readme_counts()`: read `README.md`; for each manifest, find the line containing its `role_id`, extract the integer immediately preceding `tools` (regex e.g. `rf"{role_id}[^|\n]*?(\d+)\s*(?:\*\*\s*)?tools"`), compare to `tool_count(m)`. Collect mismatches.
  - **port check** `check_ports()`: the generated table is the SSOT; `--check` regenerates the table and diffs against the file's current marked region (stale → fail). (This covers ports.)
  - CLI: `--check` → run check_readme_counts + verify architecture marked-region == render_port_table(); print mismatches; exit 1 if any, else 0. Default / `--write` → write the architecture table region; print what changed.
  - Keep it stdlib-only, no external deps.

- [ ] **Step 4:** Run `python3 scripts/gen_docs.py --check` — EXPECT it to FAIL now (win/mac README counts are 33/34 but AST is 38/39; and architecture.md has no markers yet). Confirm the failure message names win-device 33≠38 + mac-device 34≠39. (Task 2 makes it pass.)

- [ ] **Step 5: Commit** `feat(scripts): gen-docs.py — port-table generation + tool-count/port drift --check`.

---

## Task 2: Wire it in — markers, fix stale counts, test green

**Files:** `docs/architecture.md`, all 9 `README*.md` (win/mac counts only), `scripts/tests/test_gen_docs.py` (un-skip).

- [ ] **Step 1: Add markers to `docs/architecture.md`.** Wrap the existing port table's data rows with `<!-- gen:port-table -->` (before the header `| 平台 |…`) and `<!-- /gen:port-table -->` (after the last data row). Note the current table has a 驱动栈 column + HarmonyOS row; the generated table is `| 平台 | 设备主机 OS | 端口 |` (driver detail already lives in architecture's "原生驱动" / Segment-3 section — leave that section untouched). Then run `python3 scripts/gen_docs.py --write` to replace the marked region with the generated table. Verify the result reads correctly (4 manifest rows by port + the HarmonyOS planned row).

- [ ] **Step 2: Fix the drifted tool counts in all 9 READMEs.** In `README.md` + `README.{zh-CN,ja,ko,es,fr,de,pt-BR,ru}.md`, update the win-device count 33→**38** and mac-device count 34→**39** in the status-table rows (localized: e.g. en "33 tools"→"38 tools", ja "33 ツール"→"38 ツール", zh "33 ..."→"38 ...", etc.). Leave android (25) + ios (26) as-is. Touch ONLY those two numbers per file; do not alter other prose. (Grep each file for the win/mac row to find the exact token.)

- [ ] **Step 3: `--check` green.** `python3 scripts/gen_docs.py --check` → exit 0 (English counts now 38/39 match AST; architecture table fresh). Un-skip/enable the `test_check_passes_on_fresh_docs` test.

- [ ] **Step 4: Run the test + the broader suites.**
```bash
python3 -m pytest scripts/tests -q                 # gen-docs test green
python3 -m pytest platforms/tests -q               # 24 unaffected
```

- [ ] **Step 5:** Sanity — `git diff` shows: new `scripts/gen_docs.py` + tests, architecture.md (markers + regenerated table), 9 READMEs (only the win/mac numbers changed). Commit `feat(docs): generate architecture port table + fix win/mac tool counts (38/39) drifted by P1b; wire gen-docs --check test`.

---

## Definition of Done (P2b)
- `scripts/gen_docs.py --check` exits 0 on fresh docs, non-zero on drift (tool count or port), with a clear message naming the mismatch.
- `docs/architecture.md` port table is generated from manifests between codegen markers (`--write` regenerates it); adding a platform + re-running `--write` updates it with no manual table editing.
- README win/mac tool counts corrected to 38/39 across all 9 languages; android 25 / ios 26 unchanged.
- A test runs `--check` as the CI gate; `platforms/tests` unaffected.
- Curated per-language README changelog tables are NOT mechanically regenerated (only the win/mac integers fixed).

## Out of scope
Continuous parsing of the 8 non-English READMEs' counts (English is the checked canonical); putting driver_stack/host descriptions in manifests; fixing the pre-existing `test_has_device_in_result_rejects_unauthorized` cli failure; the `install-agent-side.py` manual PLATFORM dict (separate concern).
