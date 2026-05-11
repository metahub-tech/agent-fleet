from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

import fleet
from .detect import detect_os, detect_tailscale, detect_uv
from .frameworks import FRAMEWORK_REGISTRY
from .frameworks.base import ServerRoleEntry
from .installers import filter_for_os
from .types import ServerRole
from .wizard import build_install_context, render_install_summary

console = Console()


def _banner():
    osi = detect_os()
    uv = detect_uv()
    ts = detect_tailscale()
    lines = [
        f"agent-fleet v{fleet.__version__}",
        f"  OS         : {osi.system} {osi.version} ({osi.arch})",
        f"  uv         : {'ok' if uv else 'missing'}",
        f"  Tailscale  : {'logged in as ' + ts.hostname if ts else 'not detected'}",
    ]
    console.print(Panel("\n".join(lines), title="🚢 agent-fleet"))
    return osi, ts


def _select_roles(osi):
    candidates = filter_for_os(osi)
    if not candidates:
        console.print("[red]No supported roles for this OS.[/red]")
        return []
    answer = questionary.checkbox(
        f"Roles for this {osi.kind} machine to host:",
        choices=[questionary.Choice(f"{i.role_id}  ({i.display_name}, :{i.port})", value=i) for i in candidates],
    ).ask()
    return answer or []


def _select_network(ts):
    default = "tailscale" if ts else "lan"
    choice = questionary.select(
        "Network mode:",
        choices=[
            questionary.Choice("LAN / same WiFi", value="lan"),
            questionary.Choice("Tailscale (recommended)" + (" [logged in]" if ts else " [not detected]"), value="tailscale"),
        ],
        default="LAN / same WiFi" if default == "lan" else "Tailscale (recommended)",
    ).ask()
    return choice or "lan"


def _select_frameworks():
    return questionary.checkbox(
        "Which agent frameworks to generate config for?",
        choices=[questionary.Choice(f"{fw.framework_id}  ({fw.display_name})", value=fw) for fw in FRAMEWORK_REGISTRY],
    ).ask() or []


def _print_framework_snippets(frameworks, server_roles):
    entries = [ServerRoleEntry(role=r) for r in server_roles]
    for fw in frameworks:
        snippet = fw.render_full_snippet(entries)
        lang = "json" if fw.config_format == "json" else "yaml"
        console.print(Panel(Syntax(snippet, lang, line_numbers=False), title=f"{fw.display_name} → {fw.config_path_template}"))
        if fw.notes():
            console.print(f"[dim]Notes: {fw.notes()}[/dim]\n")
        if fw.cli_alternative():
            console.print(f"[cyan]CLI alternative:[/cyan]\n{fw.cli_alternative()}\n")


def _run_install(roles, ctx):
    for r in roles:
        console.print(f"\n[bold]Installing {r.role_id}…[/bold]")
        for ev in r.install(ctx):
            color = "red" if ev.level == "error" else ("yellow" if ev.level == "warn" else "white")
            console.print(f"  [{color}]{ev.message}[/{color}]")
    # Verify each
    deployed = []
    for r in roles:
        result = r.verify()
        if result.ok:
            console.print(f"  [green]✓[/green] {r.role_id} verified ({result.tool_count} tools)")
            deployed.append(ServerRole(role_id=r.role_id, display_name=r.display_name,
                                       hostname=ctx.tailscale_hostname or "127.0.0.1", port=r.port))
        else:
            console.print(f"  [red]✗[/red] {r.role_id} verify failed: {result.error}")
    return deployed


def _run_guidance(roles):
    for r in roles:
        steps = r.guidance_steps()
        if not steps:
            continue
        console.print(f"\n[bold magenta]🔓 Operation guidance for {r.role_id}[/bold magenta]")
        for i, s in enumerate(steps, 1):
            console.print(f"\n  [bold]Step {i}/{len(steps)}: {s.title}[/bold]")
            console.print(f"  {s.default_description}")
            if s.variants:
                console.print(f"\n  [dim]{s.variant_label} 变体：[/dim]")
                for vid, v in s.variants.items():
                    console.print(f"    [cyan]{v.label}[/cyan]: {v.description}")
            questionary.press_any_key_to_continue("  ↩ 完成后回车继续").ask()


def cmd_setup(args: argparse.Namespace) -> int:
    osi, ts = _banner()
    roles = _select_roles(osi)
    if not roles:
        console.print("[yellow]No roles selected — exiting.[/yellow]")
        return 0
    network = _select_network(ts)
    hostname = ts.hostname if ts else None

    ctx = build_install_context(
        repo_root=str(Path.cwd()),
        os_info=osi,
        dry_run=args.dry_run,
        network=network,
        tailscale_hostname=hostname,
    )

    deployed = _run_install(roles, ctx)
    _run_guidance(roles)

    frameworks = _select_frameworks()
    if frameworks:
        _print_framework_snippets(frameworks, deployed)

    console.print(Panel(render_install_summary(tailscale_hostname=hostname, deployed_roles=deployed)))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-fleet", description="agent-fleet: install MCP servers and generate agent-client config")
    parser.add_argument("--version", action="version", version=fleet.__version__)
    sub = parser.add_subparsers(dest="cmd")

    p_setup = sub.add_parser("setup", help="Run the interactive setup wizard")
    p_setup.add_argument("--dry-run", action="store_true", help="Show actions without writing")
    p_setup.set_defaults(func=cmd_setup)

    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
