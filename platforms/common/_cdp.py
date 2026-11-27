"""共享 CDP 客户端原语（纯 stdlib）—— human_dom 扩展装载与 devtools 能力共用。

为什么自己实现：真机 server venv 里**没有** `websockets` / `cryptography`，
装不起也不该为此加依赖。这里只做 CDP 需要的那一小撮：DevToolsActivePort 探测、
`/json` / `/json/version`、最小 WebSocket 握手与收发、单条命令往返。

安全立场（沿用 human_dom 的 moat）：连接**不带 `Origin` 头**。Chrome 会 403 掉带
Origin 的网页请求，因此本客户端不给网页开可达攻击面；也不要给这里加
`--enable-automation` 之类的开关。

本模块只被平台 server 侧调用；除 `read_port_once` / `port_file_age_ms` 这类纯函数外，
其余函数都会真的碰网络/套接字。
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
from typing import Any, Optional
from urllib.parse import urlparse

WS_OP_TIMEOUT = 8.0          # 单个 ws 连接 / CDP 命令的上限
HTTP_TIMEOUT = 3.0           # /json、/json/version 单次 HTTP 上限
VERSION_PROBE_TIMEOUT = 1.0  # cdp_port 探活：必须快，调用方在等
PORT_FILE_MAX_AGE_MS = 30 * 24 * 3600 * 1000  # 30 天；超出视为时钟不可信


# ---------------------------------------------------------------------------
# DevToolsActivePort
# ---------------------------------------------------------------------------

def read_port_once(udd: str) -> Optional[int]:
    """读 `<udd>/DevToolsActivePort` 的第一行（端口）。缺失/损坏返回 None。"""
    try:
        first = (Path(udd) / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()[0].strip()
        return int(first) if first else None
    except Exception:
        return None


def read_devtools_port(udd: str, timeout: float = 8.0, _sleep=time.sleep) -> Optional[int]:
    """轮询 DevToolsActivePort 直到 Chrome 写完（冷启动/首启会慢几秒）。"""
    deadline = timeout
    while deadline > 0:
        port = read_port_once(udd)
        if port is not None:
            return port
        _sleep(0.2)
        deadline -= 0.2
    return None


def port_file_age_ms(udd: str) -> tuple[Optional[int], Optional[str]]:
    """DevToolsActivePort 的**文件年龄**（毫秒），由设备侧算，避免调用方时钟漂移。

    只在「文件存在但探活失败」时用来区分"Chrome 正在启动（<5s）"与"陈旧文件（>60s）"，
    是**代理指标**不是事实。mtime 是墙钟：NTP 校时可能让它跳变，故做护栏 ——
    结果 < 0 或 > 30 天时返回 ``(None, "clock_skew")``，不给一个错的数字。
    """
    try:
        st = (Path(udd) / "DevToolsActivePort").stat()
    except Exception:
        return None, None
    age_ms = int((time.time() - st.st_mtime) * 1000)
    if age_ms < 0 or age_ms > PORT_FILE_MAX_AGE_MS:
        return None, "clock_skew"
    return age_ms, None


# ---------------------------------------------------------------------------
# HTTP 端点（/json、/json/version）
# ---------------------------------------------------------------------------

def http_json(url: str, opener=urllib.request.urlopen, timeout: float = HTTP_TIMEOUT):
    with opener(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe_version(port: int, opener=urllib.request.urlopen,
                  timeout: float = VERSION_PROBE_TIMEOUT) -> tuple[Optional[dict], Optional[str]]:
    """真打一次 `/json/version` 判断端点是否**活着**。

    返回 ``(info, reason)``；``info`` 需含非空 `Browser` 才算活（陈旧 DevToolsActivePort
    在 Chrome 崩溃/被杀后仍留在盘上，只看文件会误判）。
    reason ∈ ``version_probe_failed`` / ``handshake_timeout``（有端点但拿不到 ws 地址）。
    """
    try:
        info = http_json(f"http://127.0.0.1:{int(port)}/json/version", opener, timeout=timeout)
    except Exception:
        return None, "version_probe_failed"
    if not isinstance(info, dict) or not str(info.get("Browser") or "").strip():
        return None, "version_probe_failed"
    if not str(info.get("webSocketDebuggerUrl") or "").strip():
        # 端点活着但拿不到可连的 ws（极少见；对调用方而言等同于"现在还接不上"）
        return info, "handshake_timeout"
    return info, None


def list_targets(port: int, opener=urllib.request.urlopen,
                 timeout: float = HTTP_TIMEOUT) -> tuple[Optional[list], Optional[str]]:
    """`GET /json` → 目标列表。返回 ``(targets, reason)``。"""
    try:
        data = http_json(f"http://127.0.0.1:{int(port)}/json", opener, timeout=timeout)
    except Exception:
        return None, "version_probe_failed"
    if not isinstance(data, list):
        return None, "version_probe_failed"
    return data, None


def page_targets(port: int, opener=urllib.request.urlopen,
                 timeout: float = HTTP_TIMEOUT) -> tuple[list, Optional[str]]:
    """只保留可连接的 page 目标（带 webSocketDebuggerUrl）。"""
    data, reason = list_targets(port, opener, timeout)
    if data is None:
        return [], reason
    pages = [
        t for t in data
        if isinstance(t, dict)
        and t.get("type") == "page"
        and t.get("webSocketDebuggerUrl")
    ]
    return pages, None


# ---------------------------------------------------------------------------
# 最小 WebSocket（client → CDP）
# ---------------------------------------------------------------------------

def ws_connect(ws_url: str, timeout: float = WS_OP_TIMEOUT):
    """连 CDP 的 ws 端点。**不带 Origin 头**（见模块注释）。"""
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


def ws_send(sock, obj: dict) -> None:
    """发一帧 masked text（client → server 必须掩码）。"""
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


def _read_frame(sock, rd) -> tuple[bool, int, bytes]:
    """读一帧：返回 (fin, opcode, payload)。server → client 的帧不掩码。"""
    b0, b1 = rd(2)
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack(">H", rd(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", rd(8))[0]
    payload = rd(length) if length else b""
    return fin, opcode, payload


def ws_recv_text(sock) -> dict:
    """读一条完整消息（server → client），**支持分片**，跳过控制帧，返回 JSON。

    为什么要处理分片：CDP 的大返回（`Runtime.evaluate` 取 2 MiB 数据）Chrome 可能拆成
    FIN=0 的 continuation 帧；只读第一帧会得到半截 JSON → 解析失败 → 被上层当成
    `not_serializable`，把一个"结果太大"的问题误诊成序列化问题。

    协议要点：`opcode 0x1` = 文本帧，`0x0` = continuation（承接上一帧），
    `0x8/0x9/0xA` = close/ping/pong（可插在分片中间，直接跳过）。
    """
    def rd(k: int) -> bytes:
        buf = b""
        while len(buf) < k:
            chunk = sock.recv(k - len(buf))
            if not chunk:
                raise ConnectionError("ws: 对端中途关闭")
            buf += chunk
        return buf

    chunks: list[bytes] = []
    while True:
        fin, opcode, payload = _read_frame(sock, rd)
        if opcode == 0x8:
            raise ConnectionError("ws: 收到 close")
        if opcode in (0x9, 0xA):      # ping/pong 不参与消息体
            continue
        chunks.append(payload)
        if fin:
            return json.loads(b"".join(chunks).decode("utf-8"))


def cdp_call(sock, cid: int, method: str, params: Optional[dict] = None,
             timeout: float = WS_OP_TIMEOUT) -> Optional[dict]:
    """发一条 CDP 命令，读到 `id` 匹配的响应（丢弃中途事件）。失败返回 None。

    保留这个"只返回响应体"的旧签名，供 human_dom 扩展装载继续使用；
    需要原因码的调用方用 :func:`call`。
    """
    msg, _err = call(sock, cid, method, params, timeout)
    return msg


def call(sock, cid: int, method: str, params: Optional[dict] = None,
         timeout: float = WS_OP_TIMEOUT) -> tuple[Optional[dict], Optional[dict]]:
    """同 :func:`cdp_call`，但返回 ``(response, error)``。

    ``error`` = ``{"reason": "cdp_timeout" | "cdp_error", "message": str}``；
    CDP 层的拒答（例如 returnByValue 序列化失败）会带原始 message，供上层细分。

    **超时必须落到 socket 上**：只在外层循环判 deadline 是不够的——``recv`` 用的是
    socket 自己的超时（``ws_connect`` 设的那个，通常 5s），于是 ``call(timeout=0.2)``
    实际会阻塞到 5s；若 socket 没有设超时（测试里的裸 socketpair、或别的调用方），
    会**永久阻塞**。所以每轮接收前把 socket 超时设为"剩余预算"，结束后恢复原值。
    """
    try:
        ws_send(sock, {"id": cid, "method": method, "params": params or {}})
    except Exception as exc:  # 连接已坏
        return None, {"reason": "cdp_timeout", "message": f"send failed: {exc}"}

    try:
        previous = sock.gettimeout()
    except Exception:                       # 非 socket 对象（测试替身）
        previous = None
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                sock.settimeout(remaining)
            except Exception:
                pass
            try:
                msg = ws_recv_text(sock)
            except socket.timeout:
                return None, {"reason": "cdp_timeout", "message": f"{method} timed out"}
            except Exception as exc:
                return None, {"reason": "cdp_timeout", "message": f"recv failed: {exc}"}
            if msg.get("id") == cid:
                if "error" in msg:
                    err = msg.get("error") or {}
                    return None, {"reason": "cdp_error",
                                  "message": str(err.get("message") or err)}
                return msg, None
            # 其它消息（事件 / 别的命令的响应）跳过
    finally:
        try:
            sock.settimeout(previous)
        except Exception:
            pass
    return None, {"reason": "cdp_timeout", "message": f"{method} timed out"}


# ---------------------------------------------------------------------------
# 组合：轮询端口 + 探活 + 连 browser 端点
# ---------------------------------------------------------------------------

def connect_browser(udd: str, overall_timeout: float, opener=urllib.request.urlopen,
                    _sleep=time.sleep) -> tuple[Optional[Any], Optional[int]]:
    """轮询 DevToolsActivePort + `/json/version` 直到 browser ws 连上，返回 `(sock, port)`。

    兼容两种现实：(a) 全新 profile 冷启动慢；(b) 上次崩溃留下的**陈旧端口文件**——
    新 Chrome 会改写它，死端口的 `/json/version` 失败，于是继续轮。
    """
    end = time.monotonic() + overall_timeout
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return None, None
        port = read_port_once(udd)
        if port is not None:
            # 预算必须往里传：否则 probe/握手各自用默认超时（3s + 5s），
            # `connect_browser(..., 3.0)` 实际能跑 8s —— 真机实测 eval 偶发 9.3s
            # 与此吻合（ACTIVATE_TIMEOUT 3s + WS_OP_TIMEOUT 5s + 激活）。
            probe_budget = max(0.05, min(VERSION_PROBE_TIMEOUT, remaining))
            info, reason = probe_version(port, opener, timeout=probe_budget)
            if info is not None and reason is None:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return None, None
                handshake_budget = max(0.05, min(WS_OP_TIMEOUT, remaining))
                try:
                    return ws_connect(info["webSocketDebuggerUrl"], timeout=handshake_budget), port
                except Exception:
                    pass
        if time.monotonic() >= end:
            return None, None
        _sleep(min(0.3, max(0.0, end - time.monotonic())))


def close_quietly(sock) -> None:
    try:
        sock.close()
    except Exception:
        pass
