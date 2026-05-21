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

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
