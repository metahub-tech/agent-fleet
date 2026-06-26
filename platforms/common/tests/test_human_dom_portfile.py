import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom._portfile import resolve_bridge_port

def test_explicit_override_wins_and_persists(tmp_path):
    pf = tmp_path / "p"
    assert resolve_bridge_port(8766, override=9000, portfile=str(pf), is_free=lambda p: True) == 9000
    assert pf.read_text().strip() == "9000"

def test_derive_port_plus_13(tmp_path):
    assert resolve_bridge_port(8766, portfile=str(tmp_path/"p"), is_free=lambda p: True) == 8779

def test_scan_forward_when_taken(tmp_path):
    taken = {8779, 8780}
    assert resolve_bridge_port(8766, portfile=str(tmp_path/"p"), is_free=lambda p: p not in taken) == 8781

def test_persisted_stable_when_bindable(tmp_path):
    pf = tmp_path / "p"; pf.write_text("8790")
    assert resolve_bridge_port(8766, portfile=str(pf), is_free=lambda p: True) == 8790

def test_persisted_taken_falls_back_to_derive(tmp_path):
    pf = tmp_path / "p"; pf.write_text("8790")
    assert resolve_bridge_port(8766, portfile=str(pf), is_free=lambda p: p != 8790) == 8779
