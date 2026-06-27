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
