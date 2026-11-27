#!/usr/bin/env python3
"""Generate and drift-check docs from platform manifests + AST tool counts.

Usage:
    python3 scripts/gen_docs.py --check   # exit 1 if docs are stale
    python3 scripts/gen_docs.py --write   # regenerate docs/architecture.md port table
    python3 scripts/gen_docs.py           # same as --write
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root + path setup (mirror install-agent-side.py)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "platforms"))
sys.path.insert(0, str(REPO_ROOT / "platforms" / "tests"))

from common._manifest import discover_manifests  # noqa: E402
from _ast_tools import extract_mcp_tools          # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HOST_OS_LABEL: dict[str, str] = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
}

# Extra planned rows (no manifest yet)
PLANNED: list[tuple[str, str, int]] = [
    ("HarmonyOS（鸿蒙，规划中）", "任意", 8770),
]

MARK_BEGIN = "<!-- gen:port-table -->"
MARK_END = "<!-- /gen:port-table -->"

ARCHITECTURE_MD = REPO_ROOT / "docs" / "architecture.md"
README_MD = REPO_ROOT / "README.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manifests():
    return discover_manifests(REPO_ROOT / "platforms")


# Optional-capability tool counts come from the capability source (AST-only —
# never import a server). The framework (CapabilityRegistry.setup) registers the
# discovery tool list_capabilities on EVERY server, so it's always-on.
CAP_DIR = REPO_ROOT / "platforms" / "common" / "capabilities"
FRAMEWORK_TOOLS = ["list_capabilities"]

# Capabilities that are opt-in at runtime: their tools are registered only when
# the host opt-in marker exists (human_dom: ~/.fleet/human-dom-ready + per-profile
# extension). list_capabilities() reports them as unavailable (0 tools) until
# then, so counting them here would overstate what a default install exposes.
# Runtime truth stays list_capabilities(); this constant only fixes the doc
# contract (README numbers describe the default install).
OPT_IN_CAPABILITIES = {"human_dom"}

# Capabilities whose tool surface is owned by a third-party backend and can
# change with the installed version (agent_browser proxies @playwright/mcp).
# They are excluded from the stable "fixed tools" contract below; runtime
# list_capabilities() remains the only authority for their real count.
VARIABLE_CAPABILITIES = {"agent_browser"}


def _count_list_literal(path: Path, name: str) -> int:
    """Count elements of a module-level `name = [...]` list literal via AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
            and isinstance(node.value, ast.List)
        ):
            return len(node.value.elts)
    raise RuntimeError(f"{name} list literal not found in {path}")


def capability_tool_count(cap_id: str) -> int:
    """Tools an enabled OPTIONAL capability contributes (static baseline).

    core is counted via the inline server tools; unknown optionals contribute 0
    (add a branch). For agent_browser this is only a baseline list: the real
    surface is introspected from the installed @playwright/mcp at startup, so it
    is excluded from tool_count() (see VARIABLE_CAPABILITIES)."""
    if cap_id == "agent_browser":
        f = CAP_DIR / "browser" / "_agent_browser.py"
        return _count_list_literal(f, "PLAYWRIGHT_TOOLS") + _count_list_literal(f, "_MGMT_TOOLS")
    if cap_id == "human_browser":
        return len(extract_mcp_tools(CAP_DIR / "browser" / "_human_browser.py"))
    if cap_id == "vision":
        return len(extract_mcp_tools(CAP_DIR / "vision" / "_vision.py"))
    if cap_id == "devtools":
        # Registered inside DevtoolsCapability.register(); ast.walk finds them.
        return len(extract_mcp_tools(CAP_DIR / "devtools" / "_devtools.py"))
    if cap_id == "human_dom":
        # Registered inside HumanDomCapability.register(); ast.walk still finds them.
        return len(extract_mcp_tools(CAP_DIR / "human_dom" / "_human_dom.py"))
    return 0


def tool_count(m) -> int:
    """FIXED tool count a platform exposes on a default install.

    "Fixed" = inline core (@mcp.tool in the server) + framework discovery
    tool(s) + optional capabilities whose surface this repo controls. Excluded
    on purpose: opt-in capabilities (human_dom: adds tools only after the host
    marker exists) and variable capabilities (agent_browser: proxies a
    third-party @playwright/mcp whose version decides the tool list). Count
    those from the runtime list_capabilities() — never from a static number."""
    core = len(extract_mcp_tools(m.server_path))
    enabled = list((getattr(m, "capabilities", None) or {}).get("enabled") or ["core"])
    optional = sum(
        capability_tool_count(c)
        for c in enabled
        if c != "core"
        and c not in OPT_IN_CAPABILITIES
        and c not in VARIABLE_CAPABILITIES
    )
    return core + len(FRAMEWORK_TOOLS) + optional


