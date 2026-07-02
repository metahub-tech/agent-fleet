import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._human_dom import compute_status, build_status


def _bake(root, pid, port, loaded=False):
    d = root / pid; d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({"profile_id": pid, "bridge_port": port}))
    if loaded:  # 模拟 _loader 装成功写的标记
        (d / "loaded.json").write_text(json.dumps({"loaded": True, "extid": "x"}))
    return d


def test_status_filters_by_port_and_marks_connected(tmp_path):
    root = tmp_path / "human-dom-ext"
    for pid, port in [("a-1", 8779), ("b-2", 8779), ("c-3", 8780)]:
        _bake(root, pid, port, loaded=True)
    out = compute_status(ext_root=str(root), self_bridge_port=8779, connected_ids={"a-1"})
    ids = {p["profile_id"]: p for p in out}
    assert set(ids) == {"a-1", "b-2"}  # 只列本 server 桥端口(8779)的
    assert ids["a-1"]["connected"] is True and ids["b-2"]["connected"] is False
    assert all(p["installed"] for p in out)


# --- P0-B(AgentHub #100): installed 维度 = 查 loaded.json 标记(装成功即写, 比 Chrome
#     Secure Preferences 的惰性 flush 可靠) ---

def test_installed_true_when_loaded_marker_present(tmp_path):
    root = tmp_path / "human-dom-ext"
    _bake(root, "a-1", 8779, loaded=True)
    out = compute_status(str(root), 8779, connected_ids=set())
    p = {x["profile_id"]: x for x in out}["a-1"]
    assert p["installed"] is True and p["connected"] is False


def test_installed_false_when_baked_but_not_loaded(tmp_path):
    # 烤了副本但还没经 CDP 装进 Chrome(无 loaded.json) → installed=False(不是「已装」)
    root = tmp_path / "human-dom-ext"
    _bake(root, "b-2", 8779, loaded=False)
    out = compute_status(str(root), 8779, connected_ids=set())
    assert {x["profile_id"]: x for x in out}["b-2"]["installed"] is False


def test_build_status_aggregates_and_hints_installed_not_connected():
    profiles = [{"profile_id": "a-1", "installed": True, "connected": False, "bridge_port": 8779}]
    s = build_status(profiles)
    assert s["installed"] is True and s["connected"] is False
    assert s["profiles"] == profiles
    assert "不要重复装" in s["hint"] and "human_browser_open" in s["hint"]


def test_build_status_all_ready_hint():
    profiles = [{"profile_id": "a-1", "installed": True, "connected": True, "bridge_port": 8779}]
    s = build_status(profiles)
    assert s["installed"] is True and s["connected"] is True
    assert "就绪" in s["hint"]


def test_build_status_empty_hint():
    s = build_status([])
    assert s["installed"] is False and s["connected"] is False and s["profiles"] == []
    assert "自动" in s["hint"]
