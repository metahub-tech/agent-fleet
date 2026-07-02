"""human_dom 扩展装载: 起浏览器后经 CDP `Extensions.loadUnpacked` 把烤好的 per-profile
副本装进该 profile 的 Chrome —— 零 GUI / 零视觉 / 零 DPI 依赖(Chrome 137+ 禁了
--load-extension, 这是官方给自动化的替代, Playwright 也走这条; test-win11/Chrome149 实证)。

纯 stdlib(真机 server venv 无 cryptography/websockets 依赖)。永不抛到 server ——
装失败只返回 {ok:False,error}, 绝不阻断开浏览器。

moat: 起 Chrome 只加 `--remote-debugging-port=0`(临时端口/仅 127.0.0.1)、不加
--enable-automation → navigator.webdriver 仍 false; 本客户端【不带 Origin 头】连 CDP,
网页(必带 Origin)会被 Chrome 默认 403, 故不给网页开可达攻击面(实证)。
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC6455 magic(仅 handshake 断言用)


def _read_devtools_port(udd: str, timeout: float = 8.0, _sleep=time.sleep) -> "int | None":
    """轮询 <udd>/DevToolsActivePort 拿 Chrome 起后写的临时 debug 端口(首行=端口)。
    Chrome 写该文件有延迟, 故重试到 timeout。"""
    pf = Path(udd) / "DevToolsActivePort"
    deadline = timeout
    while deadline > 0:
        try:
            first = pf.read_text(encoding="utf-8").splitlines()[0].strip()
            if first:
                return int(first)
        except Exception:
            pass
        _sleep(0.2)
        deadline -= 0.2
    return None


def _ws_connect(ws_url: str, timeout: float = 8.0):
    """连 CDP browser ws。不带 Origin 头(见模块注释)。"""
    u = urlparse(ws_url)
    sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
    sock.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET {u.path} HTTP/1.1\r\n"
        f"Host: {u.hostname}:{u.port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("ws handshake: 对端关闭")
        buf += chunk
    status = buf.split(b"\r\n", 1)[0].decode("latin1")
    if "101" not in status:
        raise ConnectionError(f"ws handshake 失败: {status}")
    return sock


def _ws_send(sock, obj: dict) -> None:
    """发一帧 masked text(client→server 必须掩码)。"""
    data = json.dumps(obj).encode()
    hdr = bytearray([0x81])  # FIN + opcode=text
    n = len(data)
    if n < 126:
        hdr.append(0x80 | n)
    elif n < 65536:
        hdr.append(0x80 | 126)
        hdr += struct.pack(">H", n)
    else:
        hdr.append(0x80 | 127)
        hdr += struct.pack(">Q", n)
    mask = os.urandom(4)
    hdr += mask
    hdr += bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(bytes(hdr))


def _ws_recv_text(sock) -> dict:
    """读一帧 server→client(不掩码), 跳过非数据帧, 返回 JSON。"""
    def rd(k):
        r = b""
        while len(r) < k:
            c = sock.recv(k - len(r))
            if not c:
                raise ConnectionError("ws: 对端中途关闭")
            r += c
        return r
    while True:
        b0, b1 = rd(2)
        opcode = b0 & 0x0f
        ln = b1 & 0x7f
        if ln == 126:
            ln = struct.unpack(">H", rd(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", rd(8))[0]
        payload = rd(ln)
        if opcode in (0x8, 0x9, 0xA):  # close/ping/pong → 跳过
            if opcode == 0x8:
                raise ConnectionError("ws: 收到 close")
            continue
        return json.loads(payload.decode("utf-8"))


def _cdp_call(sock, cid: int, method: str, params: dict = None, timeout: float = 8.0):
    """发一条 CDP 命令, 读到 id 匹配的响应(丢弃中途的事件)。"""
    _ws_send(sock, {"id": cid, "method": method, "params": params or {}})
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msg = _ws_recv_text(sock)
        except Exception:
            return None
        if msg.get("id") == cid:
            return msg
    return None


def load_dom_extension(udd: str, ext_dir, timeout: float = 10.0,
                       _open=urllib.request.urlopen, _sleep=time.sleep) -> dict:
    """在【已起、带 --remote-debugging-port=0 的】Chrome(该 udd)里经 CDP
    Extensions.loadUnpacked 装 ext_dir。返回 {ok:True,id} 或 {ok:False,error}。永不抛。"""
    port = _read_devtools_port(udd, timeout=timeout, _sleep=_sleep)
    if port is None:
        return {"ok": False, "error": "DevToolsActivePort 未就绪(chrome debug 端口没起来)"}
    try:
        raw = _open(f"http://127.0.0.1:{port}/json/version", timeout=5).read()
        ws_url = json.loads(raw.decode("utf-8"))["webSocketDebuggerUrl"]
    except Exception as e:
        return {"ok": False, "error": f"取 CDP browser ws 失败: {type(e).__name__}: {e}"}
    sock = None
    try:
        sock = _ws_connect(ws_url, timeout=timeout)
        reply = _cdp_call(sock, 1, "Extensions.loadUnpacked", {"path": str(ext_dir)}, timeout=timeout)
        if reply is None:
            return {"ok": False, "error": "loadUnpacked 无响应"}
        if "error" in reply:
            return {"ok": False, "error": f"loadUnpacked 报错: {reply['error'].get('message', '?')}"}
        return {"ok": True, "id": reply.get("result", {}).get("id")}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
