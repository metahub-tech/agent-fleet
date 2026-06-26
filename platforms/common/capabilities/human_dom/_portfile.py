"""桥端口在 server 启动时一次确定并持久化; 扩展安装读该持久值(保 server↔扩展端口一致)。"""
from __future__ import annotations
import os, socket

def _portfile_path(mcp_port: int) -> str:
    return os.path.expanduser(f"~/.fleet/dom-bridge-{mcp_port}.port")

def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port)); return True
        except OSError:
            return False

def _read(pf: str):
    try:
        return int(open(pf).read().strip())
    except Exception:
        return None

def _write(pf: str, port: int) -> None:
    os.makedirs(os.path.dirname(pf), exist_ok=True)
    open(pf, "w").write(str(port))

def resolve_bridge_port(mcp_port: int, override=None, portfile=None, is_free=None) -> int:
    is_free = is_free or _is_free
    pf = portfile or _portfile_path(mcp_port)
    if override is not None:
        chosen = int(override)
    else:
        persisted = _read(pf)
        if persisted and is_free(persisted):
            return persisted
        chosen = mcp_port + 13
        while not is_free(chosen):
            chosen += 1
    _write(pf, chosen)
    return chosen
