"""
Shared file-system operations extracted from the platform servers (mac/windows).

These are plain functions — no MCP decorators, no Annotated wrappers, no ctx.
P1b will re-wrap them as ``@mcp.tool`` entries inside each server.

Key fix vs. the Windows server: ``Path(...).expanduser()`` is applied to every
path argument so that ``~``-prefixed paths resolve correctly on all OSes.
The macOS server already used ``expanduser()``; the Windows server was missing
it — that latent bug is corrected here.
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def read_file(
    path: str,
    offset: int = 0,
    length: int = 1000,
    encoding: str = "utf-8",
) -> dict:
    """Read a text file. Returns metadata + selected lines slice."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"path not found: {path}"}
    if not p.is_file():
        return {"error": f"not a file: {path}"}
    size = p.stat().st_size
    try:
        with p.open("r", encoding=encoding, errors="replace") as f:
            all_lines = f.read().splitlines()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "size_bytes": size}

    total = len(all_lines)
    if offset < 0:
        start = max(0, total + offset)
    else:
        start = min(offset, total)
    end = min(start + length, total)
    return {
        "path": str(p),
        "size_bytes": size,
        "total_lines": total,
        "from_line": start,
        "to_line": end,
        "content": "\n".join(all_lines[start:end]),
    }


def write_file(
    path: str,
    content: str,
    mode: str = "rewrite",
    encoding: str = "utf-8",
) -> dict:
    """Write or append text to a file. Creates parent directories if needed."""
    if mode not in ("rewrite", "append"):
        return {"error": "mode must be 'rewrite' or 'append'"}
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with p.open("a" if mode == "append" else "w", encoding=encoding) as f:
            f.write(content)
        return {"ok": True, "path": str(p), "bytes_written": len(content.encode(encoding))}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def edit_block(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    encoding: str = "utf-8",
) -> dict:
    """Find-and-replace inside a text file. Fails if old_string is not unique unless replace_all."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"path not found: {path}"}
    try:
        text = p.read_text(encoding=encoding)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    count = text.count(old_string)
    if count == 0:
        return {"error": "old_string not found", "occurrences": 0}
    if count > 1 and not replace_all:
        return {"error": "old_string not unique; pass replace_all=True or extend with surrounding context", "occurrences": count}
    new_text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    p.write_text(new_text, encoding=encoding)
    return {"ok": True, "path": str(p), "replaced": count if replace_all else 1}


def list_directory(
    path: str,
    depth: int = 1,
    include_hidden: bool = False,
) -> dict:
    """List entries in a directory."""
    p = Path(path).expanduser()
    if not p.exists() or not p.is_dir():
        return {"error": f"not a directory: {path}"}

    entries: list[dict] = []

    def walk(d: Path, current_depth: int) -> None:
        try:
            for child in sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if not include_hidden and child.name.startswith("."):
                    continue
                try:
                    is_dir = child.is_dir()
                    entry: dict[str, Any] = {
                        "name": child.name,
                        "path": str(child),
                        "type": "dir" if is_dir else "file",
                    }
                    if not is_dir:
                        try:
                            entry["size"] = child.stat().st_size
                        except OSError:
                            entry["size"] = None
                    entries.append(entry)
                    if is_dir and current_depth < depth:
                        walk(child, current_depth + 1)
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            return

    walk(p, 1)
    return {"path": str(p), "entries": entries, "count": len(entries)}


def create_directory(
    path: str,
) -> dict:
    """Create a directory (mkdir -p semantics)."""
    p = Path(path).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def move_file(
    src: str,
    dst: str,
) -> dict:
    """Move or rename a file or directory."""
    s = Path(src).expanduser()
    d = Path(dst).expanduser()
    if not s.exists():
        return {"error": f"src not found: {src}"}
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return {"ok": True, "src": str(s), "dst": str(d)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def get_file_info(
    path: str,
) -> dict:
    """Return stat-like metadata for a path."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"path not found: {path}"}
    try:
        st = p.stat()
        return {
            "path": str(p),
            "type": "dir" if p.is_dir() else "file",
            "size_bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "ctime": datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat(),
            "is_symlink": p.is_symlink(),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# 二进制收发（file_put / file_get）
#
# 为什么需要：``write_file`` / ``read_file`` 只走 UTF-8 文本（按行），推图片/HTML
# 这类字节只能靠临时 http.server + curl 绕一圈。这里给一对**字节级**原语：
# 原子写、回 sha256 供对账、超限报错**绝不截断**。
# ---------------------------------------------------------------------------

MAX_TRANSFER_BYTES = 4 * 1024 * 1024   # 单文件上限（base64 后 ~5.6 MiB，留 MCP 余量）

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400  # Windows: FILE_ATTRIBUTE_REPARSE_POINT


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_reparse(path: Path, st: os.stat_result) -> bool:
    """该路径本身是否符号链接 / junction（Windows 的 junction 在 3.10/3.11 上
    ``islink()`` 返回 False，必须看 st_file_attributes 或用 3.12 的 ``isjunction``）。"""
    try:
        if os.path.islink(path):
            return True
    except OSError:
        pass
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            if isjunction(path):
                return True
        except OSError:
            pass
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def first_reparse_component(path: str) -> Optional[str]:
    r"""从盘符/根开始**逐段**检查，返回第一个 reparse point 的绝对路径；没有则 None。

    为什么不直接比较 ``realpath == abspath``：Windows 的 8.3 短路径、盘符/目录大小写、
    结尾分隔符都会让字符串比较假红。逐段判断不依赖字符串相等，且**不会**把
    ``C:\Users\All Users`` 这类系统自带的 junction 误判成用户路径问题。
    """
    p = Path(path).expanduser()
    parts = p.parts
    if not parts:
        return None
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            st = os.lstat(current)
        except OSError:
            continue          # 尚不存在（写新文件的正常情况）→ 继续往下看
        if _is_reparse(current, st):
            return str(current)
    return None


def put_bytes(path: str, data: bytes, follow_symlinks: bool = False) -> dict:
    """把字节**原子**写到 ``path``（临时文件 + ``os.replace``）。

    返回 ``{ok, path, bytes, sha256}``；失败带 `reason`：
    ``file_too_large`` / ``symlink_not_allowed`` / ``write_failed``。
    回 sha256 是硬要求：否则"推上去的那份"没法对账，只能拉回来比。
    """
    p = Path(path).expanduser()
    size = len(data)
    if size > MAX_TRANSFER_BYTES:
        return {"ok": False, "reason": "file_too_large", "bytes": size,
                "max_bytes": MAX_TRANSFER_BYTES}
    if not follow_symlinks:
        hit = first_reparse_component(str(p))
        if hit:
            return {"ok": False, "reason": "symlink_not_allowed",
                    "real_path": hit, "hint": "pass follow_symlinks=True if this is intended"}
    tmp: Optional[Path] = None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.part-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, p)
    except Exception as exc:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        return {"ok": False, "reason": "write_failed", "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "path": str(p), "bytes": size, "sha256": sha256_bytes(data)}


def get_bytes(path: str) -> dict:
    """读回一个文件的原始字节（base64）+ 元数据；超限报错，**不截断**。"""
    p = Path(path).expanduser()
    try:
        st = p.stat()
    except FileNotFoundError:
        return {"ok": False, "reason": "not_found", "path": str(p)}
    except Exception as exc:
        return {"ok": False, "reason": "stat_failed", "error": f"{type(exc).__name__}: {exc}"}
    if p.is_dir():
        return {"ok": False, "reason": "is_directory", "path": str(p)}
    if st.st_size > MAX_TRANSFER_BYTES:
        return {"ok": False, "reason": "file_too_large", "bytes": st.st_size,
                "max_bytes": MAX_TRANSFER_BYTES}
    try:
        data = p.read_bytes()
    except Exception as exc:
        return {"ok": False, "reason": "read_failed", "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "path": str(p),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        "content_b64": base64.b64encode(data).decode("ascii"),
    }
