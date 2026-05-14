from fleet.types import InstallContext, OSInfo
from fleet.installers._env import setup_env


def _ctx(**kw):
    osi = OSInfo(system="Linux", version="6.1", arch="x86_64", is_apple_silicon=False)
    return InstallContext(repo_root="/tmp/repo", os_info=osi, **kw)


def test_win_device_only_gets_wizard_managed():
    env = setup_env(_ctx(), "win-device")
    assert env["ATB_WIZARD_MANAGED"] == "1"
    assert "ATB_ANDROID_MODE" not in env
    assert "ATB_ANDROID_REUSE_CONFIG" not in env


def test_android_reuse_config():
    env = setup_env(_ctx(android_reuse_config=True), "android-device")
    assert env["ATB_WIZARD_MANAGED"] == "1"
    assert env["ATB_ANDROID_REUSE_CONFIG"] == "1"
    assert "ATB_ANDROID_MODE" not in env


def test_android_mode():
    env = setup_env(_ctx(android_mode="usb"), "android-device")
    assert env["ATB_WIZARD_MANAGED"] == "1"
    assert env["ATB_ANDROID_MODE"] == "usb"
    assert "ATB_ANDROID_REUSE_CONFIG" not in env


def test_android_reuse_wins_over_mode():
    # wizard never sets both, but reuse must take precedence if it ever happens
    env = setup_env(_ctx(android_mode="usb", android_reuse_config=True), "android-device")
    assert env["ATB_ANDROID_REUSE_CONFIG"] == "1"
    assert "ATB_ANDROID_MODE" not in env


def test_android_no_choice_only_wizard_managed():
    # android-device selected but no mode collected (shouldn't happen via wizard,
    # but setup_env must not crash) — scripts will fall back to interactive
    env = setup_env(_ctx(), "android-device")
    assert env["ATB_WIZARD_MANAGED"] == "1"
    assert "ATB_ANDROID_MODE" not in env
    assert "ATB_ANDROID_REUSE_CONFIG" not in env


def test_inherits_parent_env():
    env = setup_env(_ctx(), "win-device")
    assert "PATH" in env  # parent process env preserved
