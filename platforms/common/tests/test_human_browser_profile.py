import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # common/ for _browser_lease
from _browser_lease import _resolve_profile

def test_path_profile():
    udd, pdir, key = _resolve_profile("~/.fleet/wechat-publisher")
    assert udd.endswith("wechat-publisher")
    assert pdir is None
    assert key == udd

def test_dir_at_name():
    udd, pdir, key = _resolve_profile("/tmp/work@Profile 1")
    assert pdir == "Profile 1"
    assert key == udd + "::Profile 1"

def test_same_string_same_key_R4():
    # R4: agent 与 human 传同一 profile 值 → 同 key → 同磁盘登录
    assert _resolve_profile("~/.fleet/op")[2] == _resolve_profile("~/.fleet/op")[2]

def test_isolated_default():
    udd, pdir, key = _resolve_profile("")
    assert udd.endswith("agent-browser-profile") and pdir is None


# --- _human_launch_args 专用 profile 启动参数（纯函数）---
from capabilities.browser._human_browser import _human_launch_args

def test_launch_args_with_profile_dir():
    args = _human_launch_args("/c", "/udd", "Default", "http://x")
    assert args == ["/c", "--user-data-dir=/udd", "--profile-directory=Default", "http://x"]

def test_launch_args_no_pdir_no_url():
    args = _human_launch_args("/c", "/udd", None, "")
    assert args == ["/c", "--user-data-dir=/udd"]
    assert "--profile-directory" not in " ".join(args)  # pdir=None 不带
