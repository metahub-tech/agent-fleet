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
from capabilities.browser._human_browser import (
    _human_launch_args, _FIRST_RUN_FLAGS, _FIRST_RUN_DISABLE_FEATURES)

_FR_DF = "--disable-features=" + ",".join(_FIRST_RUN_DISABLE_FEATURES)

def test_launch_args_with_profile_dir():
    args = _human_launch_args("/c", "/udd", "Default", "http://x")
    assert args == ["/c", "--user-data-dir=/udd", *_FIRST_RUN_FLAGS, _FR_DF,
                    "--profile-directory=Default", "http://x"]

def test_launch_args_no_pdir_no_url():
    args = _human_launch_args("/c", "/udd", None, "")
    assert args == ["/c", "--user-data-dir=/udd", *_FIRST_RUN_FLAGS, _FR_DF]
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


# --- auto-bake: 起专用 profile 时自动烤 human_dom 扩展副本(AgentHub #211 ★最大优化)---
import json
from capabilities.browser._human_browser import _ensure_human_dom_ext
from capabilities.human_dom._ident import human_dom_profile_id

def test_ensure_ext_auto_bakes_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # win 用 USERPROFILE
    ext = _ensure_human_dom_ext("~/.fleet/op-x", 8779)
    assert ext is not None and Path(ext).is_dir()
    assert Path(ext).name == human_dom_profile_id("~/.fleet/op-x")  # 目录名=profile_id
    cjs = (Path(ext) / "content.js").read_text(encoding="utf-8")
    assert "__AF_PROFILE_ID__" not in cjs and "__AF_PORT__" not in cjs  # 占位已烤掉(非模板)
    meta = json.loads((Path(ext) / "meta.json").read_text(encoding="utf-8"))
    assert meta["bridge_port"] == 8779

def test_ensure_ext_idempotent_same_port(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    ext1 = _ensure_human_dom_ext("~/.fleet/op-x", 8779)
    sentinel = Path(ext1) / "_keep.txt"; sentinel.write_text("x")  # 若重烤(rmtree)会被删
    ext2 = _ensure_human_dom_ext("~/.fleet/op-x", 8779)  # 桥端口同 → 不重烤
    assert ext2 == ext1 and sentinel.exists()  # 哨兵还在 = 没重烤

def test_ensure_ext_rebakes_on_port_change(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    ext = _ensure_human_dom_ext("~/.fleet/op-x", 8779)
    sentinel = Path(ext) / "_keep.txt"; sentinel.write_text("x")
    _ensure_human_dom_ext("~/.fleet/op-x", 8780)  # 桥端口变 → 重烤(server 换端口后旧副本失效)
    assert not sentinel.exists()  # 哨兵被删 = 重烤了
    meta = json.loads((Path(ext) / "meta.json").read_text(encoding="utf-8"))
    assert meta["bridge_port"] == 8780

def test_ensure_ext_skips_default_or_no_port(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert _ensure_human_dom_ext("", 8779) is None          # 默认日常 profile(无 profile) 不烤
    assert _ensure_human_dom_ext("~/.fleet/op-x", None) is None  # 无桥端口不烤


# --- P0-A(AgentHub #100): 确定性装扩展 —— debug 端口 + CDP loadUnpacked ---
from capabilities.browser import _human_browser as _hb

def test_launch_args_remote_debug_adds_ephemeral_port():
    args = _human_launch_args("/c", "/udd", "Default", "http://x", remote_debug=True)
    assert "--remote-debugging-port=0" in args   # 临时端口(写进 DevToolsActivePort)
    assert args[-1] == "http://x"                 # url 仍在最后
    assert "--user-data-dir=/udd" in args

def test_launch_args_no_remote_debug_by_default():
    args = _human_launch_args("/c", "/udd", None, "")
    assert not any("remote-debugging" in a for a in args)  # 默认不开 debug 端口

def test_maybe_load_human_dom_delegates_to_loader(monkeypatch):
    import capabilities.human_dom._loader as L
    seen = {}
    monkeypatch.setattr(L, "load_dom_extension",
                        lambda udd, ext, **kw: seen.update(udd=udd, ext=ext, kw=kw) or {"ok": True, "id": "xyz"})
    r = _hb._maybe_load_human_dom("/udd", "/ext", navigate_url="http://t")
    assert r == {"ok": True, "id": "xyz"}
    assert seen["udd"] == "/udd" and seen["ext"] == "/ext"
    assert seen["kw"] == {"navigate_url": "http://t"}  # navigate_url 透传给 loader


# --- P0/P2(AgentHub #100 桥注册阻断): 关 LocalNetworkAccessChecks 让公开页直连 localhost 桥 ---
def test_launch_args_disables_lna_for_human_dom():
    # 真机实证根因: 公开页(example.com/公众号)→localhost 桥的 WS 被 PNA/LNA gate, 弹窗+长延迟,
    # 注册不上 → locate no_tab_for_profile。remote_debug(human_dom)时关掉 LNA 检查即首启 connected。
    args = _human_launch_args("/c", "/udd", None, "http://x", remote_debug=True)
    feats = [a for a in args if a.startswith("--disable-features=")]
    assert len(feats) == 1, "只能有一个 --disable-features(Chrome 只认最后一个, 必须合并)"
    assert "LocalNetworkAccessChecks" in feats[0]
    for f in ("ChromeWhatsNewUI", "SigninPromo", "ForYouFre"):  # 首启 feature 也在同一个 flag 里
        assert f in feats[0]

def test_launch_args_no_lna_disable_without_human_dom():
    args = _human_launch_args("/c", "/udd", None, "http://x", remote_debug=False)
    feats = [a for a in args if a.startswith("--disable-features=")]
    assert len(feats) == 1 and "LocalNetworkAccessChecks" not in feats[0]


# --- P1(AgentHub #100 轮10): 抑制异常退出后的「恢复页面?」崩溃气泡 ---
def test_launch_args_hides_crash_restore_bubble():
    # 强杀 chrome 后 profile 带「未正确关闭」标记 → 下次开窗弹恢复气泡, 干扰 operator。
    # 专用 profile 两条路(human_dom 与否)都要带该 flag(异常退出兜底)。
    for rd in (True, False):
        args = _human_launch_args("/c", "/udd", None, "http://x", remote_debug=rd)
        assert "--hide-crash-restore-bubble" in args


# --- P1(AgentHub #100 轮12): 起窗后 server 侧 Win32 强制最大化(--start-maximized 被 profile 恢复覆盖) ---
def test_launch_args_start_maximized():
    # --start-maximized 作首帧提示(会被 profile 尺寸恢复覆盖, 真正强制靠 server 侧 Win32 ShowWindow)
    args = _human_launch_args("/c", "/udd", None, "http://x")
    assert "--start-maximized" in args

def test_maybe_foreground_calls_fn():
    seen = []
    ok = _hb._maybe_foreground(lambda udd, activate: seen.append((udd, activate)) or True, "/udd", True)
    assert seen == [("/udd", True)] and ok is True

def test_maybe_foreground_none_and_raise_are_safe():
    assert _hb._maybe_foreground(None, "/udd", False) is False   # 无 fn(mac/linux) → False
    assert _hb._maybe_foreground(lambda u, a: (_ for _ in ()).throw(RuntimeError("x")), "/udd", True) is False  # 抛→False

def test_init_accepts_maximize_fn():
    cap = _hb.HumanBrowserCapability(bridge_port=8779, maximize_fn=lambda u: None)
    assert cap._maximize_fn is not None
    assert _hb.HumanBrowserCapability()._maximize_fn is None  # 默认无