def host_label(m) -> str:
    return " / ".join(HOST_OS_LABEL.get(o, o) for o in m.host_os)


# ---------------------------------------------------------------------------
# Port table rendering
# ---------------------------------------------------------------------------

def render_port_table() -> str:
    """Return a markdown table string (no surrounding markers).

    Columns: 平台 | 设备主机 OS | 端口
    Rows: one per manifest sorted by port, then PLANNED rows.
    """
    lines = [
        "| 平台 | 设备主机 OS | 端口 |",
        "|---|---|---|",
    ]
    manifests = sorted(_manifests(), key=lambda m: m.port)
    for m in manifests:
        lines.append(f"| {m.display_name} | {host_label(m)} | {m.port} |")
    for display, host, port in PLANNED:
        lines.append(f"| {display} | {host} | {port} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# architecture.md writer
# ---------------------------------------------------------------------------

def write_architecture() -> bool:
    """Replace the text between gen:port-table markers in docs/architecture.md.

    Returns True if the file changed, False if it was already up-to-date.
    Raises RuntimeError if markers are absent.
    """
    text = ARCHITECTURE_MD.read_text(encoding="utf-8")
    if MARK_BEGIN not in text or MARK_END not in text:
        raise RuntimeError(
            f"Markers {MARK_BEGIN!r} / {MARK_END!r} not found in {ARCHITECTURE_MD}.\n"
            "Task 2 adds them — run Task 2 first, or add them manually."
        )
    table = render_port_table()
    new_region = f"\n{table}\n"
    # Replace everything between the two markers (inclusive of content, not the markers)
    pattern = re.compile(
        re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END),
        re.DOTALL,
    )
    new_text = pattern.sub(MARK_BEGIN + new_region + MARK_END, text)
    if new_text == text:
        return False
    ARCHITECTURE_MD.write_text(new_text, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# README tool-count check
# ---------------------------------------------------------------------------

def check_readme_counts() -> list[str]:
    """Return mismatch messages (empty = all good).

    README must state the FIXED count ("<n> fixed tools" or "<n> tools").
    Variable-surface capabilities (agent_browser) are documented as
    runtime-only, so they never appear in this number.
    """
    text = README_MD.read_text(encoding="utf-8")
    messages: list[str] = []
    for m in _manifests():
        pattern = re.compile(
            rf"{re.escape(m.id)}[^|\n]*?(\d+)\s*(?:fixed\s+)?(?:\*\*\s*)?tools",
        )
        match = pattern.search(text)
        n = tool_count(m)
        if match:
            found = int(match.group(1))
            if found != n:
                messages.append(
                    f"{m.id}: README says {found} tools, AST has {n}"
                )
        else:
            messages.append(f"could not find count for {m.id} in README.md")
    return messages


# ---------------------------------------------------------------------------
# CHANGELOG structure (仅约束 [Unreleased])
# ---------------------------------------------------------------------------
#
# 这条约束是"追着跑"追出来的：同一个 `### 新增` 小节被重复追加过两次（一次在合并分支、
# 一次在后续提交），发版时要手工合并。只在 [Unreleased] 范围内管，历史段落不动。

CHANGELOG_MD = REPO_ROOT / "CHANGELOG.md"


def changelog_unreleased(text: str) -> str:
    """取出 `## [Unreleased]` 到下一个 `## [` 之间的内容（没有则返回空串）。"""
    start = re.search(r"^## \[Unreleased\]", text, re.M)
    if not start:
        return ""
    rest = text[start.end():]
    end = re.search(r"^## \[", rest, re.M)
    return rest[:end.start()] if end else rest


def duplicate_subsection_headings(section: str) -> list[str]:
    """返回重复出现的小节标题（`### xxx`），保持首次出现顺序。"""
    headings = re.findall(r"^### (.+)$", section, re.M)
    seen: list[str] = []
    dupes: list[str] = []
    for h in headings:
        if h in seen and h not in dupes:
            dupes.append(h)
        else:
            seen.append(h)
    return dupes


def check_changelog_structure() -> list[str]:
    """`[Unreleased]` 下同类小节只能有一个（否则发版时必然要手工合并且容易漏）。"""
    if not CHANGELOG_MD.is_file():
        return []
    section = changelog_unreleased(CHANGELOG_MD.read_text(encoding="utf-8"))
    dupes = duplicate_subsection_headings(section)
    return [f"CHANGELOG.md: [Unreleased] 下重复的小节标题 {dupes!r}（同类条目请合并到同一节）"
            for _ in dupes]


# ---------------------------------------------------------------------------
# Platform README / setup-guide tool counts
# ---------------------------------------------------------------------------
#
# `check_readme_counts()` only guarded the repo-root README. That let a real drift
# through once: the root README matched while `platforms/<p>/README.md` and
# `docs/platforms/<p>.md` still said the old number (gen_docs stayed green).
# These two files are exactly what a reviewer reads when they open a platform, so
# they get the same treatment as the root README.

#: platform id -> setup guide under docs/platforms/ (they predate the manifest ids).
SETUP_GUIDE_BY_ID = {
    "win-device": "windows.md",
    "mac-device": "macos.md",
    "android-device": "android.md",
    "ios-device": "ios.md",
}

_FIXED_COUNT_RE = re.compile(r"固定工具数\s*\**\s*(\d+)")
_CORE_COUNT_RE = re.compile(r"除上面\s*(\d+)\s*个 core 工具外")
_APPENDIX_CORE_RE = re.compile(r"core 工具（(\d+)\s*个）")


def _count_docs_for(m) -> list[Path]:
    docs = [m.dir / "README.md"]
    guide = SETUP_GUIDE_BY_ID.get(m.id)
    if guide:
        docs.append(REPO_ROOT / "docs" / "platforms" / guide)
    return docs


def check_platform_doc_counts() -> list[str]:
    """Every platform README / setup guide must state the counts derived from code."""
    messages: list[str] = []
    for m in _manifests():
        expected_total = tool_count(m)
        expected_core = len(extract_mcp_tools(m.server_path))
        for path in _count_docs_for(m):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(REPO_ROOT)
            for found in _FIXED_COUNT_RE.findall(text):
                if int(found) != expected_total:
                    messages.append(f"{rel}: says 固定工具数 {found}, code says {expected_total}")
            for found in _CORE_COUNT_RE.findall(text):
                if int(found) != expected_core:
                    messages.append(f"{rel}: says 除上面 {found} 个 core 工具, code has {expected_core}")
            for found in _APPENDIX_CORE_RE.findall(text):
                if int(found) != expected_core:
                    messages.append(f"{rel}: 附录 A 标题写 core {found} 个, code has {expected_core}")
    return messages


# ---------------------------------------------------------------------------
# Architecture port-table staleness check
# ---------------------------------------------------------------------------

def check_architecture_table() -> list[str]:
    """Return mismatch messages if the marked region is absent or stale."""
    text = ARCHITECTURE_MD.read_text(encoding="utf-8")
    if MARK_BEGIN not in text or MARK_END not in text:
        return [
            f"docs/architecture.md: port-table markers absent "
            f"({MARK_BEGIN!r} / {MARK_END!r}); run --write after Task 2 adds them"
        ]
    pattern = re.compile(
        re.escape(MARK_BEGIN) + r"(.*?)" + re.escape(MARK_END),
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return ["docs/architecture.md: could not extract marked region"]
    current_content = match.group(1)
    expected_content = f"\n{render_port_table()}\n"
    if current_content != expected_content:
        return [
            "docs/architecture.md: port table is stale — run `gen_docs.py --write` to regenerate"
        ]
    return []


# ---------------------------------------------------------------------------
# Public check / write entry-points
# ---------------------------------------------------------------------------

def check() -> int:
    """Run all checks. Print messages, return 1 if any mismatch else 0."""
    messages: list[str] = []
    messages.extend(check_readme_counts())
    messages.extend(check_platform_doc_counts())
    messages.extend(check_architecture_table())
    messages.extend(check_changelog_structure())
    for msg in messages:
        print(msg)
    return 1 if messages else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true",
                       help="Check docs for drift; exit 1 if stale")
    group.add_argument("--write", action="store_true",
                       help="Regenerate docs/architecture.md port table (default action)")
    args = parser.parse_args()

    if args.check:
        sys.exit(check())
    else:
        # --write or default
        try:
            changed = write_architecture()
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        if changed:
            print(f"Updated {ARCHITECTURE_MD}")
        else:
            print(f"No change — {ARCHITECTURE_MD} already up-to-date")


if __name__ == "__main__":
    main()
