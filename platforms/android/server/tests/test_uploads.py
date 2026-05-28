"""Unit tests for _uploads.py (agent → device-host staging → phone 上传支撑逻辑)."""
import base64
import sys
import threading as _t
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import _uploads as up


# ----- Task 1: 骨架 + 常量 + 目录 -----

def test_constants_and_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "uploads" / "jobs")
    up.ensure_dirs()
    assert (tmp_path / "uploads" / "jobs").is_dir()
    assert up.SYNC_B64_MAX == 6 * 1024 * 1024
    assert up.MIN_FREE_BYTES == 500 * 1024 * 1024


# ----- Task 2: 校验 helper -----

def test_require_xor():
    up.require_xor("a", None, ("content_base64", "url"))       # ok
    up.require_xor(None, "b", ("content_base64", "url"))       # ok
    with pytest.raises(up.UploadError):
        up.require_xor("a", "b", ("content_base64", "url"))    # both
    with pytest.raises(up.UploadError):
        up.require_xor(None, None, ("content_base64", "url"))  # neither


def test_decode_b64():
    assert up.decode_b64(base64.b64encode(b"hi").decode()) == b"hi"
    with pytest.raises(up.UploadError):
        up.decode_b64("not!!base64")


def test_sanitize_filename():
    assert up.sanitize_filename("bg.jpg") == "bg.jpg"
    with pytest.raises(up.UploadError):
        up.sanitize_filename("../etc/passwd")
    with pytest.raises(up.UploadError):
        up.sanitize_filename("a/b.png")
    with pytest.raises(up.UploadError):
        up.sanitize_filename("")


def test_validate_device_path():
    assert up.validate_device_path("/sdcard/Pictures/x.jpg") == "/sdcard/Pictures/x.jpg"
    assert up.validate_device_path("/storage/emulated/0/Download/x") == "/storage/emulated/0/Download/x"
    with pytest.raises(up.UploadError):
        up.validate_device_path("/data/local/tmp/x")     # 前缀不允许
    with pytest.raises(up.UploadError):
        up.validate_device_path("/sdcard/../data/x")     # 穿越


def test_validate_url_scheme_and_ssrf():
    up.validate_url("https://example.com/a.jpg")          # ok（公网域名）
    with pytest.raises(up.UploadError):
        up.validate_url("ftp://example.com/a")            # scheme
    with pytest.raises(up.UploadError):
        up.validate_url("http://127.0.0.1/a")             # loopback
    with pytest.raises(up.UploadError):
        up.validate_url("http://169.254.169.254/latest")  # 元数据


def test_is_image():
    assert up.is_image("a.JPG") is True
    assert up.is_image("a.png") is True
    assert up.is_image("a.apk") is False


def test_filename_rejects_injection_chars():
    for bad in ["it's.jpg", 'a";b', "x;rm.png", "a$b", "a`b`", "a\nb"]:
        with pytest.raises(up.UploadError):
            up.sanitize_filename(bad)


def test_device_path_rejects_injection_chars():
    # 单引号会破坏 content query --where 的 SQL 字面量
    with pytest.raises(up.UploadError):
        up.validate_device_path("/sdcard/Pictures/it's.jpg")
    with pytest.raises(up.UploadError):
        up.validate_device_path("/sdcard/Pictures/a;b.jpg")
    with pytest.raises(up.UploadError):
        up.validate_device_path("/sdcard/Pictures/a\\b.jpg")


def test_ip_is_blocked():
    assert up._ip_is_blocked("127.0.0.1") is True
    assert up._ip_is_blocked("10.1.2.3") is True
    assert up._ip_is_blocked("169.254.169.254") is True
    assert up._ip_is_blocked("8.8.8.8") is False
    assert up._ip_is_blocked("not-an-ip") is False


# ----- HTTP /upload helpers -----

def test_parse_bool():
    assert up.parse_bool(None, True) is True
    assert up.parse_bool(None, False) is False
    assert up.parse_bool("true") is True
    assert up.parse_bool("1") is True
    assert up.parse_bool("YES") is True
    assert up.parse_bool("false") is False
    assert up.parse_bool("0") is False


def test_resolve_upload_target_with_device_path():
    fname, dpath = up.resolve_upload_target("/sdcard/Pictures/a.png", None)
    assert dpath == "/sdcard/Pictures/a.png" and fname == "a.png"


def test_resolve_upload_target_filename_only_image_vs_other():
    # 图片默认进 Pictures，其它进 Download
    _, dpath_img = up.resolve_upload_target(None, "pic.jpg")
    assert dpath_img == "/sdcard/Pictures/pic.jpg"
    _, dpath_apk = up.resolve_upload_target(None, "app.apk")
    assert dpath_apk == "/sdcard/Download/app.apk"


def test_resolve_upload_target_requires_one():
    with pytest.raises(up.UploadError):
        up.resolve_upload_target(None, None)
    # 路径穿越仍被拒
    with pytest.raises(up.UploadError):
        up.resolve_upload_target("/data/local/tmp/x", None)


# ----- Task 3: 分片暂存 + 空间守卫 -----

def _patch_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "u")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "u" / "jobs")
    up.ensure_dirs()


