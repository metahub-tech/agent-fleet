#!/usr/bin/env python3
"""Generate and drift-check docs from platform manifests + AST tool counts.

Usage:
    python3 scripts/gen_docs.py --check   # exit 1 if docs are stale
    python3 scripts/gen_docs.py --write   # regenerate docs/architecture.md port table
    python3 scripts/gen_docs.py           # same as --write
"""
from __future__ import annotations

import argparse
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


def tool_count(m) -> int:
    return len(extract_mcp_tools(m.server_path))


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
    """Return a list of mismatch messages (empty = all good)."""
    text = README_MD.read_text(encoding="utf-8")
    messages: list[str] = []
    for m in _manifests():
        pattern = re.compile(
            rf"{re.escape(m.id)}[^|\n]*?(\d+)\s*(?:\*\*\s*)?tools",
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
    messages.extend(check_architecture_table())
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
