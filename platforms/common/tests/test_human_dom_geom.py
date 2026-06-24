import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capabilities"))
from human_dom._geom import viewport_to_screen, top_chrome_px

GEOM = {"screenX": 100, "screenY": 80, "innerW": 1200, "innerH": 800,
        "outerW": 1200, "outerH": 888, "dpr": 2, "scrollX": 0, "scrollY": 500}

def test_top_chrome_px_is_outer_minus_inner():
    assert top_chrome_px(GEOM) == 88

def test_center_maps_screenX_plus_rect_no_dpr():
    rect = {"left": 40, "top": 60, "width": 100, "height": 20}
    out = viewport_to_screen(rect, GEOM)
    assert out["center"] == [190.0, 238.0]
    assert out["box"] == [140.0, 228.0, 100, 20]

def test_rect_already_scroll_relative_no_scroll_subtraction():
    rect = {"left": 0, "top": 0, "width": 10, "height": 10}
    out = viewport_to_screen(rect, GEOM)
    assert out["center"] == [105.0, 173.0]
