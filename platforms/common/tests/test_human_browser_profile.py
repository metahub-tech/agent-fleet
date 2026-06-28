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
from capabilities.browser._human_browser import _human_launch_args, _FIRST_RUN_SUPPRESS_FLAGS

def test_launch_args_with_profile_dir():
    args = _human_launch_args("/c", "/udd", "Default", "http://x")
    assert args == ["/c", "--user-data-dir=/udd", *_FIRST_RUN_SUPPRESS_FLAGS,
                    "--profile-directory=Default", "http://x"]

def test_launch_args_no_pdir_no_url():
    args = _human_launch_args("/c", "/udd", None, "")
    assert args == ["/c", "--user-data-dir=/udd", *_FIRST_RUN_SUPPRESS_FLAGS]
    assert "--profile-directory" not in " ".join(args)  # pdir=None 不带

def test_launch_args_suppresses_first_run_popups():
    # AgentHub #211: 全新 profile 必须零首启原生弹窗(登录提示/设默认横幅/What's New/FRE),
    # 否则操作员 agent 不认识这些原生窗口会乱处理(误关标签/落登录页)。
    # test-win11 真机验证的 flag 组;flag 不禁用扩展、不影响 human_dom 加载。
    args = _human_launch_args("/c", "/udd", None, "http://x")
    for flag in ("--no-first-run", "--no-default-browser-check", "--disable-fre"):
        assert flag in args, f"缺首启抑制 flag: {flag}"
    feat = next(a for a in args if a.startswith("--disable-features="))
    for f in ("ChromeWhatsNewUI", "SigninPromo", "ForYouFre"):
        assert f in feat, f"--disable-features 缺 {f}"
    # url 仍是最后一个位置参(Chrome 把位置参当要打开的 URL),flag 在它之前
    assert args[-1] == "http://x"
    assert args[0] == "/c" and args[1] == "--user-data-dir=/udd"  # binary + udd 仍在最前
