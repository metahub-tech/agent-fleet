import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._human_dom import compute_status

def test_status_filters_by_port_and_marks_connected(tmp_path):
    root = tmp_path / "human-dom-ext"
    for pid, port in [("a-1", 8779), ("b-2", 8779), ("c-3", 8780)]:
        d = root / pid; d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"profile_id": pid, "bridge_port": port}))
    out = compute_status(ext_root=str(root), self_bridge_port=8779, connected_ids={"a-1"})
    ids = {p["profile_id"]: p for p in out}
    assert set(ids) == {"a-1", "b-2"}
    assert ids["a-1"]["connected"] is True and ids["b-2"]["connected"] is False
    assert all(p["installed"] for p in out)


# --- P0-B(AgentHub #100): installed 维度 = 查该 profile 的 Secure Preferences ---
import os
from capabilities.human_dom._human_dom import build_status


def _bake_meta(root, pid, port, udd=None, profile_dir=None):
    d = root / pid; d.mkdir(parents=True, exist_ok=True)
    meta = {"profile_id": pid, "bridge_port": port}
    if udd is not None: meta["udd"] = str(udd)
    if profile_dir is not None: meta["profile_dir"] = profile_dir
    (d / "meta.json").write_text(json.dumps(meta))


def test_installed_true_when_secure_prefs_has_ext(tmp_path):
    root = tmp_path / "human-dom-ext"
    udd = tmp_path / "udd-a"
    (udd / "Default").mkdir(parents=True)
    # 模拟 CDP loadUnpacked 写进 Secure Preferences 的 source path(含 human-dom-ext/<pid>)
    (udd / "Default" / "Secure Preferences").write_text(
        json.dumps({"extensions": {"settings": {"abc": {
            "path": str(root / "a-1").replace("\\", "\\\\")}}}}))
    _bake_meta(root, "a-1", 8779, udd=udd)
    out = compute_status(str(root), 8779, connected_ids=set())
    p = {x["profile_id"]: x for x in out}["a-1"]
    assert p["installed"] is True and p["connected"] is False


def test_installed_false_when_secure_prefs_missing_ext(tmp_path):
    root = tmp_path / "human-dom-ext"
    udd = tmp_path / "udd-b"
    (udd / "Default").mkdir(parents=True)
    (udd / "Default" / "Secure Preferences").write_text(json.dumps({"extensions": {"settings": {}}}))
    _bake_meta(root, "b-2", 8779, udd=udd)
    out = compute_status(str(root), 8779, connected_ids=set())
    assert {x["profile_id"]: x for x in out}["b-2"]["installed"] is False


def test_installed_fallback_true_when_meta_lacks_udd(tmp_path):
    # 旧 meta(无 udd) → 兜底用 baked-existence(不回归旧行为)
    root = tmp_path / "human-dom-ext"
    _bake_meta(root, "c-3", 8779)  # 无 udd
    out = compute_status(str(root), 8779, connected_ids=set())
    assert {x["profile_id"]: x for x in out}["c-3"]["installed"] is True


def test_build_status_aggregates_and_hints_installed_not_connected():
    profiles = [{"profile_id": "a-1", "installed": True, "connected": False, "bridge_port": 8779}]
    s = build_status(profiles)
    assert s["installed"] is True and s["connected"] is False
    assert s["profiles"] == profiles
    assert "不要重复装" in s["hint"] and "human_browser_open" in s["hint"]


def test_build_status_empty_hint():
    s = build_status([])
    assert s["installed"] is False and s["connected"] is False and s["profiles"] == []
    assert "自动" in s["hint"]
