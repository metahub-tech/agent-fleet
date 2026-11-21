"""Tests for the skills handoff step (fleet.skills + setup flags).

The design point under test: the wizard describes *what* must be made available
and never enumerates agent frameworks / guesses their skill directories.
"""
import json
from pathlib import Path

from fleet import skills
from fleet.cli import build_parser


def _fake_script(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "install_skills.py"
    script.write_text("", encoding="utf-8")
    return script


class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_plan_skills_merges_roles(tmp_path, monkeypatch):
    _fake_script(tmp_path)
    plans = {
        "win-device": ["using-win", "using-human-browser"],
        "android-device": ["using-android"],
    }

    def fake_run(cmd, **kwargs):
        platform_id = cmd[cmd.index("--platform") + 1]
        payload = {
            "platform": platform_id,
            "repo_root": str(tmp_path),
            "skills": [
                {"name": name, "source": str(tmp_path / "skills" / name)} for name in plans[platform_id]
            ],
        }
        return _Proc(json.dumps(payload))

    monkeypatch.setattr(skills.subprocess, "run", fake_run)
    plan = skills.plan_skills(tmp_path, ["win-device", "android-device"])

    assert plan["roles"] == ["win-device", "android-device"]
    assert [s["name"] for s in plan["skills"]] == ["using-android", "using-human-browser", "using-win"]
    assert plan["skills"][0]["roles"] == ["android-device"]
    assert "error" not in plan


def test_plan_skills_missing_script(tmp_path):
    plan = skills.plan_skills(tmp_path, ["win-device"])
    assert plan["skills"] == []
    assert "install_skills.py" in plan["error"]


def test_plan_skills_reports_failed_role(tmp_path, monkeypatch):
    _fake_script(tmp_path)
    monkeypatch.setattr(skills.subprocess, "run", lambda cmd, **kw: _Proc(returncode=2, stderr="boom"))
    plan = skills.plan_skills(tmp_path, ["win-device"])
    assert plan["skills"] == []
    assert "win-device" in plan["error"] and "boom" in plan["error"]


def test_handoff_tells_the_agent_what_to_do_and_where():
    plan = {
        "repo_root": "/repo",
        "roles": ["win-device"],
        "skills": [{"name": "using-win", "source": "/repo/platforms/windows/skills/using-win", "roles": ["win-device"]}],
    }
    md = skills.handoff_markdown(plan)

    assert "要做什么" in md
    assert "重启会话" in md
    assert "`using-win`" in md
    assert "/repo/platforms/windows/skills/using-win" in md
    # Placement is the agent's job, with examples explicitly marked non-exhaustive.
    assert "非穷举" in md
    assert "~/.claude/skills/" in md and "~/.dsh/skills/" in md
    assert "scripts/install_skills.py --platform <role> --target" in md


def test_write_handoff_creates_md_and_json(tmp_path):
    plan = {"repo_root": "/repo", "roles": ["win-device"], "skills": []}
    md_path, json_path = skills.write_handoff(plan, out_dir=tmp_path)

    assert md_path.is_file() and json_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["generated_by"] == "agent-fleet setup"
    assert "restart the session" in payload["action"]
    assert payload["roles"] == ["win-device"]


def test_install_to_delegates_one_call_per_role(tmp_path, monkeypatch):
    _fake_script(tmp_path)
    calls = []
    monkeypatch.setattr(skills.subprocess, "run",
                        lambda cmd, **kw: (calls.append(cmd), _Proc("ok"))[1])

    results = skills.install_to(tmp_path, ["win-device", "android-device"], "~/.dsh/skills")

    assert [r[0] for r in results] == ["win-device", "android-device"]
    assert all(r[1] == 0 for r in results)
    assert len(calls) == 2
    assert "--target" in calls[0] and "~/.dsh/skills" in calls[0]
    assert "--dry-run" not in calls[0]


def test_setup_flags_expose_no_skills_and_skills_target():
    args = build_parser().parse_args(["setup", "--no-skills", "--skills-target", "/tmp/skills"])
    assert args.no_skills is True
    assert args.skills_target == "/tmp/skills"
    assert build_parser().parse_args(["setup"]).skills_target is None
