# Android Agent 文件上传 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 agent 把自己持有的字节(base64/url)上传到安卓手机,小图同步进相册、大文件/APK 走主机暂存 + 后台任务 + 轮询,绕开 25s 传输上限。

**Architecture:** 纯逻辑(校验/暂存/命令构造/url 下载/job 注册表)集中到新模块 `_uploads.py`,可注入 adb runner 便于单测;`android_device_mcp.py` 只加 4 个薄 `@mcp.tool` 包装(`upload_media`/`stage_upload`/`deliver_staged`/`job_status`)接线真实 adb。后台 `adb push`/`install` 用 `subprocess.Popen` 在守护线程跑(不经 `_adb_run` 的 25s `min()` 钳制),PID 落盘以便 server 重启清场。

**Tech Stack:** Python 3.10+, fastmcp, pydantic, 标准库 `urllib.request`/`socket`/`ipaddress`/`subprocess`/`threading`/`base64`/`uuid`(**不引入新依赖**),pytest。

设计依据:`docs/internal/design/2026-05-28-android-agent-file-upload-design.md`。

---

## File Structure

- **Create** `platforms/android/server/_uploads.py` — 全部纯逻辑 + JobRegistry。
- **Modify** `platforms/android/server/android_device_mcp.py` — 4 个 `@mcp.tool` 薄包装 + 启动时 `reap_orphans()`。
- **Create** `platforms/android/server/tests/test_uploads.py` — 单测。
- **Modify** `platforms/android/server/tests/test_tool_signatures.py` — 工具计数 25 → 29、工具名清单补 4 个。
- **Modify** docs:android 工具清单 + 计数、`using-android` skill、`CHANGELOG.md`。

约定:测试 `import` 方式沿用现有 `sys.path.insert(0, parent)`;`_uploads.py` 不在导入期碰真实 adb/网络/磁盘——所有副作用走函数参数注入或显式调用。

---

## Task 1: 模块骨架 + 常量 + 目录

**Files:**
- Create: `platforms/android/server/_uploads.py`
- Test: `platforms/android/server/tests/test_uploads.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_uploads.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import _uploads as up


def test_constants_and_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "uploads" / "jobs")
    up.ensure_dirs()
    assert (tmp_path / "uploads" / "jobs").is_dir()
    assert up.SYNC_B64_MAX == 6 * 1024 * 1024
    assert up.MIN_FREE_BYTES == 500 * 1024 * 1024
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd platforms/android/server && python -m pytest tests/test_uploads.py::test_constants_and_dirs -v`
Expected: FAIL（`ModuleNotFoundError: _uploads` 或 `AttributeError`）

- [ ] **Step 3: 最小实现**

```python
# _uploads.py
"""agent → device-host staging → phone 上传支撑逻辑（纯逻辑 + 后台 job）。

设计：docs/internal/design/2026-05-28-android-agent-file-upload-design.md
不在导入期触碰 adb/网络/磁盘；副作用经参数注入或显式调用。
"""
from __future__ import annotations

import base64
import ipaddress
import shutil
import socket
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

UPLOADS_DIR = Path.home() / ".agent-fleet" / "uploads"
JOBS_DIR = UPLOADS_DIR / "jobs"

SYNC_B64_MAX = 6 * 1024 * 1024          # upload_media: base64 解码后字节上限
SYNC_URL_MAX_USB = 20 * 1024 * 1024     # upload_media: USB 同步 url 上限
SYNC_URL_MAX_WIRELESS = 8 * 1024 * 1024 # upload_media: 无线同步 url 上限（保守默认）
URL_HARD_MAX = 200 * 1024 * 1024        # 任何 url 下载硬上限
MIN_FREE_BYTES = 500 * 1024 * 1024      # 暂存目录可用空间低于此值拒绝新会话/job
STAGE_TTL_SEC = 1800                    # 分片会话 30min 未收尾即可回收
JOB_TTL_SEC = 3600                      # 完成态 job 1h 后回收

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}
ALLOWED_DEVICE_PREFIXES = ("/sdcard/", "/storage/emulated/0/")


class UploadError(ValueError):
    """入参/校验错误，工具层转成 {ok: false, error}。"""


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd platforms/android/server && python -m pytest tests/test_uploads.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add platforms/android/server/_uploads.py platforms/android/server/tests/test_uploads.py
git commit -m "feat(android-upload): _uploads 模块骨架 + 常量 + 暂存目录"
```

