"""agent → device-host staging → phone 上传支撑逻辑（纯逻辑 + 后台 job）。

设计：docs/internal/design/2026-05-28-android-agent-file-upload-design.md
计划：docs/internal/plans/2026-05-28-android-agent-file-upload.md

不在导入期触碰 adb/网络/磁盘；副作用经参数注入或显式调用。
"""
from __future__ import annotations

import base64
import ipaddress
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

UPLOADS_DIR = Path.home() / ".agent-fleet" / "uploads"
JOBS_DIR = UPLOADS_DIR / "jobs"

SYNC_B64_MAX = 6 * 1024 * 1024           # upload_media: base64 解码后字节上限
SYNC_URL_MAX_USB = 20 * 1024 * 1024      # upload_media: USB 同步 url 上限
SYNC_URL_MAX_WIRELESS = 8 * 1024 * 1024  # upload_media: 无线同步 url 上限（保守默认）
URL_HARD_MAX = 200 * 1024 * 1024         # 任何 url 下载硬上限
MIN_FREE_BYTES = 500 * 1024 * 1024       # 暂存目录可用空间低于此值拒绝新会话/job
STAGE_TTL_SEC = 1800                     # 分片会话 30min 未收尾即可回收
JOB_TTL_SEC = 3600                       # 完成态 job 1h 后回收

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}
ALLOWED_DEVICE_PREFIXES = ("/sdcard/", "/storage/emulated/0/")

# 由 android_device_mcp 在导入后注入真实 adb 路径
ADB_BIN = "adb"


class UploadError(ValueError):
    """入参/校验错误，工具层转成 {ok: false, error}。"""


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
#                        VALIDATION
# ============================================================

def require_xor(a, b, names: tuple[str, str]) -> None:
    if (a is None) == (b is None):
        raise UploadError(f"必须且只能提供 {names[0]} 与 {names[1]} 之一")


def decode_b64(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=True)
    except Exception as e:  # noqa: BLE001
        raise UploadError(f"base64 解码失败: {e}") from e


# shell/SQL 注入面字符：禁止出现在 filename / device_path 中
# （device_path 会拼进 `content query --where "_data='...'"`，单引号会破坏 SQL 字面量）
_FORBIDDEN_PATH_CHARS = set("'\"`;$\n\r")


def sanitize_filename(name: str) -> str:
    if not name or "/" in name or "\\" in name or ".." in name:
        raise UploadError(f"非法 filename: {name!r}")
    if set(name) & _FORBIDDEN_PATH_CHARS:
        raise UploadError(f"filename 含非法字符（引号/分号/$ 等）: {name!r}")
    return name


def validate_device_path(path: str) -> str:
    if ".." in path or not path.startswith(ALLOWED_DEVICE_PREFIXES):
        raise UploadError(
            f"device_path 必须在 {ALLOWED_DEVICE_PREFIXES} 内且不含 '..': {path!r}"
        )
    if set(path) & (_FORBIDDEN_PATH_CHARS | {"\\"}):
        raise UploadError(f"device_path 含非法字符（引号/分号/$/反斜线等）: {path!r}")
    return path


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved


def _is_blocked_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False  # 解析失败交给下载阶段报错
    return any(_ip_is_blocked(sockaddr[0]) for *_, sockaddr in infos)


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


# ============================================================
#                     STAGING (分片会话)
# ============================================================

def _free_bytes() -> int:
    target = UPLOADS_DIR if UPLOADS_DIR.exists() else UPLOADS_DIR.parent
    return shutil.disk_usage(target).free


def _check_space() -> None:
    if _free_bytes() < MIN_FREE_BYTES:
        raise UploadError("暂存目录可用空间不足（< 500MB），拒绝新上传")


def stage_path(stage_id: str) -> Path:
    return UPLOADS_DIR / f"{stage_id}.part"


