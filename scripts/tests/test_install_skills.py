"""Tests for scripts/install_skills.py."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import install_skills  # noqa: E402


def test_plan_for_win_includes_device_and_browser_skills():
    names = [name for name, _ in install_skills.plan("win-device", with_agent_browser=False)]
    assert names[0] == "using-win"
    assert "using-human-browser" in names
    assert "using-human-dom" in names
    assert "using-vision" in names
    assert "using-fleet-browser" not in names


def test_plan_agent_browser_is_opt_in():
    names = [name for name, _ in install_skills.plan("win-device", with_agent_browser=True)]
    assert "using-fleet-browser" in names


def test_plan_for_mobile_is_device_skill_only():
    for platform, skill in (("android-device", "using-android"), ("ios-device", "using-ios")):
        names = [name for name, _ in install_skills.plan(platform, with_agent_browser=True)]
        assert names == [skill]


def test_all_planned_sources_exist():
    for platform in install_skills.PLATFORMS:
        for name, src in install_skills.plan(platform, with_agent_browser=True):
            assert (src / "SKILL.md").is_file(), f"{platform}: {name} missing SKILL.md at {src}"


def test_copy_mode_is_idempotent_and_force_refreshes(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("v1", encoding="utf-8")
    dst = tmp_path / "target" / "using-x"

    assert install_skills.link_or_copy(src, dst, "copy", force=False) == "copied"
    assert (dst / "SKILL.md").read_text(encoding="utf-8") == "v1"

    # Re-running without --force keeps the existing copy.
    assert install_skills.link_or_copy(src, dst, "copy", force=False) == "kept"
    assert (dst / "SKILL.md").read_text(encoding="utf-8") == "v1"

    # --force refreshes it from the source.
    (src / "SKILL.md").write_text("v2", encoding="utf-8")
    assert install_skills.link_or_copy(src, dst, "copy", force=True) == "replaced"
    assert (dst / "SKILL.md").read_text(encoding="utf-8") == "v2"


def test_list_cli_runs():
    r = subprocess.run(
        [sys.executable, "scripts/install_skills.py", "--list"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "win-device" in r.stdout and "ios-device" in r.stdout
