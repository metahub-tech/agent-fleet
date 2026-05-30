# iOS Agent 文件上传 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 agent 把字节传到 iOS 设备 —— `target=photos` 走 WDA 扩展(NSData raw body → PHPhotoLibrary)、`target=app` 走 pymobiledevice3 afc;以 mac host 上的 `POST /upload` HTTP 端点为主入口(同 Android 模式)。

**Architecture:** 共享 helper 抽到 `platforms/common/_upload_common.py`,Android `_uploads.py` 切引用保留专属;iOS 新 `_uploads_ios.py` 含 WDA 客户端 + afc 推送;WDA 加 `FBPhotosCommands` 路由(raw body + 头部元数据,`dispatch_semaphore` 等 `performChanges` completion);`build-wda.sh` 在 xcodebuild 前调 `wda-ext/install.sh` 幂等注入(`.h/.m` cp + `FBCommandRouter.m` sed + `PlistBuddy` upsert + `touch` 失效 cache)。

**Tech Stack:** Python 3.10+, fastmcp, pymobiledevice3, httpx(已是 ios server dep,用于 mac→WDA HTTP),pytest,Starlette `custom_route`;Objective-C(WDA 扩展),`/usr/libexec/PlistBuddy`,bash + sed。**不引入新 Python 依赖**。

设计依据:`docs/internal/design/2026-05-30-ios-agent-file-upload-design.md`。

> **Spec 微调(本计划生效后请同步更新 spec)**:WDA 端点改为 **raw body**(`application/octet-stream`)+ `X-Filename` / `X-Type` 头,而非 multipart —— FBRouteRequest 的 `request.body` 直给 NSData,ObjC 端不用多写 multipart 解析。mac `/upload` handler 内部把入站 body(raw 或 multipart 都吃)流式转 raw POST 给 WDA。

---

## File Structure

### Create
- `platforms/common/_upload_common.py` —— 共享 helper(`UploadError`/`require_xor`/`decode_b64`/`parse_bool`/`sanitize_filename`/`is_image`/`is_video`/`_ip_is_blocked`/`_is_blocked_ip`/`validate_url`/`download_url`/`UPLOADS_DIR`/`URL_HARD_MAX`/`IMAGE_EXTS`/`VIDEO_EXTS`/`_FORBIDDEN_PATH_CHARS_BASE`)
- `platforms/common/tests/__init__.py` + `platforms/common/tests/test_upload_common.py`
- `platforms/ios/server/_uploads_ios.py` —— iOS 专属:`validate_relpath`、WDA HTTP 客户端(httpx)、afc 推送 helper、`_http_upload_worker`(threadpool 同步)
- `platforms/ios/server/tests/test_uploads_ios.py`
- `platforms/ios/wda-ext/FBPhotosCommands.h`、`FBPhotosCommands.m` —— WDA route
- `platforms/ios/wda-ext/install.sh`、`uninstall.sh` —— 幂等注入/还原
- `platforms/ios/wda-ext/README.md` —— 一页说明,关联 build-wda.sh

### Modify
- `platforms/android/server/_uploads.py` —— 切到 `from _upload_common import ...`,保留 android 专属(`_FORBIDDEN_PATH_CHARS` 在 base 上加 `'` 等);Android 现有 63 单测必须仍全绿。
- `platforms/ios/server/ios_device_mcp.py` —— 加 3 个 `@mcp.tool`(`upload_to_photos`/`upload_to_app`/`get_upload_endpoint`)+ 1 个 `@mcp.custom_route("/upload")` Starlette 路由 + `import _uploads_ios as up_ios` + import `starlette.{requests,responses,concurrency}`。
- `platforms/ios/scripts/build-wda.sh` —— xcodebuild 前调 `wda-ext/install.sh "$WDA_DIR"`,失败即退出。
- `platforms/ios/README.md`、`platforms/ios/skills/using-ios/SKILL.md`、`docs/architecture.md`、`CHANGELOG.md`、`docs/internal/design/2026-05-30-ios-agent-file-upload-design.md`(微调 multipart→raw body 描述)。

---

## Task 1: `_upload_common.py` 骨架 + 常量 + UploadError + ensure_dirs

**Files:**
- Create: `platforms/common/_upload_common.py`
- Create: `platforms/common/tests/__init__.py`
- Create: `platforms/common/tests/test_upload_common.py`

- [ ] **Step 1: 写失败测试**

```python
# platforms/common/tests/test_upload_common.py
import sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import _upload_common as up

def test_constants_and_error():
    assert up.URL_HARD_MAX == 200 * 1024 * 1024
    assert ".jpg" in up.IMAGE_EXTS and ".png" in up.IMAGE_EXTS
    assert ".mp4" in up.VIDEO_EXTS and ".mov" in up.VIDEO_EXTS
    assert issubclass(up.UploadError, ValueError)

def test_ensure_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "UPLOADS_DIR", tmp_path / "uploads")
    up.ensure_dirs()
    assert (tmp_path / "uploads").is_dir()
```

- [ ] **Step 2: 跑,确认失败**

Run: `cd platforms/common && python3 -m pytest tests/ -q`
Expected: `ModuleNotFoundError: _upload_common` 或 collection error。

- [ ] **Step 3: 最小实现**

```python
# platforms/common/_upload_common.py
"""跨平台上传支撑 helper（Android / iOS / 后续 Win/Mac 都可共用的纯逻辑）。

设计：docs/internal/design/2026-05-28-android-agent-file-upload-design.md
      docs/internal/design/2026-05-30-ios-agent-file-upload-design.md

不引入 platform 特定逻辑（adb、pymobiledevice3、WDA），保持可单测且无外部依赖。
"""
from __future__ import annotations

import base64
import ipaddress
import socket
import urllib.parse
import urllib.request
from pathlib import Path

UPLOADS_DIR = Path.home() / ".agent-fleet" / "uploads"
URL_HARD_MAX = 200 * 1024 * 1024  # 任何 url 下载硬上限

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv", ".webm"}

# 通用最小注入字符集（quote/分号/$/反斜线/换行）。各平台可在自己模块按需扩展
# （Android 还需补单引号防 MediaStore SQL 注入）。
_FORBIDDEN_PATH_CHARS_BASE = set("\"`;$\n\r")


class UploadError(ValueError):
    """入参/校验错误，工具层转成 {ok: false, error}。"""


def ensure_dirs() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: 跑,确认通过**

Run: `cd platforms/common && python3 -m pytest tests/ -q`
Expected: `2 passed`。

- [ ] **Step 5: 提交**

```bash
git add platforms/common/_upload_common.py platforms/common/tests/__init__.py platforms/common/tests/test_upload_common.py
git commit -m "feat(upload-common): 跨平台上传 helper 骨架（常量 + UploadError + ensure_dirs）"
```

---

## Task 2: 校验 + 类型判断 helper(require_xor / decode_b64 / sanitize_filename / is_image / is_video)

**Files:**
- Modify: `platforms/common/_upload_common.py`
- Modify: `platforms/common/tests/test_upload_common.py`

- [ ] **Step 1: 追加失败测试**

