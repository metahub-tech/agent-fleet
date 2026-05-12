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
        f"  Tailscale  : {'ok, hostname=' + ts.hostname if ts else 'not detected'}",
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


def _network_choices(ts):
    """Build the (choices, default_value) pair for the network-mode prompt.

    questionary.select validates `default` against `[c.value for c in choices]`
    (NOT against titles — verified in questionary/prompts/common.py:30-31), so
    we must pass a value here.  Extracted so tests can assert the default is
    always one of the available values.
    """
    lan = questionary.Choice("LAN / same WiFi", value="lan")
    ts_suffix = " [logged in]" if ts else " [not detected]"
    tch = questionary.Choice("Tailscale (recommended)" + ts_suffix, value="tailscale")
    default_value = tch.value if ts else lan.value
    return [lan, tch], default_value


def _select_network(ts):
    choices, default = _network_choices(ts)
    choice = questionary.select(
        "Network mode:",
        choices=choices,
        default=default,
    ).ask()
    return choice or "lan"


def _select_frameworks():
    # Claude Code is pre-checked.  Users who press <enter> without space-toggling
    # any item still get the most common config snippet (rather than no output at
    # all, which was a silent UX dead-end before this change).
    choices = [
        questionary.Choice(
            f"{fw.framework_id}  ({fw.display_name})",
            value=fw,
            checked=(fw.framework_id == "claude-code"),
        )
        for fw in FRAMEWORK_REGISTRY
    ]
    return questionary.checkbox(
        "Which agent frameworks to generate config for? (space to toggle, enter to confirm)",
        choices=choices,
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
    """Install each role, verify, return (server_roles, installers).

    server_roles : list[ServerRole]      — thin dataclass for snippet rendering
    installers   : list[BaseInstaller]   — kept in parallel so smoke runner can
                                           call installer.smoke_tests() (which
                                           ServerRole doesn't have).
    """
    for r in roles:
        console.print(f"\n[bold]Installing {r.role_id}…[/bold]")
        for ev in r.install(ctx):
            color = "red" if ev.level == "error" else ("yellow" if ev.level == "warn" else "white")
            console.print(f"  [{color}]{ev.message}[/{color}]")
    deployed: list[ServerRole] = []
    deployed_installers: list = []
    failed_roles = []
    for r in roles:
        if ctx.dry_run:
            console.print(f"  [dim]↪ {r.role_id} verify skipped (dry-run)[/dim]")
            deployed.append(ServerRole(role_id=r.role_id, display_name=r.display_name,
                                       hostname=ctx.tailscale_hostname or "127.0.0.1", port=r.port))
            deployed_installers.append(r)
            continue
        result = r.verify()
        if result.ok:
            console.print(f"  [green]✓[/green] {r.role_id} verified ({result.tool_count} tools)")
            deployed.append(ServerRole(role_id=r.role_id, display_name=r.display_name,
                                       hostname=ctx.tailscale_hostname or "127.0.0.1", port=r.port))
            deployed_installers.append(r)
        else:
            console.print(f"  [red]✗[/red] {r.role_id} verify failed: {result.error}")
            failed_roles.append((r, result))
    if failed_roles:
        console.print()
        console.print(f"[yellow]⚠ {len(failed_roles)} role(s) failed verification — "
                      f"NOT included in framework config snippets below:[/yellow]")
        for r, res in failed_roles:
            console.print(f"  [yellow]·[/yellow] {r.role_id}: {res.error}")
        console.print("[yellow]  Re-run `uvx agent-fleet setup` after fixing the service "
                      "(check logs / port).[/yellow]")
    return deployed, deployed_installers


def _run_smoke_tests(deployed, hostname: str) -> None:
    """For each deployed role, call its smoke_tests() and render a pass/fail
    table.  Connects to the server over Tailscale (hostname) so smoke
    exercises the same network path the agent will use, not just localhost.
    """
    from .smoke import run_smoke_tests

    total_pass = total_fail = total_skip = 0
    console.print("\n[bold]🩺 Smoke testing each MCP server...[/bold]")
    console.print("[dim]   (calls representative tools end-to-end; catches TCC / device / venv issues now,\n   not after you restart your agent host)[/dim]")
    for role in deployed:
        tests = role.smoke_tests()
        if not tests:
            continue
        url = f"http://{hostname}:{role.port}/mcp"
        console.print(f"\n  [bold]{role.role_id}[/bold]  [dim]({url})[/dim]")
        results = run_smoke_tests(hostname, role.port, tests)
        for r in results:
            if r.ok:
                total_pass += 1
                tail = f"[dim]({r.duration_ms}ms)[/dim]" if r.duration_ms else ""
                console.print(f"    [green]✓[/green] {r.test.description:<28} {tail}")
            elif r.skipped:
                total_skip += 1
                console.print(f"    [yellow]–[/yellow] {r.test.description:<28} [dim](optional, skipped: {r.error})[/dim]")
            else:
                total_fail += 1
                console.print(f"    [red]✗[/red] {r.test.description:<28} [red]{r.error}[/red]")
                if r.test.hint_on_failure:
                    console.print(f"        [yellow]↪ {r.test.hint_on_failure}[/yellow]")

    total = total_pass + total_fail + total_skip
    summary_color = "green" if total_fail == 0 else "yellow"
    summary = f"\n[bold {summary_color}]📊 Smoke summary: {total_pass}/{total} passed"
    if total_fail:
        summary += f", {total_fail} FAILED"
    if total_skip:
        summary += f", {total_skip} optional-skipped"
    summary += "[/bold {0}]".format(summary_color)
    console.print(summary)
    if total_fail:
        console.print("[yellow]   Address the failed item(s) above, then re-run `agent-fleet setup` to re-verify.[/yellow]")


def _run_guidance(roles, ctx):
    """For each role, optionally invoke the macOS primer (registers Python.app
    in TCC + opens the Settings pane), then print the guidance step and wait
    for user keystroke."""
    from . import macos_perm

    macos_primer = {
        "macos_accessibility": lambda p: macos_perm.prime_accessibility(p),
        "macos_screen_recording": lambda p: macos_perm.prime_screen_recording(p),
        "macos_automation": lambda p: macos_perm.prime_automation(),
        "macos_full_disk_access": lambda p: macos_perm.prime_full_disk_access(),
    }

    venv_py = Path(ctx.repo_root) / "platforms" / "macos" / "server" / ".venv" / "bin" / "python3"
    venv_ready = venv_py.exists()

    for r in roles:
        steps = r.guidance_steps()
        if not steps:
            continue
        console.print(f"\n[bold magenta]🔓 Operation guidance for {r.role_id}[/bold magenta]")
        if any(s.id in macos_primer for s in steps) and not venv_ready:
            console.print(f"  [yellow]↪ venv not found at {venv_py}; primers will be skipped.[/yellow]")
        for i, s in enumerate(steps, 1):
            console.print(f"\n  [bold]Step {i}/{len(steps)}: {s.title}[/bold]")
            if s.id in macos_primer and venv_ready:
                console.print(f"  [dim]↪ Triggering {s.id} ...[/dim]")
                macos_primer[s.id](venv_py)
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

    deployed, deployed_installers = _run_install(roles, ctx)
    if args.dry_run:
        console.print("\n[dim]↪ Skipping operation guidance + smoke tests (dry-run).[/dim]")
    else:
        _run_guidance(roles, ctx)
        if deployed_installers:
            _run_smoke_tests(deployed_installers, hostname or "127.0.0.1")

    frameworks = _select_frameworks()
    if frameworks:
        _print_framework_snippets(frameworks, deployed)
    else:
        console.print(
            "\n[yellow]No agent frameworks selected — skipping config snippets.[/yellow]\n"
            "[dim]Endpoints are listed in the summary below. Re-run `agent-fleet setup`\n"
            "and press <space> on each framework you want to generate snippets for.[/dim]"
        )

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