---

## Task 2: 校验 helper（异或/base64/文件名/设备路径/url/图片判定）

**Files:**
- Modify: `platforms/android/server/_uploads.py`
- Test: `platforms/android/server/tests/test_uploads.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest

def test_require_xor():
    up.require_xor("a", None, ("content_base64", "url"))      # ok
    with pytest.raises(up.UploadError):
        up.require_xor("a", "b", ("content_base64", "url"))   # both
    with pytest.raises(up.UploadError):
        up.require_xor(None, None, ("content_base64", "url")) # neither

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

def test_validate_device_path():
    assert up.validate_device_path("/sdcard/Pictures/x.jpg") == "/sdcard/Pictures/x.jpg"
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
    assert up.is_image("a.apk") is False
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd platforms/android/server && python -m pytest tests/test_uploads.py -v`
Expected: FAIL（`AttributeError: require_xor` 等）

- [ ] **Step 3: 最小实现（追加到 `_uploads.py`）**

```python
def require_xor(a, b, names: tuple[str, str]) -> None:
    if (a is None) == (b is None):
        raise UploadError(f"必须且只能提供 {names[0]} 与 {names[1]} 之一")

def decode_b64(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=True)
    except Exception as e:
        raise UploadError(f"base64 解码失败: {e}") from e

def sanitize_filename(name: str) -> str:
    if not name or "/" in name or "\\" in name or ".." in name:
        raise UploadError(f"非法 filename: {name!r}")
    return name

def validate_device_path(path: str) -> str:
    if ".." in path or not path.startswith(ALLOWED_DEVICE_PREFIXES):
        raise UploadError(f"device_path 必须在 {ALLOWED_DEVICE_PREFIXES} 内且不含 '..': {path!r}")
    return path

def _is_blocked_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False  # 解析失败交给下载阶段报错
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
            return True
    return False

def validate_url(url: str) -> None:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise UploadError(f"仅支持 http/https: {url!r}")
    if not p.hostname:
        raise UploadError(f"url 缺少 host: {url!r}")
    if _is_blocked_ip(p.hostname):
        raise UploadError(f"拒绝内网/元数据地址: {p.hostname}")

def is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTS
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd platforms/android/server && python -m pytest tests/test_uploads.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add platforms/android/server/_uploads.py platforms/android/server/tests/test_uploads.py
git commit -m "feat(android-upload): 校验 helper（异或/base64/路径穿越/SSRF）"
```

---

## Task 3: 暂存（分片会话 + 空间检查）

**Files:**
- Modify: `platforms/android/server/_uploads.py`
- Test: `platforms/android/server/tests/test_uploads.py`

- [ ] **Step 1: 写失败测试**

```python
def test_staging_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "u")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "u" / "jobs")
    up.ensure_dirs()
    sid = up.new_stage("big.apk")
    r1 = up.append_chunk(sid, b"AAAA", last=False)
    assert r1["bytes_received"] == 4 and r1["complete"] is False
    r2 = up.append_chunk(sid, b"BB", last=True)
    assert r2["bytes_received"] == 6 and r2["complete"] is True
    assert up.stage_is_complete(sid) is True
    assert up.stage_path(sid).read_bytes() == b"AAAABB"

def test_append_unknown_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "u")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "u" / "jobs")
    up.ensure_dirs()
    with pytest.raises(up.UploadError):
        up.append_chunk("nonexistent", b"x", last=False)

def test_free_space_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "u")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "u" / "jobs")
    up.ensure_dirs()
    monkeypatch.setattr(up, "_free_bytes", lambda: up.MIN_FREE_BYTES - 1)
    with pytest.raises(up.UploadError):
        up.new_stage("x.bin")
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd platforms/android/server && python -m pytest tests/test_uploads.py -v`
Expected: FAIL

- [ ] **Step 3: 最小实现（追加）**