```python
def test_require_xor():
    up.require_xor("a", None, ("a", "b"))
    up.require_xor(None, "b", ("a", "b"))
    with pytest.raises(up.UploadError): up.require_xor("a", "b", ("a", "b"))
    with pytest.raises(up.UploadError): up.require_xor(None, None, ("a", "b"))

def test_decode_b64():
    import base64
    assert up.decode_b64(base64.b64encode(b"hi").decode()) == b"hi"
    with pytest.raises(up.UploadError): up.decode_b64("not!!base64")

def test_sanitize_filename_minimal():
    assert up.sanitize_filename("bg.jpg") == "bg.jpg"
    for bad in ["", "../x", "a/b", "a\\b", "a;b", 'a"b', "a\nb"]:
        with pytest.raises(up.UploadError):
            up.sanitize_filename(bad)
    # 单引号通用 base 不禁（Android 自行扩展）
    assert up.sanitize_filename("it's.jpg") == "it's.jpg"

def test_is_image_and_video():
    assert up.is_image("a.JPG") and up.is_image("a.heic") and not up.is_image("a.mp4")
    assert up.is_video("v.MOV") and up.is_video("v.mp4") and not up.is_video("a.jpg")
```

- [ ] **Step 2: 跑 → 失败**

Run: `cd platforms/common && python3 -m pytest tests/ -q`
Expected: 4 failures(`AttributeError: require_xor` 等)。

- [ ] **Step 3: 实现**(追加到 `_upload_common.py`)

```python
def require_xor(a, b, names: tuple[str, str]) -> None:
    if (a is None) == (b is None):
        raise UploadError(f"必须且只能提供 {names[0]} 与 {names[1]} 之一")

def decode_b64(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=True)
    except Exception as e:  # noqa: BLE001
        raise UploadError(f"base64 解码失败: {e}") from e

def sanitize_filename(name: str) -> str:
    if not name or "/" in name or "\\" in name or ".." in name:
        raise UploadError(f"非法 filename: {name!r}")
    if set(name) & _FORBIDDEN_PATH_CHARS_BASE:
        raise UploadError(f"filename 含非法字符: {name!r}")
    return name

def is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTS

def is_video(name: str) -> bool:
    return Path(name).suffix.lower() in VIDEO_EXTS
```

- [ ] **Step 4: 跑 → 通过 / Step 5: 提交**

Run → 6 passed。

```bash
git add platforms/common/_upload_common.py platforms/common/tests/test_upload_common.py
git commit -m "feat(upload-common): 校验 helper（xor/b64/filename/is_image/is_video）"
```

---

## Task 3: URL/SSRF 校验 + 流式 download_url

**Files:**
- Modify: `platforms/common/_upload_common.py`
- Modify: `platforms/common/tests/test_upload_common.py`

- [ ] **Step 1: 追加失败测试**

```python
def test_ip_blocked():
    assert up._ip_is_blocked("127.0.0.1") and up._ip_is_blocked("10.1.2.3")
    assert up._ip_is_blocked("169.254.169.254")
    assert not up._ip_is_blocked("8.8.8.8")
    assert not up._ip_is_blocked("not-an-ip")

def test_validate_url():
    up.validate_url("https://example.com/x")
    with pytest.raises(up.UploadError): up.validate_url("ftp://example.com")
    with pytest.raises(up.UploadError): up.validate_url("http://127.0.0.1/x")

import functools, http.server, threading
def _serve(d):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    s = http.server.HTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, s.server_address[1]

def test_download_url_ok(tmp_path, monkeypatch):
    (tmp_path / "a.bin").write_bytes(b"X" * 80)
    s, port = _serve(tmp_path)
    monkeypatch.setattr(up, "_is_blocked_ip", lambda h: False)
    monkeypatch.setattr(up, "_ip_is_blocked", lambda ip: False)
    try:
        n = up.download_url(f"http://127.0.0.1:{port}/a.bin", tmp_path / "o", max_bytes=1000)
        assert n == 80 and (tmp_path / "o").read_bytes() == b"X" * 80
    finally: s.shutdown()

def test_download_url_over_limit(tmp_path, monkeypatch):
    (tmp_path / "big.bin").write_bytes(b"X" * 5000)
    s, port = _serve(tmp_path)
    monkeypatch.setattr(up, "_is_blocked_ip", lambda h: False)
    monkeypatch.setattr(up, "_ip_is_blocked", lambda ip: False)
    try:
        with pytest.raises(up.UploadError):
            up.download_url(f"http://127.0.0.1:{port}/big.bin", tmp_path / "o", max_bytes=1000)
    finally: s.shutdown()
```

- [ ] **Step 2: 跑 → 失败 / Step 3: 实现**

```python
def _ip_is_blocked(ip_str: str) -> bool:
    try: ip = ipaddress.ip_address(ip_str)
    except ValueError: return False
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved

def _is_blocked_ip(host: str) -> bool:
    try: infos = socket.getaddrinfo(host, None)
    except socket.gaierror: return False
    return any(_ip_is_blocked(sa[0]) for *_, sa in infos)

def validate_url(url: str) -> None:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise UploadError(f"仅支持 http/https: {url!r}")
    if not p.hostname:
        raise UploadError(f"url 缺少 host: {url!r}")
    if _is_blocked_ip(p.hostname):
        raise UploadError(f"拒绝内网/元数据地址: {p.hostname}")

def download_url(url: str, dest: Path, max_bytes: int) -> int:
    """下载 url 到 dest，SSRF 校验 + 大小上限 + DNS 重绑定对端复验。返回字节数。"""
    validate_url(url)
    cap = min(max_bytes, URL_HARD_MAX)
    written = 0
    req = urllib.request.Request(url, headers={"User-Agent": "agent-fleet"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        try: peer_ip = resp.fp.raw._sock.getpeername()[0]
        except Exception: peer_ip = None
        if peer_ip and _ip_is_blocked(peer_ip):
            raise UploadError(f"连接对端为内网/元数据地址: {peer_ip}")
        clen = resp.headers.get("Content-Length")
        if clen and int(clen) > cap:
            raise UploadError(f"文件超过上限 {cap} 字节（Content-Length={clen}）")
        with dest.open("wb") as fh:
            while True:
                buf = resp.read(64 * 1024)
                if not buf: break
                written += len(buf)
                if written > cap:
                    fh.close(); dest.unlink(missing_ok=True)
                    raise UploadError(f"下载超过上限 {cap} 字节")
                fh.write(buf)
    return written
```

- [ ] **Step 4: 跑 → 通过 / Step 5: 提交**

```bash
git add platforms/common/_upload_common.py platforms/common/tests/test_upload_common.py
git commit -m "feat(upload-common): url 下载 + SSRF/对端复验 + 流式大小上限"
```

---

## Task 4: parse_bool

**Files:** Modify common.

- [ ] **Step 1-5(同上 TDD 模式)**

测试:
```python
def test_parse_bool():
    assert up.parse_bool(None, True) is True and up.parse_bool(None, False) is False
    for t in ("true","1","yes","on","TRUE"): assert up.parse_bool(t) is True
    for f in ("false","0","no","off"): assert up.parse_bool(f) is False
```

实现:
```python
def parse_bool(s, default: bool = False) -> bool:
    if s is None: return default
    return str(s).strip().lower() in ("1", "true", "yes", "on")
```

提交 `feat(upload-common): parse_bool`。

