"""Resolve the skill set for the installed roles and hand it off to the running agent.

The wizard deliberately does **not** enumerate agent frameworks: there is no
finite list of harnesses and their skill directories, and guessing one is how
you silently write into a directory the client never reads. So the wizard only
states *what* must happen:

* ``~/.fleet/skills-handoff.md`` / ``.json`` — the resolved skills, their
  absolute source paths, and the instruction "put these where your agent loads
  skills from, then restart the session" (written for an agent to act on);
* ``--skills-target <dir>`` — when a human or script wants the wizard to place
  them itself, it does exactly that and nothing else.

The actual file placement lives in ``scripts/install_skills.py``; this module
only plans, describes and (optionally) delegates.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_REL = Path("scripts") / "install_skills.py"
HANDOFF_DIR = Path("~/.fleet")


def find_script(repo_root: str | Path) -> Path | None:
    path = Path(repo_root) / SCRIPT_REL
    return path if path.is_file() else None


def plan_skills(repo_root: str | Path, platform_ids: list[str]) -> dict:
    """Resolve skills for the given roles via ``install_skills.py --json`` (no writes).

    Returns ``{"repo_root", "roles", "skills": [{"name", "source", "roles"}]}``;
    a role whose names are already present merges into the existing entry.
    """
    script = find_script(repo_root)
    if script is None:
        return {"repo_root": str(repo_root), "roles": list(platform_ids), "skills": [], "error": f"missing {SCRIPT_REL.as_posix()}"}

    merged: dict[str, dict] = {}
    errors: list[str] = []
    for platform_id in platform_ids:
        proc = subprocess.run(
            [sys.executable, str(script), "--platform", platform_id, "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            errors.append(f"{platform_id}: {proc.stderr.strip() or proc.stdout.strip()}")
            continue
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            errors.append(f"{platform_id}: invalid JSON plan ({exc})")
            continue
        for skill in payload.get("skills", []):
            entry = merged.setdefault(
                skill["name"], {"name": skill["name"], "source": skill["source"], "roles": []}
            )
            if platform_id not in entry["roles"]:
                entry["roles"].append(platform_id)

    plan: dict = {
        "repo_root": str(Path(repo_root).resolve()),
        "roles": list(platform_ids),
        "skills": sorted(merged.values(), key=lambda s: s["name"]),
    }
    if errors:
        plan["error"] = "; ".join(errors)
    return plan


def handoff_markdown(plan: dict) -> str:
    """Agent-readable instruction: what to make available, and that placement is the agent's job."""
    lines = [
        "# agent-fleet · skills handoff",
        "",
        f"- generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- repo: {plan.get('repo_root', '')}",
        f"- roles: {', '.join(plan.get('roles', [])) or '(none)'}",
        "",
        "## 要做什么（给 agent）",
        "",
        "把下面每个 skill 目录放进**你自己加载技能的位置**，然后重启会话。",
        "agent-fleet 不知道、也不枚举所有 harness —— 所以这里只声明「要什么」，放哪儿按你自己那套约定决定：",
        "",
        "- 常见约定（示例，非穷举）：Claude Code → `~/.claude/skills/`；DeepSeek Harness → `~/.dsh/skills/`（项目级 `<repo>/.dsh/skills/`）；其它 harness 按其文档，或直接在会话里读取下面的 `SKILL.md` 绝对路径。",
        "- 若你的 harness 不支持磁盘技能目录：在需要时读取 `SKILL.md`，按其中的规范调用 MCP 工具即可。",
        "- 放好之后**重启会话**，技能目录才会刷新。",
        "",
        "## skills",
        "",
        "| skill | 源目录（绝对路径） | 角色 |",
        "|---|---|---|",
    ]
    for skill in plan.get("skills", []):
        lines.append(f"| `{skill['name']}` | `{skill['source']}` | {', '.join(skill['roles'])} |")
    if not plan.get("skills"):
        lines.append("| _(none)_ | — | — |")
    lines += [
        "",
        "## 想省事时（让 agent-fleet 代放）",
        "",
        "```bash",
        "python3 scripts/install_skills.py --platform <role> --target <你的技能目录>",
        "```",
        "",
    ]
    if plan.get("error"):
        lines += [f"> plan error: {plan['error']}", ""]
    return "\n".join(lines)


def write_handoff(plan: dict, out_dir: str | Path | None = None) -> tuple[Path, Path]:
    """Write ``skills-handoff.md`` and ``skills-handoff.json``; returns both paths."""
    directory = Path(out_dir).expanduser() if out_dir else HANDOFF_DIR.expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    md_path = directory / "skills-handoff.md"
    json_path = directory / "skills-handoff.json"
    md_path.write_text(handoff_markdown(plan), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "generated_by": "agent-fleet setup",
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "action": (
                    "Place each skill directory where YOUR agent loads skills from "
                    "(Claude Code: ~/.claude/skills; DeepSeek Harness: ~/.dsh/skills or "
                    "<repo>/.dsh/skills; otherwise follow your harness), then restart the session."
                ),
                **plan,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return md_path, json_path


def install_to(repo_root: str | Path, platform_ids: list[str], target: str, dry_run: bool = False) -> list[tuple[str, int, str]]:
    """Delegate placement to ``install_skills.py --target`` (one call per role)."""
    script = find_script(repo_root)
    if script is None:
        return [("*", 127, f"missing {SCRIPT_REL.as_posix()} under {repo_root}")]
    results: list[tuple[str, int, str]] = []
    for platform_id in platform_ids:
        cmd = [sys.executable, str(script), "--platform", platform_id, "--target", target]
        if dry_run:
            cmd.append("--dry-run")
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        results.append((platform_id, proc.returncode, f"{proc.stdout or ''}{proc.stderr or ''}".strip()))
    return results
