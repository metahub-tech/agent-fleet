# platforms/common/tests/test_vision_locate.py
import numpy as np
import cv2
from capabilities.vision import _locate


def test_decode_png_roundtrip():
    img = np.zeros((10, 20, 3), np.uint8)
    img[:, :, 2] = 255  # red
    ok, buf = cv2.imencode(".png", img)
    out = _locate.decode_png(buf.tobytes())
    assert out.shape == (10, 20, 3)
    assert int(out[0, 0, 2]) == 255


def test_crop_region_offset():
    img = np.zeros((100, 200, 3), np.uint8)
    cropped, offset = _locate.crop_region(img, (50, 20, 150, 60))  # left,top,right,bottom
    assert cropped.shape == (40, 100, 3)
    assert offset == (50, 20)


def test_crop_region_none():
    img = np.zeros((100, 200, 3), np.uint8)
    cropped, offset = _locate.crop_region(img, None)
    assert cropped.shape == (100, 200, 3) and offset == (0, 0)


def test_sub_line_center_substring():
    # OCR 行框 box=[x,y,w,h]=[100,20,200,16], 识别文本 "330 points by Max", 找 "by"
    # "by" 在第 11-12 字符(共 17 字), 比例中心 ~ (11.5/17)
    box = [100, 20, 200, 16]
    cx, cy = _locate.sub_line_center(box, "330 points by Max", "by")
    assert 220 <= cx <= 260      # 100 + 200*(~0.676) ≈ 235
    assert cy == 28              # 20 + 16/2


def test_sub_line_center_fallback_whole_line():
    box = [100, 20, 200, 16]
    cx, cy = _locate.sub_line_center(box, "登录", "登录")  # query==whole text
    assert cx == 200 and cy == 28  # 整行中心


def test_sub_line_center_not_found_fallback():
    box = [100, 20, 200, 16]
    cx, cy = _locate.sub_line_center(box, "abc", "zzz")  # 不在文本里 → 整行中心
    assert cx == 200 and cy == 28


def _items():
    # 归一 OCR 项 {text, box:[x,y,w,h], conf}
    return [
        {"text": "登录", "box": [1180, 20, 40, 16], "conf": 0.99},      # exact
        {"text": "登录注册", "box": [1180, 50, 80, 16], "conf": 0.95},  # contains
        {"text": "用户登录页", "box": [300, 200, 100, 16], "conf": 0.9}, # contains
    ]


def test_rank_exact_first_and_center():
    c = _locate.rank_candidates(_items(), "登录", offset=(0, 0), max_results=20)
    assert c[0]["text"] == "登录" and c[0]["match_field"] == "exact"
    assert c[0]["score"] == 1.0
    assert c[0]["center"] == [1200, 28]   # 1180+40/2, 20+16/2


def test_rank_offset_added():
    c = _locate.rank_candidates(_items()[:1], "登录", offset=(50, 10), max_results=20)
    assert c[0]["center"] == [1250, 38]


def test_rank_no_match_empty():
    assert _locate.rank_candidates(_items(), "zzz", offset=(0, 0), max_results=20) == []


def test_rank_max_results_truncates():
    items = [{"text": f"go{i}", "box": [i, 0, 10, 10], "conf": 0.9} for i in range(30)]
    c = _locate.rank_candidates(items, "go", offset=(0, 0), max_results=5)
    assert len(c) == 5


def _textured_img():
    # 有纹理的图标块(TM_CCOEFF_NORMED 对均匀块退化, 故加文字纹理); 块中心=(120,75)
    img = np.zeros((200, 300, 3), np.uint8)
    cv2.rectangle(img, (100, 60), (140, 90), (40, 40, 40), -1)
    cv2.putText(img, "OK", (104, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2)
    return img


def test_match_template_same_scale_hit():
    img = _textured_img()
    tmpl = img[60:90, 100:140].copy()
    r = _locate.match_template(img, tmpl, threshold=0.85, offset=(0, 0))
    assert r["found"] is True
    assert abs(r["center"][0] - 120) <= 2 and abs(r["center"][1] - 75) <= 2
    assert r["score"] > 0.95


def test_match_template_offset():
    img = _textured_img()
    tmpl = img[60:90, 100:140].copy()
    r = _locate.match_template(img, tmpl, threshold=0.85, offset=(10, 5))
    assert abs(r["center"][0] - 130) <= 2 and abs(r["center"][1] - 80) <= 2


def test_match_template_below_threshold():
    # 有纹理模板(有方差→matchTemplate 良定义), 但目标图里没有 → 低分
    img = np.zeros((200, 300, 3), np.uint8)
    tmpl = _textured_img()[60:90, 100:140].copy()  # "OK" 图标, 不在全黑图里
    r = _locate.match_template(img, tmpl, threshold=0.85, offset=(0, 0))
    assert r["found"] is False and "best_score" in r


def test_rank_candidates_exposes_ocr_conf():
    # R5: 候选透出 OCR 检测置信度 ocr_conf, 保留 match 质量 score
    items = [{"text": "登录", "box": [10, 20, 40, 18], "conf": 0.87}]
    cands = _locate.rank_candidates(items, "登录")
    assert cands[0]["ocr_conf"] == 0.87
    assert cands[0]["score"] == 1.0            # 既有 match 质量(exact)不变
    assert cands[0]["match_field"] == "exact"


def test_rank_candidates_ocr_conf_defaults_when_missing():
    # 无 conf → 防御默认 0.0, 不 KeyError
    items = [{"text": "登录", "box": [10, 20, 40, 18]}]
    cands = _locate.rank_candidates(items, "登录")
    assert cands[0]["ocr_conf"] == 0.0
