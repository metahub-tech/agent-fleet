"""Shared recursive file-content search operations (P1b wraps these as MCP tools).

Extracted from platforms/macos/server/mac_device_mcp.py (canonical reference).
The only divergence from the Windows counterpart is a missing .expanduser() on
the path in start_search — corrected here.

State:
  _searches        — dict keyed by search_id
  _searches_lock   — threading.Lock protecting _searches
  _search_id_counter — monotonic integer for unique IDs
  _SEARCH_BUFFER_LIMIT — maximum matches kept in memory per search

Functions:
  _run_search(search_id, root, regex, file_glob) — background worker thread
  start_search(path, pattern, file_glob, case_sensitive) -> dict
  get_more_search_results(search_id, offset, length) -> dict
  list_searches() -> list[dict]
  stop_search(search_id) -> dict
"""

import re
import threading
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
#                  MODULE-LEVEL SEARCH STATE
# ============================================================
_searches_lock = threading.Lock()
_searches: dict[str, dict] = {}
_search_id_counter = 0
_SEARCH_BUFFER_LIMIT = 5000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_search(search_id: str, root: Path, regex: re.Pattern, file_glob: str) -> None:
    try:
        for f in root.rglob(file_glob):
            with _searches_lock:
                slot = _searches.get(search_id)
                if slot is None or slot["stop"]:
                    return
            if not f.is_file():
                continue
            try:
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    for ln, line in enumerate(fh, start=1):
                        if regex.search(line):
                            with _searches_lock:
                                slot = _searches.get(search_id)
                                if slot is None or slot["stop"]:
                                    return
                                if len(slot["matches"]) < _SEARCH_BUFFER_LIMIT:
                                    slot["matches"].append(
                                        {"file": str(f), "line": ln, "text": line.rstrip("\r\n")}
                                    )
                                else:
                                    slot["truncated"] = True
                                    return
            except (PermissionError, OSError, UnicodeDecodeError):
                continue
    finally:
        with _searches_lock:
            slot = _searches.get(search_id)
            if slot is not None:
                slot["done"] = True


def start_search(
    path: str,
    pattern: str,
    file_glob: str = "*",
    case_sensitive: bool = False,
) -> dict:
    """Start a recursive file-content search. Returns search_id; poll with get_more_search_results."""
    global _search_id_counter
    root = Path(path).expanduser()  # bug fix: win server was missing .expanduser()
    if not root.exists() or not root.is_dir():
        return {"error": f"not a directory: {path}"}
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"error": f"invalid regex: {e}"}

    with _searches_lock:
        _search_id_counter += 1
        search_id = f"s{_search_id_counter}"
        _searches[search_id] = {
            "started_at": _now(),
            "root": str(root),
            "pattern": pattern,
            "file_glob": file_glob,
            "case_sensitive": case_sensitive,
            "matches": [],
            "done": False,
            "stop": False,
            "truncated": False,
        }
    threading.Thread(target=_run_search, args=(search_id, root, regex, file_glob), daemon=True).start()
    # NOTE: reading _searches[search_id]["started_at"] after releasing the lock is a
    # pre-existing wart in both servers (harmless because the slot is never deleted here);
    # copied faithfully from the canonical mac reference.
    return {"search_id": search_id, "started_at": _searches[search_id]["started_at"].isoformat()}


def get_more_search_results(
    search_id: str,
    offset: int = 0,
    length: int = 100,
) -> dict:
    """Fetch matches from a running or completed search."""
    with _searches_lock:
        slot = _searches.get(search_id)
        if slot is None:
            return {"error": f"search_id {search_id} not found"}
        all_matches = list(slot["matches"])
        done = slot["done"]
        truncated = slot["truncated"]

    total = len(all_matches)
    end = min(offset + length, total)
    return {
        "search_id": search_id,
        "total_matches": total,
        "from_index": offset,
        "to_index": end,
        "matches": all_matches[offset:end],
        "done": done,
        "truncated": truncated,
    }


def list_searches() -> list[dict]:
    """List all in-flight or recent searches."""
    out: list[dict] = []
    with _searches_lock:
        for sid, slot in _searches.items():
            out.append(
                {
                    "search_id": sid,
                    "root": slot["root"],
                    "pattern": slot["pattern"],
                    "started_at": slot["started_at"].isoformat(),
                    "matches": len(slot["matches"]),
                    "done": slot["done"],
                    "truncated": slot["truncated"],
                }
            )
    return out


def stop_search(
    search_id: str,
) -> dict:
    """Cancel a running search."""
    with _searches_lock:
        slot = _searches.get(search_id)
        if slot is None:
            return {"error": f"search_id {search_id} not found"}
        slot["stop"] = True
    return {"ok": True, "search_id": search_id}