def _stage_meta(stage_id: str) -> Path:
    return UPLOADS_DIR / f"{stage_id}.done"


def _stage_name_file(stage_id: str) -> Path:
    return UPLOADS_DIR / f"{stage_id}.name"


def new_stage(filename: str) -> str:
    _check_space()
    ensure_dirs()
    safe = sanitize_filename(filename)
    stage_id = uuid.uuid4().hex
    _stage_name_file(stage_id).write_text(safe)
    stage_path(stage_id).touch()
    return stage_id


def stage_filename(stage_id: str) -> str:
    f = _stage_name_file(stage_id)
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


def _clear_stage(stage_id: str) -> None:
    stage_path(stage_id).unlink(missing_ok=True)
    _stage_meta(stage_id).unlink(missing_ok=True)
    _stage_name_file(stage_id).unlink(missing_ok=True)


# ============================================================
#                   ADB COMMAND BUILDERS (纯函数)
# ============================================================

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


# ============================================================
#                     URL DOWNLOAD (主机侧)
# ============================================================

def download_url(url: str, dest: Path, max_bytes: int) -> int:
    """下载 url 到 dest，SSRF 校验 + 大小上限。返回写入字节数。"""
    validate_url(url)
    cap = min(max_bytes, URL_HARD_MAX)
    written = 0
    req = urllib.request.Request(url, headers={"User-Agent": "agent-fleet-android"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (scheme 已校验)
        # DNS-rebinding 防御：pre-check 与 urlopen 之间 DNS 可能被翻转，复验真实对端 IP。
        # 在读取/返回任何响应体之前中止，避免把内网/元数据服务的数据带回。
        try:
            peer_ip = resp.fp.raw._sock.getpeername()[0]
        except Exception:  # noqa: BLE001 - 拿不到对端就退回到 pre-check
            peer_ip = None
        if peer_ip and _ip_is_blocked(peer_ip):
            raise UploadError(f"连接对端为内网/元数据地址: {peer_ip}")
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


# ============================================================
#                       JOB REGISTRY
# ============================================================

class JobRegistry:
    """内存态后台任务注册表：submit() 在守护线程跑注入的 work()。

    状态机 running → succeeded / failed。重启丢失（接受，文档说明）。
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit(self, *, kind: str, serial: str, work, on_done=None, job_id: str | None = None) -> str:
        job_id = job_id or uuid.uuid4().hex
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
            stale = [k for k, v in self._jobs.items()
                     if v.get("finished_at") and now - v["finished_at"] > JOB_TTL_SEC]
            for jid in stale:
                del self._jobs[jid]


# ============================================================
#          BACKGROUND PROCESS RUNNER + PID + 孤儿清场
# ============================================================

def _pid_file(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.pid"


def run_proc(job_id: str, adb_args: list[str], timeout: int | None = None) -> tuple[int, str, str]:
    """在守护线程里前台阻塞跑一条 adb 命令（不经 25s 钳制）。写/删 pid。"""
    ensure_dirs()
    cmd = adb_args if adb_args[:1] == [ADB_BIN] else [ADB_BIN] + adb_args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _pid_file(job_id).write_text(str(proc.pid))
    try:
        out, err = proc.communicate(timeout=timeout)
        return (proc.returncode,
                out.decode("utf-8", "replace"),
                err.decode("utf-8", "replace"))
    finally:
        _pid_file(job_id).unlink(missing_ok=True)


def reap_orphans() -> None:
    """server 启动调用：杀掉上次残留的后台子进程并清场。"""
    if not JOBS_DIR.exists():
        return
    for pf in JOBS_DIR.glob("*.pid"):
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, signal.SIGKILL)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        finally:
            pf.unlink(missing_ok=True)
    for pattern in ("*.part", "*.done", "*.name", "dl_*", "sync_*"):
        for p in UPLOADS_DIR.glob(pattern):
            if p.is_file():
                p.unlink(missing_ok=True)