---

## Task 5: Android `_uploads.py` 切引用 `_upload_common`,保留专属

**Files:**
- Modify: `platforms/android/server/_uploads.py`
- 不动:`platforms/android/server/tests/`(63 单测必须仍全绿)

- [ ] **Step 1: 改 import + 删冗余**

把现有 `_uploads.py` 的 `UploadError` / `require_xor` / `decode_b64` / `parse_bool` / `_ip_is_blocked` / `_is_blocked_ip` / `validate_url` / `download_url` / `is_image` / `URL_HARD_MAX` / `IMAGE_EXTS` / `UPLOADS_DIR` 整段删掉,顶部加:

```python
# 复用跨平台共享 helper（platforms/common/_upload_common.py）
# 当前 server 由 setup 脚本把 platforms/common/ 放进 sys.path（见 conftest 与 server 入口）。
from _upload_common import (
    UploadError, ensure_dirs as _common_ensure_dirs, require_xor, decode_b64,
    parse_bool, sanitize_filename as _common_sanitize_filename, is_image,
    _ip_is_blocked, _is_blocked_ip, validate_url, download_url,
    UPLOADS_DIR, URL_HARD_MAX, IMAGE_EXTS,
)
```

保留并改造下列 Android 专属:
- `_FORBIDDEN_PATH_CHARS = up_common_base | {"'"}` —— Android 需多禁单引号(防 `content query --where _data='...'` SQL 注入)。**改为本地集合,不动 common**:
  ```python
  from _upload_common import _FORBIDDEN_PATH_CHARS_BASE
  _FORBIDDEN_PATH_CHARS = _FORBIDDEN_PATH_CHARS_BASE | set("'")  # Android 额外防 SQL
  ```
- `sanitize_filename`(本地版,叠加 `_FORBIDDEN_PATH_CHARS` 检查):
  ```python
  def sanitize_filename(name: str) -> str:
      _common_sanitize_filename(name)  # 通用校验
      if set(name) & {"'"}:            # Android 额外
          raise UploadError(f"filename 含 SQL 单引号: {name!r}")
      return name
  ```
- `validate_device_path`、`canonical_data_path`、`push_args`/`install_args`/`media_scan_args`/`media_insert_args`/`mediastore_query_args`、`new_stage`/`append_chunk`/`stage_is_complete`/`_clear_stage` 等暂存逻辑、`JobRegistry`、`run_proc`、`reap_orphans`、`ADB_BIN`、`SYNC_*` / `STAGE_TTL_SEC` / `JOB_TTL_SEC` / `MIN_FREE_BYTES` —— 全部保留(Android 专属常量与逻辑)。
- `ensure_dirs` 复用 common(它创 `UPLOADS_DIR`),Android 自己另保 `JOBS_DIR.mkdir`:
  ```python
  def ensure_dirs() -> None:
      _common_ensure_dirs()
      JOBS_DIR.mkdir(parents=True, exist_ok=True)
  ```

- [ ] **Step 2: 保 server 入口能找到 common**

`platforms/android/server/android_device_mcp.py` 已有 `sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))`(见 line ~50),common 已在 sys.path。检查:
```bash
grep -n "platforms/common\|parent.parent.parent.*common" platforms/android/server/android_device_mcp.py
```
应已存在。若无,本任务加上;tests 通过 `conftest.py` 也已注入(检查 `platforms/android/server/tests/conftest.py`)。

- [ ] **Step 3: 跑 Android 全测试套**