```python
def _free_bytes() -> int:
    return shutil.disk_usage(UPLOADS_DIR.parent if not UPLOADS_DIR.exists() else UPLOADS_DIR).free

def _check_space() -> None:
    if _free_bytes() < MIN_FREE_BYTES:
        raise UploadError("暂存目录可用空间不足（< 500MB），拒绝新上传")

def _stage_meta(stage_id: str) -> Path:
    return UPLOADS_DIR / f"{stage_id}.done"

def new_stage(filename: str) -> str:
    _check_space()
    ensure_dirs()
    stage_id = uuid.uuid4().hex
    safe = sanitize_filename(filename)
    # 记录原始文件名供后续命名
    (UPLOADS_DIR / f"{stage_id}.name").write_text(safe)
    stage_path(stage_id).touch()
    return stage_id

def stage_path(stage_id: str) -> Path:
    return UPLOADS_DIR / f"{stage_id}.part"

def stage_filename(stage_id: str) -> str:
    f = UPLOADS_DIR / f"{stage_id}.name"
    return f.read_text() if f.exists() else f"{stage_id}.bin"

def append_chunk(stage_id: str, data: bytes, last: bool) -> dict:
    p = stage_path(stage_id)
    if not p.exists():
        raise UploadError(f"未知 stage_id: {stage_id}")
    with p.open("ab") as fh:
        fh.write(data)
    if last:
        _stage_meta(stage_id).touch()
    return {"bytes_received": p.stat().st_size, "complete": last}

def stage_is_complete(stage_id: str) -> bool:
    return _stage_meta(stage_id).exists()
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd platforms/android/server && python -m pytest tests/test_uploads.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add platforms/android/server/_uploads.py platforms/android/server/tests/test_uploads.py
git commit -m "feat(android-upload): 分片暂存会话 + 空间守卫"
```

---

## Task 4: adb 命令构造器（push / media-scan / 兜底 insert / install）

**Files:**
- Modify: `platforms/android/server/_uploads.py`
- Test: `platforms/android/server/tests/test_uploads.py`

纯函数：只构造 adb 参数列表（不执行），保证用列表参数、文件名安全传递。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd platforms/android/server && python -m pytest tests/test_uploads.py -v`
Expected: FAIL

- [ ] **Step 3: 最小实现（追加）**

```python
def push_args(serial: str, host_path: str, device_path: str) -> list[str]:
    return ["-s", serial, "push", host_path, device_path]

def install_args(serial: str, apk_path: str, replace: bool = True) -> list[str]:
    args = ["-s", serial, "install"]
    if replace:
        args.append("-r")
    args.append(apk_path)
    return args

def media_scan_args(device_path: str) -> list[str]:
    # 列表参数逐项传；file://<path> 整体作为一个 arg，避免设备端 shell 再切分
    return ["shell", "am", "broadcast", "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d", f"file://{device_path}"]

def media_insert_args(device_path: str) -> list[str]:
    # 兜底：经 adb shell content（shell uid，绕过 Android10+ MANAGE_MEDIA 限制）直插 MediaStore
    return ["shell", "content", "insert",
            "--uri", "content://media/external/images/media",
            "--bind", f"_data:s:{device_path}",
            "--bind", "mime_type:s:image/jpeg"]
```

- [ ] **Step 4: 运行,确认通过 / Step 5: 提交**

Run: `cd platforms/android/server && python -m pytest tests/test_uploads.py -v` → PASS

```bash
git add platforms/android/server/_uploads.py platforms/android/server/tests/test_uploads.py
git commit -m "feat(android-upload): adb 命令构造器（push/scan/insert/install）"
```

---

## Task 5: url 下载（urllib + SSRF + 大小上限）

**Files:**
- Modify: `platforms/android/server/_uploads.py`
- Test: `platforms/android/server/tests/test_uploads.py`

- [ ] **Step 1: 写失败测试（用本地 http server，不出网）**

```python
import http.server, threading as _t, functools

def _serve(tmp_path):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    srv = http.server.HTTPServer(("127.0.0.1", 0), h)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]

def test_download_url_ok(tmp_path, monkeypatch):
    (tmp_path / "a.bin").write_bytes(b"X" * 100)
    srv, port = _serve(tmp_path)
    monkeypatch.setattr(up, "_is_blocked_ip", lambda h: False)  # 放行 127.0.0.1 仅为测试
    dest = tmp_path / "out.bin"
    n = up.download_url(f"http://127.0.0.1:{port}/a.bin", dest, max_bytes=1000)
    assert n == 100 and dest.read_bytes() == b"X" * 100
    srv.shutdown()