def test_staging_chunks(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    sid = up.new_stage("big.apk")
    r1 = up.append_chunk(sid, b"AAAA", last=False)
    assert r1["bytes_received"] == 4 and r1["complete"] is False
    r2 = up.append_chunk(sid, b"BB", last=True)
    assert r2["bytes_received"] == 6 and r2["complete"] is True
    assert up.stage_is_complete(sid) is True
    assert up.stage_path(sid).read_bytes() == b"AAAABB"
    assert up.stage_filename(sid) == "big.apk"


def test_append_unknown_stage(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    with pytest.raises(up.UploadError):
        up.append_chunk("nonexistent", b"x", last=False)


def test_free_space_guard(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "_free_bytes", lambda: up.MIN_FREE_BYTES - 1)
    with pytest.raises(up.UploadError):
        up.new_stage("x.bin")


# ----- Task 4: adb 命令构造器 -----

def test_command_builders():
    assert up.push_args("S", "/host/x.jpg", "/sdcard/Pictures/x.jpg") == \
        ["-s", "S", "push", "/host/x.jpg", "/sdcard/Pictures/x.jpg"]
    assert up.media_scan_args("/sdcard/Pictures/x.jpg") == \
        ["shell", "am", "broadcast", "-a",
         "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
         "-d", "file:///sdcard/Pictures/x.jpg"]
    ins = up.media_insert_args("/sdcard/Pictures/x.jpg")
    assert ins[:3] == ["shell", "content", "insert"]
    assert "content://media/external/images/media" in ins
    assert up.install_args("S", "/host/app.apk", replace=True) == \
        ["-s", "S", "install", "-r", "/host/app.apk"]
    assert up.install_args("S", "/host/app.apk", replace=False) == \
        ["-s", "S", "install", "/host/app.apk"]


def test_canonical_data_path():
    # MediaStore 存 /storage/emulated/0/...，查询必须用规范形式而非 /sdcard/...
    assert up.canonical_data_path("/sdcard/Pictures/x.jpg") == "/storage/emulated/0/Pictures/x.jpg"
    assert up.canonical_data_path("/storage/emulated/0/Pictures/x.jpg") == "/storage/emulated/0/Pictures/x.jpg"


def test_mediastore_query_args_uses_canonical_path():
    args = up.mediastore_query_args("/sdcard/Pictures/x.jpg")
    assert "_data='/storage/emulated/0/Pictures/x.jpg'" in args
    assert "content://media/external/images/media" in args
    # 绝不能用 /sdcard/ 形式（那会假阴性）
    assert all("/sdcard/" not in a for a in args)


# ----- Task 5: url 下载 -----

import functools
import http.server


def _serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_download_url_ok(tmp_path, monkeypatch):
    (tmp_path / "a.bin").write_bytes(b"X" * 100)
    srv, port = _serve(tmp_path)
    monkeypatch.setattr(up, "_is_blocked_ip", lambda h: False)   # 放行 127.0.0.1 仅为测试
    monkeypatch.setattr(up, "_ip_is_blocked", lambda ip: False)  # 同时放行 peer-recheck
    dest = tmp_path / "out.bin"
    try:
        n = up.download_url(f"http://127.0.0.1:{port}/a.bin", dest, max_bytes=1000)
        assert n == 100 and dest.read_bytes() == b"X" * 100
    finally:
        srv.shutdown()


def test_download_url_over_limit(tmp_path, monkeypatch):
    (tmp_path / "big.bin").write_bytes(b"X" * 5000)
    srv, port = _serve(tmp_path)
    monkeypatch.setattr(up, "_is_blocked_ip", lambda h: False)
    monkeypatch.setattr(up, "_ip_is_blocked", lambda ip: False)
    try:
        with pytest.raises(up.UploadError):
            up.download_url(f"http://127.0.0.1:{port}/big.bin", tmp_path / "o", max_bytes=1000)
    finally:
        srv.shutdown()


def test_download_url_ssrf_blocked(tmp_path):
    with pytest.raises(up.UploadError):
        up.download_url("http://127.0.0.1/x", tmp_path / "o", max_bytes=1000)


# ----- Task 6: JobRegistry -----

def test_job_success_and_get():
    reg = up.JobRegistry()
    done = _t.Event()

    def work():
        return {"device_path": "/sdcard/x", "returncode": 0}

    jid = reg.submit(kind="deliver", serial="S", work=work, on_done=done.set)
    assert reg.get(jid)["state"] in ("running", "succeeded")
    assert done.wait(2)
    j = reg.get(jid)
    assert j["state"] == "succeeded" and j["returncode"] == 0 and j["finished_at"]


def test_job_failure_records_error():
    reg = up.JobRegistry()
    done = _t.Event()

    def work():
        raise RuntimeError("adb push failed")

    jid = reg.submit(kind="deliver", serial="S", work=work, on_done=done.set)
    assert done.wait(2)
    j = reg.get(jid)
    assert j["state"] == "failed" and "adb push failed" in j["error"]


def test_job_get_unknown():
    assert up.JobRegistry().get("nope") is None


def test_job_submit_with_preset_id():
    reg = up.JobRegistry()
    done = _t.Event()
    jid = reg.submit(kind="deliver", serial="S", work=lambda: {}, on_done=done.set, job_id="fixed123")
    assert jid == "fixed123"
    assert done.wait(2)
    assert reg.get("fixed123")["state"] == "succeeded"


# ----- Task 7: 后台进程 runner + PID + 清场 -----

def test_run_proc_writes_and_removes_pid(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr(up, "ADB_BIN", "/bin/true")
    rc, _out, _err = up.run_proc("job1", ["whatever"])  # /bin/true 忽略参数，立即退出 0
    assert rc == 0
    assert not (up.JOBS_DIR / "job1.pid").exists()


def test_reap_orphans_kills_live_pid(tmp_path, monkeypatch):
    _patch_dirs(tmp_path, monkeypatch)
    import subprocess
    p = subprocess.Popen(["sleep", "30"])
    (up.JOBS_DIR / "stale.pid").write_text(str(p.pid))
    (up.UPLOADS_DIR / "leftover.part").write_text("x")
    up.reap_orphans()
    p.wait(timeout=5)                       # 被 reap 杀掉
    assert not (up.JOBS_DIR / "stale.pid").exists()
    assert not (up.UPLOADS_DIR / "leftover.part").exists()
