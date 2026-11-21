"""Install agent-fleet skills into a client's skill directory.

The skill bundles live in the repo (``platforms/<p>/skills`` and
``platforms/common/skills``) and are installed by ``scripts/install_skills.py``.
The CLI shells out to that script instead of duplicating the layout rules — the
CLI already requires a repo checkout because ``platforms/`` is not packaged into
the wheel.

Only clients that actually load skills from disk expose a ``skills_dir``; for the
others (Cursor, Cline, ...) the wizard prints the manual command instead of
writing somewhere the client would ignore.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_REL = Path("scripts") / "install_skills.py"


def skill_targets(frameworks) -> list[str]:
    """Skill directories of the selected frameworks, de-duplicated, in selection order."""
    seen: list[str] = []
    for fw in frameworks:
        target = getattr(fw, "skills_dir", None)
        if target and target not in seen:
            seen.append(target)
    return seen


def find_script(repo_root: str | Path) -> Path | None:
    path = Path(repo_root) / SCRIPT_REL
    return path if path.is_file() else None


def install_skills(
    repo_root: str | Path,
    platform_ids: list[str],
    target: str,
    dry_run: bool = False,
) -> list[tuple[str, int, str]]:
    """Run ``install_skills.py`` once per role. Returns ``(platform_id, rc, output)``.

    A role id is exactly what the script's ``--platform`` expects
    (``win-device`` / ``mac-device`` / ``android-device`` / ``ios-device``).
    """
    script = find_script(repo_root)
    if script is None:
        return [("*", 127, f"missing {SCRIPT_REL.as_posix()} under {repo_root}")]
    results: list[tuple[str, int, str]] = []
    for platform_id in platform_ids:
        cmd = [sys.executable, str(script), "--platform", platform_id, "--target", target]
        if dry_run:
            cmd.append("--dry-run")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = f"{proc.stdout or ''}{proc.stderr or ''}".strip()
        results.append((platform_id, proc.returncode, output))
    return results