def test_download_url_over_limit(tmp_path, monkeypatch):
    (tmp_path / "big.bin").write_bytes(b"X" * 5000)
    srv, port = _serve(tmp_path)
    monkeypatch.setattr(up, "_is_blocked_ip", lambda h: False)
    with pytest.raises(up.UploadError):
        up.download_url(f"http://127.0.0.1:{port}/big.bin", tmp_path / "o", max_bytes=1000)
    srv.shutdown()
```

- [ ] **Step 2: 运行,确认失败** → FAIL

- [ ] **Step 3: 最小实现（追加）**

```python
def download_url(url: str, dest: Path, max_bytes: int) -> int:
    validate_url(url)
    cap = min(max_bytes, URL_HARD_MAX)
    written = 0
    req = urllib.request.Request(url, headers={"User-Agent": "agent-fleet-android"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (scheme 已校验)
        clen = resp.headers.get("Content-Length")
        if clen and int(clen) > cap:
            raise UploadError(f"文件超过上限 {cap} 字节（Content-Length={clen}）")
        with dest.open("wb") as fh:
            while True:
                buf = resp.read(64 * 1024)
                if not buf:
                    break
                written += len(buf)
                if written > cap:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise UploadError(f"下载超过上限 {cap} 字节")
                fh.write(buf)
    return written
```

- [ ] **Step 4: 运行,确认通过 / Step 5: 提交**

Run → PASS

```bash
git add platforms/android/server/_uploads.py platforms/android/server/tests/test_uploads.py
git commit -m "feat(android-upload): url 下载（SSRF 校验 + 大小上限）"
```

---

## Task 6: JobRegistry（后台任务状态机 + 注入 work）

**Files:**
- Modify: `platforms/android/server/_uploads.py`
- Test: `platforms/android/server/tests/test_uploads.py`

后台执行通过注入的 `work()` 回调完成（生产用 Popen 包装，测试用 fake）。状态机：running → succeeded / failed。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行,确认失败** → FAIL

- [ ] **Step 3: 最小实现（追加）**

```python
class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit(self, *, kind: str, serial: str, work, on_done=None) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id, "kind": kind, "serial": serial,
                "state": "running", "started_at": time.time(), "finished_at": None,
            }
        t = threading.Thread(target=self._run, args=(job_id, work, on_done), daemon=True)
        t.start()
        return job_id

    def _run(self, job_id, work, on_done) -> None:
        try:
            result = work() or {}
            self._update(job_id, state="succeeded", **result)
        except Exception as e:  # noqa: BLE001
            self._update(job_id, state="failed", error=str(e))
        finally:
            if on_done:
                on_done()

    def _update(self, job_id, **fields) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return
            j.update(fields)
            j["finished_at"] = time.time()

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def gc(self) -> None:
        now = time.time()
        with self._lock:
            for jid in [k for k, v in self._jobs.items()
                        if v.get("finished_at") and now - v["finished_at"] > JOB_TTL_SEC]:
                del self._jobs[jid]
```

- [ ] **Step 4: 运行,确认通过 / Step 5: 提交**

Run → PASS

```bash
git add platforms/android/server/_uploads.py platforms/android/server/tests/test_uploads.py
git commit -m "feat(android-upload): JobRegistry 后台任务状态机"
```

---

## Task 7: 后台进程 runner + PID 落盘 + 孤儿清场

**Files:**
- Modify: `platforms/android/server/_uploads.py`
- Test: `platforms/android/server/tests/test_uploads.py`

`run_proc` 用 `Popen` 跑一条 adb 命令(不经 25s 钳制),写 `<job_id>.pid`,`wait()` 后删除 pid。`reap_orphans` 在 server 启动时杀掉残留 pid 并清场。

- [ ] **Step 1: 写失败测试（用 `sleep` 进程，不依赖 adb）**

```python
import os, signal

def test_run_proc_writes_and_removes_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "u")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "u" / "jobs")
    up.ensure_dirs()
    rc, _out, _err = up.run_proc("job1", ["true"])  # 立即结束
    assert rc == 0
    assert not (up.JOBS_DIR / "job1.pid").exists()

def test_reap_orphans_kills_live_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "u")
    monkeypatch.setattr(up, "JOBS_DIR", tmp_path / "u" / "jobs")
    up.ensure_dirs()
    import subprocess
    p = subprocess.Popen(["sleep", "30"])
    (up.JOBS_DIR / "stale.pid").write_text(str(p.pid))
    up.reap_orphans()
    p.wait(timeout=5)                       # 被 reap 杀掉
    assert not (up.JOBS_DIR / "stale.pid").exists()