```bash
cd platforms/android/server && python3 -m pytest tests/ -q
```
Expected: **63 passed**(同 PR #53 数)。任何 fail 立即停下查 import 是否齐全 / 名字是否对得上。

- [ ] **Step 4: 提交**

```bash
git add platforms/android/server/_uploads.py
git commit -m "refactor(android-upload): 把通用 helper 切到 _upload_common（Android 专属保留）"
```

---

## Task 6: iOS `_uploads_ios.py` 校验 + 默认目录 helper

**Files:**
- Create: `platforms/ios/server/_uploads_ios.py`
- Create: `platforms/ios/server/tests/test_uploads_ios.py`

- [ ] **Step 1: 写失败测试**

```python
# platforms/ios/server/tests/test_uploads_ios.py
import sys, pytest
from pathlib import Path
_SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SERVER))
sys.path.insert(0, str(_SERVER.parent.parent / "common"))

# Provide a fake adb-equivalent so module import doesn't need real pymobiledevice3 device
import _uploads_ios as up_ios
from _upload_common import UploadError

def test_validate_relpath_ok():
    assert up_ios.validate_relpath("Documents/x.txt") == "Documents/x.txt"
    assert up_ios.validate_relpath("inbox/sub/y.pdf") == "inbox/sub/y.pdf"

def test_validate_relpath_rejects_absolute_traversal_chars():
    for bad in ["/abs", "..", "a/../b", "a;b", 'a"b']:
        with pytest.raises(UploadError):
            up_ios.validate_relpath(bad)

def test_resolve_target_photos():
    fname, params = up_ios.resolve_target(target="photos", filename="bg.jpg", bundle_id=None, relpath=None)
    assert fname == "bg.jpg" and params["type"] == "image"
    fname, params = up_ios.resolve_target(target="photos", filename="v.mov", bundle_id=None, relpath=None)
    assert params["type"] == "video"

def test_resolve_target_app():
    fname, params = up_ios.resolve_target(target="app", filename=None,
                                          bundle_id="com.example", relpath="Documents/x.pdf")
    assert fname == "x.pdf" and params["bundle_id"] == "com.example" and params["relpath"] == "Documents/x.pdf"

def test_resolve_target_rejects_bad_combo():
    with pytest.raises(UploadError): up_ios.resolve_target("photos", None, None, None)
    with pytest.raises(UploadError): up_ios.resolve_target("app", None, None, None)
    with pytest.raises(UploadError): up_ios.resolve_target("invalid", "f", None, None)
```

- [ ] **Step 2: 跑 → 失败 / Step 3: 实现**

```python
# platforms/ios/server/_uploads_ios.py
"""iOS agent→设备 上传支撑（共享 helper from _upload_common；iOS 专属逻辑）。

设计：docs/internal/design/2026-05-30-ios-agent-file-upload-design.md
"""
from __future__ import annotations
from pathlib import Path
from _upload_common import (
    UploadError, sanitize_filename, is_image, is_video,
    _FORBIDDEN_PATH_CHARS_BASE,
)

# WDA HTTP 默认端口（go-ios tunnel forward 到 mac host）
WDA_DEFAULT_PORT = 8100
PHOTOS_TIMEOUT_SECS = 35  # WDA 内部 30s + 网络余量


def validate_relpath(relpath: str) -> str:
    """app 沙盒相对路径：拒绝绝对、`..`、注入字符。"""
    if not relpath or relpath.startswith("/") or ".." in relpath.split("/"):
        raise UploadError(f"非法 relpath（绝对/.. 不允许）: {relpath!r}")
    if set(relpath) & _FORBIDDEN_PATH_CHARS_BASE:
        raise UploadError(f"relpath 含非法字符: {relpath!r}")
    return relpath


def resolve_target(target: str, filename: str | None, bundle_id: str | None,
                   relpath: str | None) -> tuple[str, dict]:
    """根据 target 校验并归一化参数。返回 (fname, params)。"""
    if target == "photos":
        if not filename:
            raise UploadError("target=photos 必须提供 filename")
        fname = sanitize_filename(filename)
        if is_image(fname):     ttype = "image"
        elif is_video(fname):   ttype = "video"
        else:
            raise UploadError(f"filename 非图片/视频后缀（IMAGE_EXTS/VIDEO_EXTS）: {fname!r}")
        return fname, {"type": ttype}
    if target == "app":
        if not bundle_id or not relpath:
            raise UploadError("target=app 必须提供 bundle_id 与 relpath")
        rp = validate_relpath(relpath)
        fname = sanitize_filename(Path(rp).name)
        return fname, {"bundle_id": bundle_id, "relpath": rp}
    raise UploadError(f"未知 target: {target!r}（应为 photos|app）")
```

- [ ] **Step 4: 跑 → 通过 / Step 5: 提交**

```bash
cd platforms/ios/server && python3 -m pytest tests/test_uploads_ios.py -q
# expected: 5 passed
git add platforms/ios/server/_uploads_ios.py platforms/ios/server/tests/test_uploads_ios.py
git commit -m "feat(ios-upload): _uploads_ios 校验 + target 解析"
```

---

## Task 7: WDA HTTP 客户端(httpx,iOS Photos import POST)

**Files:** Modify `_uploads_ios.py` + tests.

- [ ] **Step 1: 写失败测试**(用 `httpx.MockTransport` 模拟 WDA)

```python
def test_wda_photos_import_ok(monkeypatch):
    import httpx, json as _j
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/wda/photos/import"
        assert request.headers["X-Filename"] == "bg.jpg"
        assert request.headers["X-Type"] == "image"
        assert request.read() == b"BYTES"
        return httpx.Response(200, json={"ok": True, "asset_id": "AID-123"})
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8100")
    monkeypatch.setattr(up_ios, "_new_wda_client", lambda port=8100, timeout=35: client)
    res = up_ios.wda_photos_import(b"BYTES", filename="bg.jpg", ttype="image")
    assert res == {"ok": True, "asset_id": "AID-123"}

def test_wda_photos_import_error(monkeypatch):
    import httpx
    def handler(request): return httpx.Response(500, json={"ok": False, "error": "denied"})
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8100")
    monkeypatch.setattr(up_ios, "_new_wda_client", lambda port=8100, timeout=35: client)
    res = up_ios.wda_photos_import(b"X", "v.mp4", "video")
    assert res["ok"] is False and "denied" in res.get("error", "")

def test_wda_photos_import_timeout(monkeypatch):
    import httpx
    def handler(request): raise httpx.ReadTimeout("slow")
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8100")
    monkeypatch.setattr(up_ios, "_new_wda_client", lambda port=8100, timeout=35: client)
    res = up_ios.wda_photos_import(b"X", "f.jpg", "image")
    assert res["ok"] is False and "timeout" in res["error"].lower()
```

- [ ] **Step 2: 跑 → 失败 / Step 3: 实现**(追加)

```python
import httpx

def _new_wda_client(port: int = WDA_DEFAULT_PORT, timeout: int = PHOTOS_TIMEOUT_SECS) -> httpx.Client:
    return httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=timeout)

def wda_photos_import(body: bytes, filename: str, ttype: str,
                       port: int = WDA_DEFAULT_PORT) -> dict:
    """POST raw body 到 WDA /wda/photos/import；返回 {ok, asset_id?, error?}。"""
    try:
        with _new_wda_client(port=port) as client:
            r = client.post("/wda/photos/import",
                            content=body,
                            headers={
                                "Content-Type": "application/octet-stream",
                                "X-Filename": filename,
                                "X-Type": ttype,
                            })
        try:
            data = r.json()
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": f"WDA non-JSON response ({r.status_code}): {r.text[:200]}"}
        # WDA 失败时通常 5xx + ok=false；2xx + ok=true
        if r.status_code >= 400 and "ok" not in data:
            return {"ok": False, "error": f"WDA HTTP {r.status_code}: {data}"}
        return data
    except httpx.TimeoutException as e:
        return {"ok": False, "error": f"WDA HTTP timeout: {e}"}
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"WDA HTTP error: {type(e).__name__}: {e}",
                "hint": "WDA daemon 未跑或端口未通：检查 launchctl list | grep wda、go-ios tunnel"}
```

- [ ] **Step 4: 跑 → 通过 / Step 5: 提交**

```bash
git add platforms/ios/server/_uploads_ios.py platforms/ios/server/tests/test_uploads_ios.py
git commit -m "feat(ios-upload): WDA HTTP 客户端（raw body + X-Filename/X-Type 头 + timeout/error）"
```

---

## Task 8: iOS afc push 包装(target=app 用,复用 ios_device_mcp 的 _afc_op 模式)

**Files:** Modify `_uploads_ios.py` + tests。

- [ ] **Step 1: 写失败测试**(注入伪 afc op)

```python
def test_afc_push_to_app_success():
    pushed = {}
    def fake_op(udid, bundle_id, documents_only, op_coroutine_factory):
        async def fake_house_arrest:  pass  # not used; fake_op just records
        pushed["udid"] = udid; pushed["bundle"] = bundle_id; pushed["doc_only"] = documents_only
        return None
    rc = up_ios.afc_push_to_app(udid="UDID1", bundle_id="com.x", documents_only=True,
                                 host_path="/tmp/file.bin", device_relpath="Documents/x.bin",
                                 afc_op=fake_op)
    assert rc["ok"] is True
    assert pushed == {"udid":"UDID1","bundle":"com.x","doc_only":True}

def test_afc_push_to_app_failure():
    def fake_op(udid, bundle_id, documents_only, op_coroutine_factory):
        raise RuntimeError("HouseArrest denied")
    rc = up_ios.afc_push_to_app("U","b",True,"/tmp/x","x", afc_op=fake_op)
    assert rc["ok"] is False and "HouseArrest" in rc["error"]
```

- [ ] **Step 2: 跑 → 失败 / Step 3: 实现**(追加)

```python
def afc_push_to_app(udid: str, bundle_id: str, documents_only: bool,
                    host_path: str, device_relpath: str, *, afc_op) -> dict:
    """注入式：afc_op = ios_device_mcp._afc_op 在生产里、tests 里 stub。
    op_coroutine_factory 接受 house_arrest 客户端、返回 await-able。"""
    try:
        async def op(ha):
            # 真实实现里 ha.push(host_path, device_relpath) 是 awaitable
            await ha.push(host_path, device_relpath)
        afc_op(udid, bundle_id, documents_only, op)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "hint": "目标 app 需 UIFileSharingEnabled（documents_only=True）或 dev-signed"}
    return {"ok": True}
```

- [ ] **Step 4: 跑 → 通过 / Step 5: 提交**

```bash
git add platforms/ios/server/_uploads_ios.py platforms/ios/server/tests/test_uploads_ios.py
git commit -m "feat(ios-upload): afc_push_to_app 注入式 wrapper（target=app）"
```

---

## Task 9: WDA 扩展 `FBPhotosCommands.h/.m`

**Files:**
- Create: `platforms/ios/wda-ext/FBPhotosCommands.h`
- Create: `platforms/ios/wda-ext/FBPhotosCommands.m`

WDA 是 ObjC,**不能在 Python pytest 单测**;本任务只写代码 + 走读;真机集成测试在 Task 12。

- [ ] **Step 1: 写 .h**

```objc
// platforms/ios/wda-ext/FBPhotosCommands.h
// agent-fleet WDA extension —— /wda/photos/import：raw body → NSTemp → PHPhotoLibrary
#import <Foundation/Foundation.h>
@class FBRoute;
NS_ASSUME_NONNULL_BEGIN
@interface FBPhotosCommands : NSObject
+ (NSArray<FBRoute *> *)routes;
@end
NS_ASSUME_NONNULL_END
```

- [ ] **Step 2: 写 .m**

```objc
// platforms/ios/wda-ext/FBPhotosCommands.m
#import "FBPhotosCommands.h"
#import "FBRoute.h"
#import "FBRouteRequest.h"
#import "FBResponsePayload.h"
@import Photos;

@implementation FBPhotosCommands

+ (NSArray<FBRoute *> *)routes {
  return @[
    [[[FBRoute POST:@"/wda/photos/import"].withoutSession]
       respondWithTarget:self action:@selector(handleImport:)],
  ];
}

+ (id<FBResponsePayload>)handleImport:(FBRouteRequest *)request {
  // raw body via request.body（NSData）；元数据走 headers
  NSData *fileData = request.body;
  NSDictionary *headers = request.headers ?: @{};
  NSString *filename = headers[@"X-Filename"] ?: @"upload.bin";
  NSString *ttype    = headers[@"X-Type"]     ?: @"image";

  if (!fileData || fileData.length == 0) {
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:@"empty body" traceback:nil]);
  }

  // 写 NSTemp
  NSString *tmp = [NSTemporaryDirectory() stringByAppendingPathComponent:
                     [NSString stringWithFormat:@"%@-%@", [NSUUID UUID].UUIDString, filename]];
  NSError *writeErr = nil;
  if (![fileData writeToFile:tmp options:NSDataWritingAtomic error:&writeErr]) {
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:
              [NSString stringWithFormat:@"write tmp failed: %@", writeErr.localizedDescription] traceback:nil]);
  }

  // 异步 PHPhotoLibrary —— 用 semaphore 等 completion（30s 超时）
  __block NSString *assetId = nil;
  __block NSError  *blockErr = nil;
  dispatch_semaphore_t sem = dispatch_semaphore_create(0);

  [[PHPhotoLibrary sharedPhotoLibrary] performChanges:^{
    NSURL *url = [NSURL fileURLWithPath:tmp];
    PHAssetCreationRequest *req = [ttype isEqualToString:@"video"]
      ? [PHAssetCreationRequest creationRequestForAssetFromVideoAtFileURL:url]
      : [PHAssetCreationRequest creationRequestForAssetFromImageAtFileURL:url];
    assetId = req.placeholderForCreatedAsset.localIdentifier;
  } completionHandler:^(BOOL ok, NSError * _Nullable err) {
    blockErr = err;
    dispatch_semaphore_signal(sem);
  }];

  long waitRc = dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 30LL * NSEC_PER_SEC));
  [[NSFileManager defaultManager] removeItemAtPath:tmp error:nil];

  if (waitRc != 0) {
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:@"PHPhotoLibrary timeout" traceback:nil]);
  }
  if (blockErr) {
    NSString *msg = [NSString stringWithFormat:@"%@ (code=%ld)",
                       blockErr.localizedDescription, (long)blockErr.code];
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:msg traceback:nil]);
  }
  return FBResponseWithObject(@{@"ok": @YES, @"asset_id": assetId ?: NSNull.null});
}

@end
```

> 备注:WDA 不同 fork 的 `FBResponseWith*` API 名稱可能略不同(`FBResponseWithObject` / `FBResponseJSONPayload` 等)。Appium fork 现行用 `FBResponseWithObject(dict)` 与 `FBResponseWithStatus(FBCommandStatus)`。如 build 失败,按 WDA 当前 `WebDriverAgentLib/Categories/FBResponsePayload.h` 实际签名调整 1-2 行。

- [ ] **Step 3: 提交(无可单测,真机集成在 Task 12)**

```bash
git add platforms/ios/wda-ext/FBPhotosCommands.h platforms/ios/wda-ext/FBPhotosCommands.m
git commit -m "feat(ios-upload): WDA 扩展 FBPhotosCommands（raw body + semaphore 等 PHPhotoLibrary）"
```

---

## Task 10: WDA 扩展 install/uninstall 脚本

**Files:**
- Create: `platforms/ios/wda-ext/install.sh`
- Create: `platforms/ios/wda-ext/uninstall.sh`
- Create: `platforms/ios/wda-ext/README.md`

- [ ] **Step 1: 写 install.sh**

```bash
#!/usr/bin/env bash
# 幂等地把 agent-fleet WDA 扩展注入到 $WDA_DIR 的 WebDriverAgent 源码树
# usage:  install.sh /path/to/WebDriverAgent
set -eu
WDA_DIR="${1:-${WDA_DIR:-$HOME/WebDriverAgent}}"
EXT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$WDA_DIR/WebDriverAgentLib" ]; then
  echo "[wda-ext] FATAL: $WDA_DIR/WebDriverAgentLib not found; pass correct WDA_DIR" >&2; exit 1
fi

ROUTES_DIR="$WDA_DIR/WebDriverAgentLib/Routes"
ROUTER_M="$WDA_DIR/WebDriverAgentLib/Routes/FBCommandRouter.m"
PLIST="$WDA_DIR/WebDriverAgentRunner/Info.plist"

# (1) cp .h/.m
install -m 0644 "$EXT_DIR/FBPhotosCommands.h" "$ROUTES_DIR/FBPhotosCommands.h"
install -m 0644 "$EXT_DIR/FBPhotosCommands.m" "$ROUTES_DIR/FBPhotosCommands.m"
echo "[wda-ext] copied FBPhotosCommands.{h,m} → $ROUTES_DIR"

# (2) 注入 #import + routes 数组项（幂等）
if ! grep -q '"FBPhotosCommands.h"' "$ROUTER_M"; then
  # 在最后一行 #import "FBxxx.h" 之后追加
  awk '
    /^#import "FB.*\.h"/ { lastImport=NR }
    { lines[NR]=$0 }
    END {
      for (i=1; i<=NR; i++) {
        print lines[i]
        if (i == lastImport) print "#import \"FBPhotosCommands.h\""
      }
    }
  ' "$ROUTER_M" > "$ROUTER_M.tmp" && mv "$ROUTER_M.tmp" "$ROUTER_M"
  echo "[wda-ext] injected #import \"FBPhotosCommands.h\" into FBCommandRouter.m"
else
  echo "[wda-ext] #import already present, skip"
fi

# routes 注册：在 commandHandlerClasses 数组里加 [FBPhotosCommands class]（幂等）
if ! grep -q "\[FBPhotosCommands class\]" "$ROUTER_M"; then
  # 锚点：找到包含 'class]' 的最后一个数组行，在其后插入
  # WDA 的 FBCommandRouter.m 通常有形如 @[ [FBAccessibilityCommands class], ... [FBLastCmd class] ]; 的数组
  python3 - <<PYEOF "$ROUTER_M"
import re, sys
p = sys.argv[1]
src = open(p).read()
# 在数组结束 ']' 前插入 ", [FBPhotosCommands class]"
new = re.sub(r'(\[FB[A-Za-z_]+Commands\s+class\])(\s*)(\]\s*;)',
             r'\1,\n  [FBPhotosCommands class]\2\3', src, count=1)
if new == src:
    sys.exit("[wda-ext] FATAL: 未找到 commandHandlerClasses 数组锚点（最后一个 [FBxxxCommands class]）；FBCommandRouter.m 结构可能变化，手动加入或调整脚本")
open(p, "w").write(new)
PYEOF
  echo "[wda-ext] injected [FBPhotosCommands class] into commandHandlerClasses"
else
  echo "[wda-ext] [FBPhotosCommands class] already present, skip"
fi

# (3) Info.plist upsert NSPhotoLibraryAddUsageDescription（用 PlistBuddy 幂等）
DESC="用于把上传的图片/视频加入相册"
/usr/libexec/PlistBuddy -c "Add :NSPhotoLibraryAddUsageDescription string '$DESC'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :NSPhotoLibraryAddUsageDescription '$DESC'" "$PLIST"
echo "[wda-ext] upserted NSPhotoLibraryAddUsageDescription"

# (4) touch -m 让 xcodebuild 增量 build 失效
touch -m "$ROUTES_DIR/FBPhotosCommands.h" "$ROUTES_DIR/FBPhotosCommands.m" "$ROUTER_M" "$PLIST"
echo "[wda-ext] done. Rebuild WDA via build-wda.sh."
```

- [ ] **Step 2: 写 uninstall.sh**

```bash
#!/usr/bin/env bash
# 反向还原 install.sh 的注入
set -eu
WDA_DIR="${1:-${WDA_DIR:-$HOME/WebDriverAgent}}"
ROUTER_M="$WDA_DIR/WebDriverAgentLib/Routes/FBCommandRouter.m"
PLIST="$WDA_DIR/WebDriverAgentRunner/Info.plist"
ROUTES_DIR="$WDA_DIR/WebDriverAgentLib/Routes"

rm -f "$ROUTES_DIR/FBPhotosCommands.h" "$ROUTES_DIR/FBPhotosCommands.m"
# 去掉 #import 行 + routes 数组项
sed -i.bak -e '/#import "FBPhotosCommands.h"/d' \
           -e '/\[FBPhotosCommands class\]/d' "$ROUTER_M" && rm -f "$ROUTER_M.bak"
# 删 plist key
/usr/libexec/PlistBuddy -c "Delete :NSPhotoLibraryAddUsageDescription" "$PLIST" 2>/dev/null || true
echo "[wda-ext] reverted."
```

- [ ] **Step 3: 写 README.md**

简短说明 + 例子(install.sh / uninstall.sh / 由 build-wda.sh 自动调)。

- [ ] **Step 4: chmod + 提交**

```bash
chmod +x platforms/ios/wda-ext/install.sh platforms/ios/wda-ext/uninstall.sh
git add platforms/ios/wda-ext/
git commit -m "feat(ios-upload): wda-ext install/uninstall（幂等 cp + 锚点注入 + PlistBuddy）"
```

---

## Task 11: `build-wda.sh` 集成 + iOS server 接线 + smoke import

**Files:**
- Modify: `platforms/ios/scripts/build-wda.sh`
- Modify: `platforms/ios/server/ios_device_mcp.py`

- [ ] **Step 1: build-wda.sh 加 wda-ext install hook**

定位 `xcodebuild` 调用前(`grep -n "xcodebuild" build-wda.sh` 看准位置),插入:

```bash
# agent-fleet WDA 扩展（FBPhotosCommands 等）—— 幂等注入
EXT_DIR="$(cd "$(dirname "$0")"/../wda-ext && pwd)"
if [ -d "$EXT_DIR" ]; then
  echo "[build-wda] applying agent-fleet wda-ext from $EXT_DIR"
  if ! "$EXT_DIR/install.sh" "$WDA_DIR"; then
    echo "[build-wda] FATAL: wda-ext install failed; abort build" >&2
    exit 1
  fi
fi
```

- [ ] **Step 2: ios_device_mcp.py 加 imports**

顶部 import 区(line ~48 附近)加:
```python
import time
import urllib.parse
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
```

在 `mcp = FastMCP(...)` 之后(line ~407 类比 android)加:
```python
import _uploads_ios as up_ios  # noqa: E402
```

- [ ] **Step 3: 插入 4 个端点(3 工具 + 1 route)**

在 `pull_file_from_app` 之后插入(整段):

```python
# ============================================================
#       AGENT → iOS UPLOAD（HTTP /upload + 3 MCP 工具）
#       设计：docs/internal/design/2026-05-30-ios-agent-file-upload-design.md
# ============================================================

def _http_upload_worker(target: str, body: bytes, fname: str, params: dict,
                       udid: str) -> dict:
    """同步执行（在 threadpool）。target=photos → WDA；target=app → afc。"""
    if target == "photos":
        return up_ios.wda_photos_import(body, filename=fname, ttype=params["type"])
    elif target == "app":
        # 落 mac 暂存再 afc push（避免在 threadpool 直读巨大 body）
        from _upload_common import UPLOADS_DIR, ensure_dirs
        import uuid as _uuid
        ensure_dirs()
        tmp = UPLOADS_DIR / f"ios_http_{_uuid.uuid4().hex}"
        try:
            tmp.write_bytes(body)
            return up_ios.afc_push_to_app(
                udid=udid, bundle_id=params["bundle_id"],
                documents_only=params.get("documents_only", True),
                host_path=str(tmp), device_relpath=params["relpath"],
                afc_op=_afc_op,
            )
        finally:
            tmp.unlink(missing_ok=True)
    return {"ok": False, "error": f"unknown target: {target}"}


@mcp.custom_route("/upload", methods=["POST"])
async def http_upload(request: Request) -> JSONResponse:
    """POST 文件字节 → target=photos 走 WDA / target=app 走 afc。

    Query: target(photos|app, 默 photos)、filename、bundle_id、relpath、
           documents_only、device。
    Body: raw（--data-binary）或 multipart（file 字段）。
    """
    try:
        from _upload_common import UploadError, URL_HARD_MAX, parse_bool
        qp = request.query_params
        target = qp.get("target", "photos")
        filename = qp.get("filename")
        bundle_id = qp.get("bundle_id")
        relpath = qp.get("relpath")
        documents_only = parse_bool(qp.get("documents_only"), True)
        device = qp.get("device")

        clen = request.headers.get("content-length")
        if clen and clen.isdigit() and int(clen) > URL_HARD_MAX:
            return JSONResponse({"ok": False, "error": f"超过上限 {URL_HARD_MAX} 字节"}, status_code=413)

        # 流式落入临时 buffer（小内存），同时支持 multipart 与 raw
        ctype = request.headers.get("content-type", "")
        buf = bytearray()
        size = 0
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            f = form.get("file")
            if f is None or not hasattr(f, "read"):
                return JSONResponse({"ok": False, "error": "multipart 缺 file 字段"}, status_code=400)
            filename = filename or getattr(f, "filename", None)
            while True:
                chunk = await f.read(64 * 1024)
                if not chunk: break
                size += len(chunk)
                if size > URL_HARD_MAX:
                    return JSONResponse({"ok": False, "error": f"超过上限 {URL_HARD_MAX} 字节"}, status_code=413)
                buf.extend(chunk)
        else:
            async for chunk in request.stream():
                size += len(chunk)
                if size > URL_HARD_MAX:
                    return JSONResponse({"ok": False, "error": f"超过上限 {URL_HARD_MAX} 字节"}, status_code=413)
                buf.extend(chunk)

        if size == 0:
            return JSONResponse({"ok": False, "error": "空请求体"}, status_code=400)

        if target == "app" and documents_only is not None:
            params_pre = {"documents_only": documents_only}
        else:
            params_pre = {}

        fname, params = up_ios.resolve_target(target, filename, bundle_id, relpath)
        params.update(params_pre)
        udid = _resolve_device(device, None)
        _state_registry.touch(udid)

        result = await run_in_threadpool(
            _http_upload_worker, target, bytes(buf), fname, params, udid)
        result.setdefault("target", target)
        result.setdefault("device", udid)
        if target == "photos":
            result.setdefault("size", size)
        return JSONResponse(result, status_code=200 if result.get("ok") else 500)
    except up_ios.UploadError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)


@mcp.tool
def upload_to_photos(
    content_base64: Annotated[Optional[str], Field(description="文件字节 base64;与 url 二选一")] = None,
    url: Annotated[Optional[str], Field(description="http/https 链接;与 content_base64 二选一")] = None,
    filename: Annotated[Optional[str], Field(description="原文件名(必填,决定 image/video)")] = None,
    device: Annotated[Optional[str], Field(description="udid 或 alias")] = None,
    ctx: Context = None,
) -> dict:
    """同步上传图片/视频到 iOS Photos 相册（小文件 base64;大文件用 HTTP /upload）。"""
    from _upload_common import require_xor, decode_b64, download_url, URL_HARD_MAX, UploadError, UPLOADS_DIR, ensure_dirs
    import uuid as _uuid
    try:
        require_xor(content_base64, url, ("content_base64", "url"))
        if not filename: raise UploadError("upload_to_photos 必须提供 filename")
        fname, params = up_ios.resolve_target("photos", filename, None, None)
        udid = _resolve_device(device, _get_session_default(ctx))
        _state_registry.touch(udid)
        if content_base64 is not None:
            body = decode_b64(content_base64)
            if len(body) > 6 * 1024 * 1024:
                return {"ok": False, "error": "超过同步上限 6MB", "hint": "用 HTTP /upload"}
        else:
            ensure_dirs()
            tmp = UPLOADS_DIR / f"ios_sync_{_uuid.uuid4().hex}"
            try:
                download_url(url, tmp, max_bytes=20 * 1024 * 1024)
                body = tmp.read_bytes()
            finally:
                tmp.unlink(missing_ok=True)
        res = up_ios.wda_photos_import(body, filename=fname, ttype=params["type"])
        res.setdefault("target", "photos"); res.setdefault("device", udid); res.setdefault("size", len(body))
        return res
    except UploadError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def upload_to_app(
    bundle_id: Annotated[str, Field(description="目标 app bundle id")],
    relpath: Annotated[str, Field(description="app 沙盒内相对路径(默 Documents 下)")],
    content_base64: Annotated[Optional[str], Field(description="文件字节 base64;与 url 二选一")] = None,
    url: Annotated[Optional[str], Field(description="http/https 链接;与 content_base64 二选一")] = None,
    documents_only: Annotated[bool, Field(description="True=Documents-only;False=full container")] = True,
    device: Annotated[Optional[str], Field(description="udid 或 alias")] = None,
    ctx: Context = None,
) -> dict:
    """同步推 agent 字节到 app 沙盒(等价 push_file_to_app,但字节来自 agent)。"""
    from _upload_common import require_xor, decode_b64, download_url, UploadError, UPLOADS_DIR, ensure_dirs
    import uuid as _uuid
    try:
        require_xor(content_base64, url, ("content_base64", "url"))
        fname, params = up_ios.resolve_target("app", None, bundle_id, relpath)
        params["documents_only"] = documents_only
        udid = _resolve_device(device, _get_session_default(ctx))
        _state_registry.touch(udid)
        ensure_dirs()
        tmp = UPLOADS_DIR / f"ios_app_{_uuid.uuid4().hex}"
        try:
            if content_base64 is not None:
                tmp.write_bytes(decode_b64(content_base64))
            else:
                download_url(url, tmp, max_bytes=20 * 1024 * 1024)
            res = up_ios.afc_push_to_app(
                udid=udid, bundle_id=bundle_id, documents_only=documents_only,
                host_path=str(tmp), device_relpath=relpath, afc_op=_afc_op,
            )
            res.setdefault("target", "app"); res.setdefault("device", udid); res.setdefault("size", tmp.stat().st_size)
            return res
        finally:
            tmp.unlink(missing_ok=True)
    except UploadError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def get_upload_endpoint(ctx: Context = None) -> dict:
    """返回 /upload HTTP 端点用法(直 POST 文件字节,绕 base64/分片)。"""
    return {
        "ok": True, "method": "POST", "path": "/upload", "port": 8769,
        "params": "target=photos|app、filename(photos 必填)、bundle_id+relpath(app 必填)、documents_only、device",
        "hint": "host 同 ios-device MCP 的 URL。例:"
                "curl -X POST --data-binary @bg.png "
                "'http://<ios-host>:8769/upload?target=photos&filename=bg.png&device=<udid|alias>'",
    }
```

- [ ] **Step 4: smoke import**

```bash
cd platforms/ios/server && python3 -c "import ios_device_mcp as s; print([t for t in ['upload_to_photos','upload_to_app','get_upload_endpoint'] if hasattr(s,t)])"
# expected: ['upload_to_photos', 'upload_to_app', 'get_upload_endpoint']
```

如 import 时缺 fake pymobiledevice3 / WDA 而崩 → 加 conftest 或 env 同 android(fake adb)做法。

- [ ] **Step 5: 提交**

```bash
git add platforms/ios/scripts/build-wda.sh platforms/ios/server/ios_device_mcp.py
git commit -m "feat(ios-upload): 接线 3 工具 + /upload 路由 + build-wda 集成 wda-ext"
```

---

## Task 12: 真机部署 + 验证(iPad iOS 26 → iPhone7 iOS 15)

> 在 mac-mini(qjl-mac-mini)的环境跑;通过 win-device-qjl(若个人机有 mac)或直接由用户在 mac-mini terminal 跑。**不是 Python 单测,真机集成**。

- [ ] **Step 1: deploy(iPad)**
  - SSH/terminal 上 qjl-mac-mini:`cd <agent-fleet-clone> && git fetch && git checkout feat/ios-file-upload && git pull`
  - 跑 `platforms/ios/scripts/build-wda.sh <iPad_UDID>` —— 应看到 `[wda-ext] applying`、`copied`、`injected #import`、`injected [FBPhotosCommands class]`、`upserted NSPhotoLibrary...`、xcodebuild test 成功。
  - 重启 ios-device server(launchd 或手动)载入新 ios_device_mcp.py。

- [ ] **Step 2: 首次相册授权**
  - 在 agent 端 `curl http://qjl-mac-mini:8769/upload?target=photos&filename=t.jpg --data-binary @/tmp/t.jpg`(任一小 jpg)。
  - 第一次会失败(`PHPhotoLibrary denied`);在 iPad 上:**设置 → 隐私 → 照片 → WebDriverAgentRunner → 添加照片**,选"允许"。
  - 再 curl,期望 `{ok:true, asset_id:"..."}`。

- [ ] **Step 3: 4 组验证(对照 Android 同款)**
  1. 小图 base64 via MCP `upload_to_photos` → `ok:true, asset_id`。
  2. curl `/upload?target=photos` 推 ~500KB jpg → 同上。
  3. curl 推 **4.4MB qinπ.png** → `ok:true`(对照 Android 同图)。在 iPad 相册可见。
  4. curl 推小 mp4(~5MB) → `ok:true`,Photos 视频分类可见。
  5. curl `/upload?target=app&bundle_id=<WDA>&relpath=Documents/test.pdf` 推 PDF → afc 落沙盒(pymobiledevice3 拉回校验 md5)。

- [ ] **Step 4: iPhone7 deploy(可选,同 PR)**
  - 同 Step 1-3,host 改 test-macpro-12,设备 iPhone7。重复 1+3+4 三组。

- [ ] **Step 5: 派 code-reviewer(Python 部分)**

dispatch feature-dev:code-reviewer,review 范围 = 本分支 vs main 的 Python 部分(`_upload_common.py` / `_uploads_ios.py` / `ios_device_mcp.py` 修改、相关测试)。WDA Swift 真机已通过即可。

- [ ] **Step 6: 修阻断 + 复验 + commit**

```bash
git add -A platforms/ios/
git commit -m "test(ios-upload): 真机验证 iPad + 小红书选图器可见;code-review 修复"
```

---

## Task 13: 文档 + CHANGELOG + spec 微调

**Files:**
- Modify: `platforms/ios/README.md`(工具表 + 上传节)
- Modify: `platforms/ios/skills/using-ios/SKILL.md`(上传用法 + curl 例子 + 授权流程)
- Modify: `docs/architecture.md`(iOS 能力行追加上传工具)
- Modify: `CHANGELOG.md`([Unreleased] 增 iOS 上传条目)
- Modify: `docs/internal/design/2026-05-30-ios-agent-file-upload-design.md`(spec 微调:WDA 端点 multipart→raw body + 头部)

- [ ] **Step 1**:按 README 工具表既有风格,加"agent→device 文件上传"行(`upload_to_photos`/`upload_to_app`/`get_upload_endpoint` + HTTP `POST /upload` 用法块)。
- [ ] **Step 2**:`using-ios/SKILL.md` 加上传节(对照 `using-android/SKILL.md` 那节风格,强调"首选 HTTP `POST /upload`、首次相册授权流程")。
- [ ] **Step 3**:`docs/architecture.md` iOS 能力行追加 `upload_to_photos`/`upload_to_app`/`get_upload_endpoint` + `POST /upload`。
- [ ] **Step 4**:`CHANGELOG.md` [Unreleased] 新增条目,~150 字概括(iOS 上传 + WDA 扩展)。
- [ ] **Step 5**:spec 文件里 multipart 描述改为 raw body + X-Filename/X-Type 头(Task 9/11 都已实际如此)。

- [ ] **Step 6**:派文档·本地化 QA subagent(general-purpose 充 QA 角色)审 doc。修无阻断 → commit。

```bash
git add -A
git commit -m "docs(ios-upload): README/skill/architecture/CHANGELOG + spec 微调（raw body）"
```

---

## Task 14: 推送 + 开 PR + 合并 + host 切回 main

- [ ] **Step 1: push 分支**

```bash
TOKEN=$(python3 -c "import json,os; p='/root/.credentials/github.json' if os.path.exists('/root/.credentials/github.json') else os.path.expanduser('~/.credentials/github.json'); print(json.load(open(p))['token'])")
cd <repo>
git push "https://${TOKEN}@github.com/metahub-tech/agent-fleet.git" feat/ios-file-upload:feat/ios-file-upload 2>&1 | sed "s/${TOKEN}/***/g"
```

- [ ] **Step 2: 开 PR via API**(同 Android PR #53 模板,链接到设计 spec + 描述真机验证结果 + 已知 follow-up)。

- [ ] **Step 3: 等用户确认后 squash 合并**(`merge_method=squash`,标题 `feat(ios): agent→设备文件上传（HTTP /upload + WDA Photos 扩展） (#N)`)。

- [ ] **Step 4: host 切回 main**

两台 mac host(qjl-mac-mini + test-macpro-12)各跑:
```bash
cd <agent-fleet> && git checkout main && git pull origin main
launchctl unload ~/Library/LaunchAgents/cc.metahub.ios-device.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/cc.metahub.ios-device.plist
```
(具体 daemon 路径按 install-ios-device-daemon.sh 实际而定,本步骤按现状指引)。

---

## Self-Review

- **Spec 覆盖**:① 传输架构 → Task 11(`/upload` 透传 / target 选路);② WDA 扩展 → Task 9 + Task 10(install/uninstall);③ build-wda 集成 → Task 11;④ 异步 semaphore → Task 9 .m 代码内;⑤ 路由静态聚合注册 → Task 10 install.sh awk/python sed;⑥ Info.plist PlistBuddy → Task 10;⑦ build cache 失效 touch → Task 10;⑧ 共享 helper 抽取 → Tasks 1-5;⑨ Android 测试不破 → Task 5 Step 3;⑩ iOS 校验+target 解析 → Task 6;⑪ 真机验证(iPad/iPhone7/4.4MB)→ Task 12;⑫ 首次授权流程 → Task 12 Step 2;⑬ 文档 + CHANGELOG → Task 13;⑭ PR + 合并 + host 切回 → Task 14。
- **Spec 微调**(WDA multipart → raw body)→ Task 13 Step 5 同步 spec 文档。
- **占位扫描**:无 TBD/TODO;每个 code step 给完整代码 / 完整命令。
- **类型/名一致**:`UploadError`、`require_xor`、`sanitize_filename`、`is_image`/`is_video`、`download_url`、`UPLOADS_DIR`、`URL_HARD_MAX`、`wda_photos_import(body, filename, ttype)`、`afc_push_to_app(..., afc_op=...)`、`resolve_target(target, filename, bundle_id, relpath)`、`/wda/photos/import` headers `X-Filename`/`X-Type` —— 在所有 task 间一致。
- **已知坑预案**:① WDA ObjC FBResponse API 不同 fork 略差 → Task 9 末尾 1-2 行调整说明;② `FBCommandRouter.m` 锚点 sed/regex 找不到 → install.sh 显式 FATAL 退出可手动定位;③ smoke import 缺 fake pymobiledevice3 → Task 11 Step 4 提示参照 android conftest 同款 fake;④ 真机首次相册授权流程显式列入 Task 12 Step 2。
