"""agent → device-host staging → phone 上传支撑逻辑（纯逻辑 + 后台 job）。

设计：docs/internal/design/2026-05-28-android-agent-file-upload-design.md
计划：docs/internal/plans/2026-05-28-android-agent-file-upload.md

不在导入期触碰 adb/网络/磁盘；副作用经参数注入或显式调用。

通用 helper（require_xor / decode_b64 / parse_bool / is_image / validate_url /
download_url / _ip_is_blocked / _is_blocked_ip / sanitize_filename 通用基底 /
UPLOADS_DIR / URL_HARD_MAX / IMAGE_EXTS / UploadError）抽到
`platforms/common/_upload_common.py`，Android 在此基础上加专属（SQL 注入字符集、
设备路径校验、adb 命令构造、JobRegistry、暂存分片、后台 runner、孤儿清场）。
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

# 复用跨平台共享 helper（platforms/common/_upload_common.py）。
# android_device_mcp.py 在启动时把 platforms/common/ 放进 sys.path；
# 测试侧由 tests/conftest.py 同款注入。
from _upload_common import (
    UploadError,
    URL_HARD_MAX,
    UPLOADS_DIR,
    IMAGE_EXTS,
    _FORBIDDEN_PATH_CHARS_BASE,
    ensure_dirs as _common_ensure_dirs,
    require_xor,
    decode_b64,
    parse_bool,
    sanitize_filename as _common_sanitize_filename,
    is_image,
    _ip_is_blocked,
    _is_blocked_ip,
    validate_url,
    download_url,
)

JOBS_DIR = UPLOADS_DIR / "jobs"

SYNC_B64_MAX = 6 * 1024 * 1024           # upload_media: base64 解码后字节上限
SYNC_URL_MAX_USB = 20 * 1024 * 1024      # upload_media: USB 同步 url 上限
SYNC_URL_MAX_WIRELESS = 8 * 1024 * 1024  # upload_media: 无线同步 url 上限（保守默认）
MIN_FREE_BYTES = 500 * 1024 * 1024       # 暂存目录可用空间低于此值拒绝新会话/job
STAGE_TTL_SEC = 1800                     # 分片会话 30min 未收尾即可回收
JOB_TTL_SEC = 3600                       # 完成态 job 1h 后回收

ALLOWED_DEVICE_PREFIXES = ("/sdcard/", "/storage/emulated/0/")

# 由 android_device_mcp 在导入后注入真实 adb 路径
ADB_BIN = "adb"


def ensure_dirs() -> None:
    _common_ensure_dirs()
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
#                 ANDROID-SPECIFIC VALIDATION
# ============================================================

# shell/SQL 注入面字符（Android 在通用 base 基础上 + 单引号）：
# device_path 会拼进 `content query --where "_data='...'"`，单引号会破坏 SQL 字面量。
_FORBIDDEN_PATH_CHARS = _FORBIDDEN_PATH_CHARS_BASE | set("'")


def sanitize_filename(name: str) -> str:
    """Android filename：先走通用校验，再拒单引号（SQL 注入）。"""
    _common_sanitize_filename(name)
    if "'" in name:
        raise UploadError(f"filename 含 SQL 单引号: {name!r}")
    return name


def validate_device_path(path: str) -> str:
    if ".." in path or not path.startswith(ALLOWED_DEVICE_PREFIXES):
        raise UploadError(
            f"device_path 必须在 {ALLOWED_DEVICE_PREFIXES} 内且不含 '..': {path!r}"
        )
    if set(path) & (_FORBIDDEN_PATH_CHARS | {"\\"}):
        raise UploadError(f"device_path 含非法字符（引号/分号/$/反斜线等）: {path!r}")
    return path


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


def canonical_data_path(device_path: str) -> str:
    """MediaStore 的 _data 列存的是规范路径 /storage/emulated/0/…，而非 /sdcard/… 软链。
    可见性查询必须用规范形式，否则 _data 等值匹配永远落空（假阴性）。"""
    if device_path.startswith("/sdcard/"):
        return "/storage/emulated/0/" + device_path[len("/sdcard/"):]
    return device_path


def mediastore_query_args(device_path: str) -> list[str]:
    """查询某文件是否已被 MediaStore 图片库索引（用规范 _data 路径）。

    整条命令作为单个 adb shell 参数传：分成多个 argv 时，`--where "_data='...'"`
    的单引号会被设备端 shell 剥离 → SQL 变成未加引号的 _data=/storage/... → 永远失配。
    把命令整体交给设备 shell 解析内嵌引号才可靠（路径已过 validate_device_path，
    无引号/分号/$ 等注入字符，可安全内嵌）。"""
    canon = canonical_data_path(device_path)
    return ["shell",
            f"content query --uri content://media/external/images/media "
            f"--where \"_data='{canon}'\""]


# ============================================================
#                  HTTP /upload 端点支撑（纯逻辑）
# ============================================================

def resolve_upload_target(device_path: str | None, filename: str | None) -> tuple[str, str]:
    """由 device_path / filename 推出 (fname, 校验后的 device_path)。
    只给 filename 时按是否图片落 Pictures / Download；两者都缺 → 报错。"""
    fname = sanitize_filename(filename) if filename else None
    if device_path:
        dpath = validate_device_path(device_path)
        fname = fname or dpath.rsplit("/", 1)[-1]
        return fname, dpath
    if not fname:
        raise UploadError("必须提供 device_path 或 filename 之一")
    default_dir = "/sdcard/Pictures" if is_image(fname) else "/sdcard/Download"
    return fname, validate_device_path(f"{default_dir}/{fname}")


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
        if proc.poll() is None:  # 超时等异常路径：杀掉子进程并排空 pipe，防孤儿/死锁
            proc.kill()
            proc.communicate()
        _pid_file(job_id).unlink(missing_ok=True)


def reap_orphans() -> None:
    """server 启动调用：杀掉上次残留的后台子进程并清场。"""
    if not JOBS_DIR.exists():
        return
    # Windows 没有 SIGKILL；os.kill 收到任意非 CTRL_* 信号都会走 TerminateProcess。
    kill_sig = getattr(signal, "SIGKILL", signal.SIGTERM)
    for pf in JOBS_DIR.glob("*.pid"):
        try:
            pid = int(pf.read_text().strip())
            os.kill(pid, kill_sig)
        except (ValueError, OSError):  # ProcessLookupError/PermissionError ⊂ OSError
            pass
        finally:
            pf.unlink(missing_ok=True)
    for pattern in ("*.part", "*.done", "*.name", "dl_*", "sync_*"):
        for p in UPLOADS_DIR.glob(pattern):
            if p.is_file():
                p.unlink(missing_ok=True)