```

- [ ] **Step 2: 运行,确认失败** → FAIL

- [ ] **Step 3: 最小实现（追加）**

```python
import subprocess

# 由 android_device_mcp 在导入后注入真实 adb 路径
ADB_BIN = "adb"

def _pid_file(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.pid"

def run_proc(job_id: str, adb_args: list[str], timeout: int | None = None) -> tuple[int, str, str]:
    """前台阻塞跑一条命令（在守护线程里调用，不经 25s 钳制）。写/删 pid。"""
    ensure_dirs()
    cmd = adb_args if adb_args[:1] == [ADB_BIN] else [ADB_BIN] + adb_args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _pid_file(job_id).write_text(str(proc.pid))
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    finally:
        _pid_file(job_id).unlink(missing_ok=True)

def reap_orphans() -> None:
    """server 启动调用：杀掉上次残留的后台子进程并清场。"""
    if not JOBS_DIR.exists():
        return
    for pf in JOBS_DIR.glob("*.pid"):
        try:
            pid = int(pf.read_text().strip())
            import os, signal
            os.kill(pid, signal.SIGKILL)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        finally:
            pf.unlink(missing_ok=True)
    # 清残留分片/临时文件
    for p in UPLOADS_DIR.glob("*.part"):
        p.unlink(missing_ok=True)
    for p in UPLOADS_DIR.glob("*.done"):
        p.unlink(missing_ok=True)
    for p in UPLOADS_DIR.glob("*.name"):
        p.unlink(missing_ok=True)
```

- [ ] **Step 4: 运行,确认通过 / Step 5: 提交**

Run → PASS

```bash
git add platforms/android/server/_uploads.py platforms/android/server/tests/test_uploads.py
git commit -m "feat(android-upload): 后台进程 runner + PID 落盘 + 孤儿清场"
```

---

## Task 8: 接线 4 个 MCP 工具 + 启动清场

**Files:**
- Modify: `platforms/android/server/android_device_mcp.py`（在 `pull_file` 之后、`UI ELEMENT INTROSPECTION` 之前插入；并在 `__main__` 启动处调用 `reap_orphans()`）

工具是薄包装：调用 `_uploads` 的纯逻辑 + `_resolve_device`/`_state_registry`,用 `_adb_run`（同步小操作）或 `JobRegistry.submit` + `run_proc`（异步）。

- [ ] **Step 1: 在 import 区加入**

```python
import _uploads as up
up.ADB_BIN = _ADB
_job_registry = up.JobRegistry()
```

- [ ] **Step 2: 在 `pull_file` 之后插入 4 个工具**

```python
@mcp.tool
def upload_media(
    content_base64: Annotated[str | None, Field(description="文件字节的 base64；与 url 二选一")] = None,
    url: Annotated[str | None, Field(description="http/https 链接；与 content_base64 二选一")] = None,
    device_path: Annotated[str | None, Field(description="设备目标路径；缺省 /sdcard/Pictures/<filename>")] = None,
    filename: Annotated[str | None, Field(description="文件名；缺省从 url 尾段或自动生成")] = None,
    make_visible: Annotated[bool, Field(description="图片 push 后触发 MediaStore 扫描")] = True,
    device: Annotated[str | None, Field(description="serial/alias；单机可省")] = None,
    ctx: Context = None,
) -> dict:
    """同步上传小文件/图片到手机。图片自动进相册。大文件用 stage_upload/deliver_staged。"""
    try:
        up.require_xor(content_base64, url, ("content_base64", "url"))
        serial = _resolve_device(device, _get_session_default(ctx))
        _state_registry.touch(serial)
        up.ensure_dirs()
        # 落主机暂存
        tmp = up.UPLOADS_DIR / f"sync_{up.uuid.uuid4().hex}"
        if content_base64 is not None:
            data = up.decode_b64(content_base64)
            if len(data) > up.SYNC_B64_MAX:
                return {"ok": False, "error": "超过同步上限",
                        "hint": "用 stage_upload + deliver_staged 异步路径"}
            tmp.write_bytes(data)
            fname = up.sanitize_filename(filename or "upload.bin")
        else:
            fname = up.sanitize_filename(filename or Path(urllib.parse.urlparse(url).path).name or "upload.bin")
            try:
                up.download_url(url, tmp, max_bytes=up.SYNC_URL_MAX_USB)
            except up.UploadError as e:
                tmp.unlink(missing_ok=True)
                return {"ok": False, "error": str(e),
                        "hint": "大文件用 deliver_staged(url=...) 异步路径"}
        dpath = up.validate_device_path(device_path or f"/sdcard/Pictures/{fname}")
        # push（同步，受 25s 钳制；小文件足够）
        r = _adb_run(up.push_args(serial, str(tmp), dpath), timeout=25, serial=None)
        if r["returncode"] != 0:
            tmp.unlink(missing_ok=True)
            return {"ok": False, "stdout": r["stdout"], "stderr": r["stderr"], **_diag(r)}
        visible = False
        content_uri = None
        if make_visible and up.is_image(fname):
            _adb_run(up.media_scan_args(dpath), timeout=10, serial=serial)
            q = _adb_run(["shell", "content", "query", "--uri",
                          "content://media/external/images/media",
                          "--where", f"_data='{dpath}'"], timeout=10, serial=serial)
            visible = "Row:" in q.get("stdout", "")
        tmp.unlink(missing_ok=True)
        return {"ok": True, "device_path": dpath, "size": (up.UPLOADS_DIR.exists() and 0) or 0,
                "visible_in_gallery": visible, "content_uri": content_uri}
    except up.UploadError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def stage_upload(
    content_base64: Annotated[str, Field(description="本片字节的 base64")],
    stage_id: Annotated[str | None, Field(description="缺省=新建会话；给定=向该会话追加")] = None,
    last: Annotated[bool, Field(description="true=收尾，标记暂存文件完成")] = False,
    filename: Annotated[str | None, Field(description="新建会话时的文件名")] = None,
    device: Annotated[str | None, Field(description="serial/alias；单机可省")] = None,
    ctx: Context = None,
) -> dict:
    """为大本地文件分片暂存：多次调用把字节追加进主机暂存文件，再用 deliver_staged 交付。"""
    try:
        data = up.decode_b64(content_base64)
        if stage_id is None:
            stage_id = up.new_stage(filename or "upload.bin")
        r = up.append_chunk(stage_id, data, last=last)
        return {"ok": True, "stage_id": stage_id, **r}
    except up.UploadError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def deliver_staged(
    stage_id: Annotated[str | None, Field(description="已完成的分片暂存 id；与 url 二选一")] = None,
    url: Annotated[str | None, Field(description="http/https 链接（主机后台下载）；与 stage_id 二选一")] = None,
    device_path: Annotated[str | None, Field(description="设备目标路径；缺省 /sdcard/Download/<filename>")] = None,
    install: Annotated[bool, Field(description="true=push 后 pm install（APK）")] = False,
    make_visible: Annotated[bool, Field(description="图片则 push 后扫描进相册")] = True,
    device: Annotated[str | None, Field(description="serial/alias；单机可省")] = None,
    ctx: Context = None,
) -> dict:
    """异步交付：后台 adb push（url 则先下载）+ 可选 pm install/媒体扫描。返回 job_id，用 job_status 轮询。"""
    try:
        up.require_xor(stage_id, url, ("stage_id", "url"))
        serial = _resolve_device(device, _get_session_default(ctx))
        _state_registry.touch(serial)
        if stage_id is not None and not up.stage_is_complete(stage_id):
            return {"ok": False, "error": f"stage {stage_id} 未收尾（需 last=True）"}
        fname = up.stage_filename(stage_id) if stage_id else \
            up.sanitize_filename(Path(urllib.parse.urlparse(url).path).name or "upload.bin")
        default_dir = "/sdcard/Download" if not up.is_image(fname) else "/sdcard/Pictures"
        dpath = up.validate_device_path(device_path or f"{default_dir}/{fname}")

        def work():
            job_local = work.job_id
            host = up.stage_path(stage_id) if stage_id else (up.UPLOADS_DIR / f"dl_{job_local}")
            if url is not None:
                up.download_url(url, host, max_bytes=up.URL_HARD_MAX)
            rc, out, err = up.run_proc(job_local, up.push_args(serial, str(host), dpath))
            if rc != 0:
                raise RuntimeError(f"adb push failed rc={rc}: {err}")
            res = {"device_path": dpath, "returncode": rc, "bytes_total": host.stat().st_size}
            if install:
                rc2, _o, e2 = up.run_proc(job_local, up.install_args(serial, str(host)))
                if rc2 != 0:
                    raise RuntimeError(f"pm install failed rc={rc2}: {e2}")
                res["installed"] = True
            elif make_visible and up.is_image(fname):
                up.run_proc(job_local, ["-s", serial] + up.media_scan_args(dpath))
                res["scanned"] = True
            # 清理暂存
            if stage_id:
                up.stage_path(stage_id).unlink(missing_ok=True)
                up._stage_meta(stage_id).unlink(missing_ok=True)
            else:
                host.unlink(missing_ok=True)
            return res

        job_id = _job_registry.submit(kind="deliver", serial=serial, work=work)
        work.job_id = job_id  # work 闭包内需要 job_id 命名 pid 文件
        return {"ok": True, "job_id": job_id, "state": "running"}
    except up.UploadError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def job_status(
    job_id: Annotated[str, Field(description="deliver_staged 返回的 job_id")],
    ctx: Context = None,
) -> dict:
    """轮询后台上传/安装任务状态。"""
    _job_registry.gc()
    j = _job_registry.get(job_id)
    if j is None:
        return {"ok": False, "error": f"未知 job_id: {job_id}"}
    return {"ok": True, **j}
```

> ⚠️ 闭包顺序坑:`work.job_id` 在 `submit` 之后才赋值,而 `submit` 会立即起线程执行 `work()`——需改为先 `job_id = uuid`、传入 work，再 submit。实现时把 `submit` 改成接受可选 `job_id`，或在 `work` 里改用 `reg` 传入的 id。**实现者按下面 Step 3 修正**。

- [ ] **Step 3: 修正 job_id 传递（改 `JobRegistry.submit` 支持预生成 id）**

在 `_uploads.py` 的 `submit` 增加 `job_id` 参数:
```python
def submit(self, *, kind, serial, work, on_done=None, job_id=None):
    job_id = job_id or uuid.uuid4().hex
    ...
```
并把 `deliver_staged` 改为:
```python
job_id = up.uuid.uuid4().hex
def work():
    host = up.stage_path(stage_id) if stage_id else (up.UPLOADS_DIR / f"dl_{job_id}")
    ... # 用闭包捕获的 job_id
_job_registry.submit(kind="deliver", serial=serial, work=work, job_id=job_id)
return {"ok": True, "job_id": job_id, "state": "running"}
```

- [ ] **Step 4: 在 `__main__` 启动处加清场**

在 `mcp.run(...)` 之前插入:
```python
    up.reap_orphans()
```

- [ ] **Step 5: 冒烟（仅校验工具注册，无需真机）**

Run: `cd platforms/android/server && python -c "import android_device_mcp as s; print([t for t in ['upload_media','stage_upload','deliver_staged','job_status'] if hasattr(s,t)])"`
Expected: `['upload_media', 'stage_upload', 'deliver_staged', 'job_status']`

- [ ] **Step 6: 提交**

```bash
git add platforms/android/server/android_device_mcp.py platforms/android/server/_uploads.py
git commit -m "feat(android-upload): 接线 upload_media/stage_upload/deliver_staged/job_status + 启动清场"
```

---

## Task 9: 更新工具计数测试 25 → 29

**Files:**
- Modify: `platforms/android/server/tests/test_tool_signatures.py`

- [ ] **Step 1: 改 `tool_names` 列表，追加 4 个工具名**

在 `tool_names` 末尾加 `"upload_media", "stage_upload", "deliver_staged", "job_status"`。

- [ ] **Step 2: 改计数断言**

`test_all_25_tools_present` → 重命名为 `test_all_29_tools_present`,断言 `len(tools) == 29`。

- [ ] **Step 3: 处理 `device` 参数断言**

`job_status` 无 `device` 参数(只接受 `job_id`/`ctx`)。把它加入 `no_device_param` 集合。

- [ ] **Step 4: 运行全测试**

Run: `cd platforms/android/server && python -m pytest tests/ -v`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add platforms/android/server/tests/test_tool_signatures.py
git commit -m "test(android-upload): 工具计数 25→29 + 新工具签名校验"
```

---

## Task 10: 真机验证（huawei-vog-al00）+ 质量门禁

> 非单测：用 MCP 工具在真机上跑。按用户既有约定自主选机验证。媒体扫描是最高风险项,按结果定稿（主方案失败则启用 `media_insert_args` 兜底,必要时回 `_uploads.py` 调整并补单测）。

- [ ] **Step 1: 小图同步进相册**
  - 造一张小 png 的 base64 → `upload_media(content_base64=..., device_path="/sdcard/Pictures/fleet_test.jpg")`。
  - 期望 `ok:true, visible_in_gallery:true`。
  - 真机佐证:`run_shell("ls -l /sdcard/Pictures/fleet_test.jpg")` 有文件;`run_shell("content query --uri content://media/external/images/media --where \"_data='/sdcard/Pictures/fleet_test.jpg'\"")` 有 Row。
  - 打开相册/任一选图器(可 `dump_ui`)确认可见。

- [ ] **Step 2: 分片 → 交付 → 轮询**
  - 取一个 ~10MB 文件,分 3-4 片 `stage_upload`(末片 `last=True`)→ `deliver_staged(stage_id, device_path="/sdcard/Download/fleet_big.bin")` → `job_status` 轮询至 `succeeded`。
  - `run_shell("ls -l /sdcard/Download/fleet_big.bin")` 校验大小一致。

- [ ] **Step 3: APK（url）安装**
  - `deliver_staged(url="<可达 apk>", install=True)` → 轮询 `succeeded`。
  - `run_shell("pm list packages | grep <pkg>")` 确认安装。
  - 若无可达 url,改用分片 + `deliver_staged(stage_id, install=True)`。

- [ ] **Step 4: 媒体扫描机制定稿**
  - 若 Step 1 的 `visible_in_gallery` 为 false:在真机试 `media_insert_args` 兜底,确认可见后把兜底接入 `upload_media`/`deliver_staged`(主方案失败时自动回退),补对应单测,重跑 Task 9 全测试。

- [ ] **Step 5: 质量门禁（章程要求）**
  - 派 `feature-dev:code-reviewer` 复核 `_uploads.py` + 4 个工具 + 测试;无阻断问题再进入收尾。
  - 修复 reviewer 指出的阻断项并复验。

- [ ] **Step 6: 收尾提交**

```bash
git add -A platforms/android/server
git commit -m "test(android-upload): 真机验证（小图进相册/分片交付/APK 安装）+ 媒体扫描定稿"
```

---

## Task 11: 文档

**Files:**
- Modify: android 工具清单文档（`docs/platforms` 下 android 章节 + 工具计数 25→29）、`platforms/android/skills/using-android/`（增补上传用法:三种来源、快/稳路径、轮询）、`CHANGELOG.md`。

- [ ] **Step 1: 工具清单 + 计数**：把 4 个新工具加入 android 工具表，所有"25 tools"改 29。
- [ ] **Step 2: skill 用法**：在 `using-android` 增"给手机传文件/图片"小节——换背景用 `upload_media`，APK/大文件用 `stage_upload`+`deliver_staged`+`job_status`，强调无 `local_path`(agent 自读 base64)。
- [ ] **Step 3: CHANGELOG** 增一条 `feat(android): agent→device 文件上传（快/稳两条路径 + 进相册）`。
- [ ] **Step 4: 派文档·本地化 QA subagent 复核**（章程要求），无阻断再提交。
- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "docs(android-upload): 工具清单/计数/using-android skill/CHANGELOG"
```

---

## Self-Review（已执行）

- **Spec 覆盖**:传输断层→Task 8 `upload_media`/`stage_upload`/`deliver_staged`(无 `local_path`,base64/url);25s→Task 6/7 后台 job;相册可见性→Task 4/8/10;异或/base64/路径穿越/SSRF→Task 2;暂存/空间/TTL→Task 3;孤儿进程→Task 7;测试→Task 1-9;真机+门禁→Task 10;文档→Task 11。无遗漏。
- **占位扫描**:无 TBD/TODO;每个 code step 给了完整代码。
- **类型一致**:`UploadError`、`require_xor`、`stage_path`/`_stage_meta`/`stage_filename`、`push_args`/`media_scan_args`/`media_insert_args`/`install_args`、`download_url`、`JobRegistry.submit(...,job_id=)`/`.get`/`.gc`、`run_proc`/`reap_orphans`/`ADB_BIN` 跨任务一致。
- **已知坑**:Task 8 的 `work.job_id` 闭包顺序问题已在 Step 3 显式修正(`submit` 支持预生成 `job_id`)。
