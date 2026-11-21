"""Tests for the wizard's skill-install step (fleet.skills + the --no-skills flag)."""
import types

from fleet import skills
from fleet.cli import build_parser
from fleet.frameworks import FRAMEWORK_REGISTRY


def _fw(**kwargs):
    return types.SimpleNamespace(**kwargs)


def test_claude_code_exposes_skills_dir():
    fw = {f.framework_id: f for f in FRAMEWORK_REGISTRY}["claude-code"]
    assert fw.skills_dir == "~/.claude/skills"


def test_clients_without_skill_dir_are_none():
    fw = {f.framework_id: f for f in FRAMEWORK_REGISTRY}["cursor"]
    assert fw.skills_dir is None


def test_skill_targets_dedup_and_preserve_order():
    a = _fw(skills_dir="~/.claude/skills")
    b = _fw(skills_dir=None)
    c = _fw(skills_dir="~/.dsh/skills")
    d = _fw(skills_dir="~/.claude/skills")
    assert skills.skill_targets([a, b, c, d]) == ["~/.claude/skills", "~/.dsh/skills"]


def test_find_script(tmp_path):
    assert skills.find_script(tmp_path) is None
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "install_skills.py").write_text("", encoding="utf-8")
    assert skills.find_script(tmp_path) == tmp_path / "scripts" / "install_skills.py"


def test_install_skills_builds_one_call_per_role(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "install_skills.py").write_text("", encoding="utf-8")
    calls = []

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Proc()

    monkeypatch.setattr(skills.subprocess, "run", fake_run)
    results = skills.install_skills(
        tmp_path, ["win-device", "android-device"], "~/.dsh/skills", dry_run=True
    )

    assert [r[0] for r in results] == ["win-device", "android-device"]
    assert all(r[1] == 0 for r in results)
    assert len(calls) == 2
    assert calls[0][-1] == "--dry-run"
    assert "--platform" in calls[0] and "win-device" in calls[0]
    assert "--target" in calls[0] and "~/.dsh/skills" in calls[0]


def test_install_skills_reports_missing_script(tmp_path):
    results = skills.install_skills(tmp_path, ["win-device"], "~/.dsh/skills")
    assert results[0][1] == 127
    assert "install_skills.py" in results[0][2]


def test_setup_accepts_no_skills_flag():
    args = build_parser().parse_args(["setup", "--no-skills"])
    assert args.no_skills is True
    assert args.dry_run is False
