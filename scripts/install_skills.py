#!/usr/bin/env python3
"""Install agent-fleet skills into an agent's skill directory (skill-only, no config writes).

This is the skill-only counterpart of scripts/install-agent-side.py: it never
touches ~/.claude.json, so it works for any MCP client (Claude Code, DeepSeek
Harness, ...). It links (or copies) the skills that belong to one device role:

    device usage      platforms/<platform>/skills/using-<short>
    human browser     platforms/common/skills/using-human-browser   (win/mac)
    human DOM         platforms/common/skills/using-human-dom       (win/mac)
    OCR locator       platforms/<platform>/skills/using-vision      (win/mac)
    agent browser     platforms/common/skills/using-fleet-browser   (opt-in)

Usage:
    python3 scripts/install-skills.py --platform win-device
    python3 scripts/install-skills.py --platform mac-device --target ~/.claude/skills
    python3 scripts/install-skills.py --platform android-device --dry-run
    python3 scripts/install-skills.py --list

Target defaults, in order: $FLEET_SKILLS_DIR, <repo>/.dsh/skills when it already
exists, ~/.dsh/skills, ~/.claude/skills. Pass --target to be explicit.

Idempotent: an existing symlink is repointed when it is stale; an existing real
directory or file is left alone unless --force. On Windows, symlink creation can
fail without Developer Mode / admin, so the default mode auto-falls back to a
real copy (re-run with --force after pulling to refresh a copy).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# platform id -> (repo dir, device skill name, supports browser/human_dom/vision)
PLATFORMS = {
    "win-device": {"dir": "windows", "skill": "using-win", "browser": True},
    "mac-device": {"dir": "macos", "skill": "using-mac", "browser": True},
    "android-device": {"dir": "android", "skill": "using-android", "browser": False},
    "ios-device": {"dir": "ios", "skill": "using-ios", "browser": False},
}

COMMON_SKILLS_DIR = REPO_ROOT / "platforms" / "common" / "skills"


def default_target() -> Path:
    override = os.environ.get("FLEET_SKILLS_DIR")
    if override:
        return Path(override).expanduser()
    project_local = REPO_ROOT / ".dsh" / "skills"
    if project_local.is_dir():
        return project_local
    dsh_home = Path(os.environ.get("DSH_HOME", "~/.dsh")).expanduser() / "skills"
    if dsh_home.is_dir():
        return dsh_home
    return Path.home() / ".dsh" / "skills"


def plan(platform: str, with_agent_browser: bool) -> list[tuple[str, Path]]:
    """(skill name, source dir) pairs for one platform role, in install order."""
    spec = PLATFORMS[platform]
    items: list[tuple[str, Path]] = [(spec["skill"], REPO_ROOT / "platforms" / spec["dir"] / "skills" / spec["skill"])]
    if spec["browser"]:
        items.append(("using-human-browser", COMMON_SKILLS_DIR / "using-human-browser"))
        items.append(("using-human-dom", COMMON_SKILLS_DIR / "using-human-dom"))
        vision = REPO_ROOT / "platforms" / spec["dir"] / "skills" / "using-vision"
        if vision.is_dir():
            items.append(("using-vision", vision))
        if with_agent_browser:
            items.append(("using-fleet-browser", COMMON_SKILLS_DIR / "using-fleet-browser"))
    return items


def link_or_copy(src: Path, dst: Path, mode: str, force: bool) -> str:
    """Return one of: linked / copied / kept / copied-over / replaced."""
    if dst.is_symlink():
        try:
            if dst.resolve() == src.resolve():
                return "kept"
        except OSError:
            pass
        dst.unlink()
        action = "replaced"
    elif dst.exists():
        if not force:
            return "kept"
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
        action = "replaced"
    else:
        action = "linked" if mode == "symlink" else "copied"

    if mode in ("auto", "symlink"):
        try:
            os.symlink(src, dst, target_is_directory=True)
            return action if action != "copied" else "linked"
        except OSError:
            if mode == "symlink":
                raise
            # Windows without Developer Mode / admin: fall back to a real copy.
            action = "copied"

    shutil.copytree(src, dst)
    return action


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform", choices=sorted(PLATFORMS), help="device role whose skills to install")
    ap.add_argument("--target", help="agent skill directory (default: auto-detect)")
    ap.add_argument("--mode", choices=("auto", "symlink", "copy"), default="auto",
                    help="auto = symlink, fall back to copy where symlinks are not permitted")
    ap.add_argument("--force", action="store_true", help="overwrite existing directories/copies")
    ap.add_argument("--with-agent-browser", action="store_true",
                    help="also install using-fleet-browser (Playwright-backed, automation traces)")
    ap.add_argument("--list", action="store_true", help="print the install plan and exit")
    ap.add_argument("--dry-run", action="store_true", help="print what would change without writing")
    args = ap.parse_args()

    if args.list:
        for platform in PLATFORMS:
            print(f"{platform}:")
            for name, src in plan(platform, args.with_agent_browser):
                print(f"  {name:22s} <- {src.relative_to(REPO_ROOT)}")
        return 0

    if not args.platform:
        ap.error("--platform is required (or use --list)")

    target = Path(args.target).expanduser() if args.target else default_target()
    items = plan(args.platform, args.with_agent_browser)

    print(f"platform : {args.platform}")
    print(f"target   : {target}")
    print(f"mode     : {args.mode}{' (dry-run)' if args.dry_run else ''}")

    missing = [name for name, src in items if not src.is_dir()]
    if missing:
        print(f"ERROR: missing skill source(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    if args.dry_run:
        for name, src in items:
            print(f"  would install {name:22s} <- {src.relative_to(REPO_ROOT)}")
        return 0

    target.mkdir(parents=True, exist_ok=True)
    failures = 0
    for name, src in items:
        dst = target / name
        try:
            action = link_or_copy(src, dst, args.mode, args.force)
        except OSError as exc:
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc} (try --mode copy)")
            continue
        print(f"  {action:9s} {name:22s} -> {dst}")

    if failures:
        return 1

    print("\nverify: the agent's skill catalog should now list "
          + ", ".join(name for name, _ in items))
    print("restart the agent session if the catalog is cached.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
