#!/usr/bin/env python3
"""Install one device's MCP server + skill into the local Claude Code config.

Usage:
    python3 scripts/install-agent-side.py --platform macbox-gui --hostname mac-test
    python3 scripts/install-agent-side.py --platform winpc-gui  --hostname win-test

What this does (idempotent):
    1. Validate inputs (platform name + repo layout).
    2. Backup ~/.claude.json with timestamped filename.
    3. Merge {platform}: {type=http, url=http://{hostname}:{port}/mcp} into mcpServers.
       (Migrated from SSE in v0.4.x; streamable-http is more resilient to long
        tool calls and middle-box keepalive timeouts. Endpoint path is /mcp
        instead of /sse.)
    4. Symlink ~/.claude/skills/using-{shortname} to platforms/{platform_dir}/skills/using-{shortname}.
    5. Print next steps.

Safe to run multiple times -- reuses backup naming, overwrites existing entries
in place (preserving other MCP servers), and recreates symlinks if dangling.

This is the agent-side counterpart to platforms/<name>/scripts/setup-<name>.{sh,ps1}
which run on the DEVICE host. setup-* configures the MCP server; this script
configures the MCP CLIENT.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Each platform: (mcp-name in ~/.claude.json, repo-dir under platforms/, skill name, default port)
PLATFORMS = {
    "winpc-gui":   {"dir": "windows", "skill": "using-winpc",   "port": 8766},
    "macbox-gui":  {"dir": "macos",   "skill": "using-macbox",  "port": 8767},
    "android-gui": {"dir": "android", "skill": "using-android", "port": 8768},
    # Future entries land here as platforms ship.
    # "iphone":   {"dir": "ios",     "skill": "using-iphone",  "port": 8769},
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--platform", required=True, choices=sorted(PLATFORMS),
                   help="MCP server name; matches Tailscale role + port")
    p.add_argument("--hostname", required=True,
                   help="Tailscale MagicDNS hostname of the device (e.g. mac-test, win-test)")
    p.add_argument("--config", default=str(Path.home() / ".claude.json"),
                   help="Path to Claude Code state file (default: ~/.claude.json)")
    p.add_argument("--skills-dir", default=str(Path.home() / ".claude" / "skills"),
                   help="Where to symlink skill (default: ~/.claude/skills)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print intended changes without writing")
    return p.parse_args()


def backup_json(config_path: Path) -> Path | None:
    if not config_path.exists():
        return None
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = config_path.with_suffix(f".json.bak-{ts}")
    shutil.copy2(config_path, backup)
    return backup


def merge_mcp_entry(config_path: Path, name: str, url: str, dry_run: bool) -> str:
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: {config_path} is not valid JSON: {e}\n"
                     f"       Refusing to overwrite. Fix the file first.")
    else:
        data = {}

    servers = data.setdefault("mcpServers", {})
    new_entry = {"type": "http", "url": url}
    prev = servers.get(name)
    servers[name] = new_entry

    if dry_run:
        return f"[DRY RUN] would write {name}: {new_entry} into {config_path}"

    # Preserve formatting (2-space indent, trailing newline) -- Claude Code rewrites it later anyway
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    if prev is None:
        return f"  added  mcpServers[{name}] = {new_entry}"
    elif prev == new_entry:
        return f"  ok     mcpServers[{name}] already = {new_entry}"
    else:
        return f"  update mcpServers[{name}] {prev} -> {new_entry}"


def install_skill_symlink(skills_dir: Path, skill_name: str, target: Path, dry_run: bool) -> str:
    if not target.exists():
        sys.exit(f"ERROR: skill source missing at {target}\n"
                 f"       Repo layout broken? Re-clone or check 'platforms/{skill_name.replace('using-', '')}'.")
    skills_dir.mkdir(parents=True, exist_ok=True)
    link_path = skills_dir / skill_name

    if link_path.is_symlink():
        existing = link_path.resolve()
        if existing == target.resolve():
            return f"  ok     {link_path} -> {target}"
        if dry_run:
            return f"[DRY RUN] would replace symlink {link_path} -> {target} (was -> {existing})"
        link_path.unlink()
        link_path.symlink_to(target)
        return f"  update {link_path} -> {target} (was -> {existing})"
    if link_path.exists():
        sys.exit(f"ERROR: {link_path} exists but is not a symlink. Refusing to overwrite.\n"
                 f"       Move/delete it first, then re-run.")
    if dry_run:
        return f"[DRY RUN] would create symlink {link_path} -> {target}"
    link_path.symlink_to(target)
    return f"  added  {link_path} -> {target}"


def main() -> None:
    # --- DEPRECATION NOTICE (v0.5.0+) ---
    print("=" * 72, file=sys.stderr)
    print(" DEPRECATION NOTICE", file=sys.stderr)
    print("   scripts/install-agent-side.py is deprecated as of v0.5.0.", file=sys.stderr)
    print("   Use the new wizard instead:", file=sys.stderr)
    print("     uvx agent-fleet setup", file=sys.stderr)
    print("   or, with the one-shot bootstrap:", file=sys.stderr)
    print("     curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh | bash", file=sys.stderr)
    print("   This script will be removed in v0.6.0.", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    print(file=sys.stderr)
    # --- end ---
    args = parse_args()
    spec = PLATFORMS[args.platform]
    skill_src = REPO_ROOT / "platforms" / spec["dir"] / "skills" / spec["skill"]
    if not skill_src.is_dir():
        sys.exit(f"ERROR: expected skill source at {skill_src} but it doesn't exist.\n"
                 f"       Are you running from inside the agent-test-bench repo?")
    config_path = Path(args.config).expanduser()
    skills_dir = Path(args.skills_dir).expanduser()
    url = f"http://{args.hostname}:{spec['port']}/mcp"

    print(f"=== install-agent-side ===")
    print(f"  repo     : {REPO_ROOT}")
    print(f"  platform : {args.platform}  (port {spec['port']})")
    print(f"  hostname : {args.hostname}")
    print(f"  url      : {url}")
    print(f"  config   : {config_path}")
    print(f"  skill    : {skill_src}  ->  {skills_dir / spec['skill']}")
    if args.dry_run:
        print(f"  mode     : DRY RUN (no changes will be written)")
    print()

    # 1. Backup
    if not args.dry_run:
        backup = backup_json(config_path)
        if backup:
            print(f"[1/3] backup  {config_path} -> {backup}")
        else:
            print(f"[1/3] backup  (no existing {config_path}; skipping)")
    else:
        print(f"[1/3] backup  [DRY RUN] would back up {config_path}")

    # 2. Merge MCP entry
    print(f"[2/3] mcpServers")
    print(merge_mcp_entry(config_path, args.platform, url, args.dry_run))

    # 3. Skill symlink
    print(f"[3/3] skill")
    print(install_skill_symlink(skills_dir, spec["skill"], skill_src, args.dry_run))

    print()
    print("=== done ===")
    print()
    print("Next steps:")
    print("  1. Restart your MCP client (Claude Code: /exit then reopen)")
    print(f"  2. Run /mcp -- you should see '{args.platform} [http] connected'")
    print(f"  3. Skill 'using-{args.platform.replace('-gui', '')}' is now")
    print(f"     auto-loaded by the client; ask the agent to drive the device.")
    print()
    print("Trouble? See docs/install-pattern.md and docs/agent-host-setup.md § 4.")


if __name__ == "__main__":
    main()
