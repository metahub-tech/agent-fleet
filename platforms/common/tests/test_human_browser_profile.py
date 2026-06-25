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


# --- with_human_dom / --load-extension 启动参数（per-profile 启用 human_dom）---
import pytest
from capabilities.browser._human_browser import _human_launch_args, _human_dom_ext_dir

def test_launch_args_with_load_extension():
    # with_human_dom=True 路径:扩展目录 → 多一个 --load-extension
    args = _human_launch_args("/c", "/udd", "Default", "http://x", load_extension="/ext")
    assert "--load-extension=/ext" in args
    assert "--user-data-dir=/udd" in args and "--profile-directory=Default" in args
    assert args[0] == "/c" and args[-1] == "http://x"

def test_launch_args_without_extension():
    # 不开 human_dom:不应出现 --load-extension
    args = _human_launch_args("/c", "/udd", None, "", load_extension=None)
    assert not any(a.startswith("--load-extension") for a in args)
    assert "--profile-directory" not in " ".join(args)  # pdir=None 不带

def test_human_dom_ext_dir_resolves():
    # with_human_dom 要靠这个定位扩展目录。随仓库发布(含 manifest.json)时应解析到
    # capabilities/human_dom/extension;若该机器是子目录单独 checkout、扩展不在,
    # 返回 None 是合理降级 → skip 而非硬失败(避免不完整 checkout 下误报)。
    d = _human_dom_ext_dir()
    if d is None:
        pytest.skip("human_dom/extension/manifest.json 不在本机,跳过路径解析校验")
    assert d.endswith("human_dom/extension") or d.endswith("human_dom\\extension")
