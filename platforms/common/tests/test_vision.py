# platforms/common/tests/test_vision.py
import base64
import numpy as np
import cv2
from capabilities.vision._vision import VisionCapability, _probe_deps


def _noop_capture():
    return b""


def _noop_tap(x, y):
    pass


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, fn):
        self.tools[fn.__name__] = fn
        return fn


def _png_bytes_login():
    img = np.full((80, 400, 3), 255, np.uint8)
    cv2.putText(img, "LOGIN", (250, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def _png_with_green_box():
    img = np.zeros((200, 300, 3), np.uint8)
    cv2.rectangle(img, (100, 60), (140, 90), (40, 40, 40), -1)
    cv2.putText(img, "OK", (104, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def _green_template_b64():
    img = np.zeros((200, 300, 3), np.uint8)
    cv2.rectangle(img, (100, 60), (140, 90), (40, 40, 40), -1)
    cv2.putText(img, "OK", (104, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2)
    tmpl = img[60:90, 100:140].copy()
    ok, buf = cv2.imencode(".png", tmpl)
    return base64.b64encode(buf.tobytes()).decode()


# ----- Task 7: metadata + availability -----

def test_metadata():
    cap = VisionCapability(capture_fn=_noop_capture, tap_fn=_noop_tap)
    assert cap.id == "vision"
    assert cap.origin == "self-built"
    assert cap.platforms == ["windows", "macos"]
    assert cap.skill == "using-vision"
    assert cap.display_name and cap.usage_hint  # 非空发现信息


def test_availability_deps_present():
    cap = VisionCapability(capture_fn=_noop_capture, tap_fn=_noop_tap)
    ok, reason = cap.availability()
    assert ok is True and reason == ""


def test_availability_deps_missing(monkeypatch):
    monkeypatch.setattr("capabilities.vision._vision._probe_deps",
                        lambda: (False, "rapidocr/opencv 未装"))
    cap = VisionCapability(capture_fn=_noop_capture, tap_fn=_noop_tap)
    ok, reason = cap.availability()
    assert ok is False and "未装" in reason


# ----- Task 8: vision_locate -----

def test_vision_locate_finds_text():
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: None)
    m = _FakeMCP()
    names = cap.register(m)
    assert "vision_locate" in names
    r = m.tools["vision_locate"]("LOGIN")
    assert r["ok"] and r["count"] >= 1
    c0 = r["candidates"][0]
    assert "LOGIN" in c0["text"].upper()
    assert 230 <= c0["center"][0] <= 360 and 30 <= c0["center"][1] <= 70


def test_vision_locate_not_found_has_sample():
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: None)
    m = _FakeMCP()
    cap.register(m)
    r = m.tools["vision_locate"]("ZZZNOPE")
    assert r["ok"] and r["count"] == 0 and "ocr_sample" in r


# ----- Task 9: vision_tap -----

def test_vision_tap_clicks_center():
    taps = []
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: taps.append((x, y)))
    m = _FakeMCP()
    names = cap.register(m)
    assert "vision_tap" in names
    r = m.tools["vision_tap"]("LOGIN")
    assert r["ok"] and len(taps) == 1
    assert taps[0] == tuple(r["tapped"]["center"])


def test_vision_tap_not_found():
    taps = []
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: taps.append((x, y)))
    m = _FakeMCP()
    cap.register(m)
    r = m.tools["vision_tap"]("ZZZNOPE")
    assert r["ok"] is False and r["error"] == "not found" and not taps


def test_vision_tap_nth_out_of_range():
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: None)
    m = _FakeMCP()
    cap.register(m)
    r = m.tools["vision_tap"]("LOGIN", None, 9)
    assert r["ok"] is False and "range" in r["error"].lower()


# ----- Task 10: vision_locate_image -----

def test_vision_locate_image_hit():
    cap = VisionCapability(capture_fn=_png_with_green_box, tap_fn=lambda x, y: None)
    m = _FakeMCP()
    names = cap.register(m)
    assert "vision_locate_image" in names
    r = m.tools["vision_locate_image"](_green_template_b64(), None, None, 0.85)
    assert r["ok"] and r["found"] and abs(r["center"][0] - 120) <= 2


def test_vision_locate_image_requires_template():
    cap = VisionCapability(capture_fn=_png_with_green_box, tap_fn=lambda x, y: None)
    m = _FakeMCP()
    cap.register(m)
    r = m.tools["vision_locate_image"](None, None, None, 0.85)
    assert r["ok"] is False and "required" in r["error"]


# ----- code-review fixes -----

def test_vision_locate_has_ocr_ms():
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: None)
    m = _FakeMCP()
    cap.register(m)
    r = m.tools["vision_locate"]("LOGIN")
    assert r["ok"] and "ocr_ms" in r and isinstance(r["ocr_ms"], int)


def test_vision_tap_multiple_exact_is_ambiguous(monkeypatch):
    # A1: 多个 exact 命中(两个相同文字按钮)应判歧义、不点, 而非静默点第一个
    from capabilities.vision import _ocr

    def fake_ocr(_img):
        return [
            {"text": "确认", "box": [100, 20, 40, 16], "conf": 0.99},
            {"text": "确认", "box": [100, 200, 40, 16], "conf": 0.99},
        ]
    monkeypatch.setattr(_ocr, "run_ocr", fake_ocr)
    taps = []
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: taps.append((x, y)))
    m = _FakeMCP()
    cap.register(m)
    r = m.tools["vision_tap"]("确认")
    assert r["ok"] is False and r["error"] == "ambiguous" and not taps
    assert len(r["candidates"]) == 2


def test_vision_tap_single_exact_among_others_taps(monkeypatch):
    # 恰好 1 个 exact(混在若干 contains 里)→ 自动点该 exact
    from capabilities.vision import _ocr

    def fake_ocr(_img):
        return [
            {"text": "提交订单", "box": [100, 20, 80, 16], "conf": 0.95},   # contains
            {"text": "提交", "box": [300, 200, 40, 16], "conf": 0.99},       # exact
        ]
    monkeypatch.setattr(_ocr, "run_ocr", fake_ocr)
    taps = []
    cap = VisionCapability(capture_fn=_png_bytes_login, tap_fn=lambda x, y: taps.append((x, y)))
    m = _FakeMCP()
    cap.register(m)
    r = m.tools["vision_tap"]("提交")
    assert r["ok"] and r["tapped"]["text"] == "提交" and len(taps) == 1
