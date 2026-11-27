"""`_cdp.ws_recv_text` 的帧解析单测：用 socketpair 喂真实字节，不起浏览器。

覆盖三个会真机出问题的形态：
1. 大消息被拆成 FIN=0 的 continuation 帧（Chrome 对大 eval 结果会这么发）——
   只读第一帧会拿到半截 JSON，被误诊成 not_serializable；
2. 分片中间插入 ping/pong 控制帧（必须跳过，不能当正文）；
3. close 帧要抛 ConnectionError（调用方据此判 cdp_timeout）。
"""
import json
import socket
import struct
import threading

import pytest

from _cdp import ws_recv_text


def _frame(payload: bytes, *, fin: bool = True, opcode: int = 0x1) -> bytes:
    """构造一个 server→client 帧（不掩码）。"""
    b0 = (0x80 if fin else 0x00) | opcode
    n = len(payload)
    if n < 126:
        header = bytes([b0, n])
    elif n < 65536:
        header = bytes([b0, 126]) + struct.pack(">H", n)
    else:
        header = bytes([b0, 127]) + struct.pack(">Q", n)
    return header + payload


@pytest.fixture()
def pair():
    client, server = socket.socketpair()
    yield client, server
    client.close()
    server.close()


def _feed(server, data: bytes) -> None:
    def writer():
        try:
            server.sendall(data)
        except OSError:
            pass
    t = threading.Thread(target=writer, daemon=True)
    t.start()
    t.join(2)


def test_single_text_frame(pair):
    client, server = pair
    _feed(server, _frame(b'{"ok": true}'))
    assert ws_recv_text(client) == {"ok": True}


def test_fragmented_message_is_reassembled(pair):
    client, server = pair
    first = b'{"result": {"id": 1, "payload": "'
    second = b'x' * 5000
    third = b'"}}'
    _feed(server, _frame(first, fin=False) + _frame(second, fin=False, opcode=0x0)
          + _frame(third, fin=True, opcode=0x0))
    msg = ws_recv_text(client)
    assert msg["result"]["payload"] == "x" * 5000


def test_control_frames_between_fragments_are_skipped(pair):
    client, server = pair
    data = (_frame(b'{"a":', fin=False)
            + _frame(b"", fin=True, opcode=0x9)      # ping 插在中间
            + _frame(b" 2}", fin=True, opcode=0x0))
    _feed(server, data)
    assert ws_recv_text(client) == {"a": 2}


def test_large_frame_uses_64bit_length(pair):
    client, server = pair
    big = json.dumps({"blob": "y" * 70000}).encode()
    _feed(server, _frame(big))
    assert len(ws_recv_text(client)["blob"]) == 70000


def test_close_frame_raises(pair):
    client, server = pair
    _feed(server, _frame(b"", fin=True, opcode=0x8))
    with pytest.raises(ConnectionError):
        ws_recv_text(client)


def test_utf8_payload_is_decoded(pair):
    client, server = pair
    _feed(server, _frame(json.dumps({"标题": "公众号"}, ensure_ascii=False).encode()))
    assert ws_recv_text(client) == {"标题": "公众号"}


# --- _cdp.call：乱序/错误/正常（真机 bug 常常死在"读到了别人的响应"）--------

def test_call_skips_unrelated_responses(pair):
    """同一个 browser socket 上会有别的命令的响应/事件；必须跳过，不能当成自己的。"""
    import _cdp

    client, server = pair
    _feed(server, _frame(json.dumps({"id": 99, "result": {"other": True}}).encode())
          + _frame(json.dumps({"method": "Page.loadEventFired", "params": {}}).encode())
          + _frame(json.dumps({"id": 7, "result": {"value": 42}}).encode()))
    msg, err = _cdp.call(client, 7, "Runtime.evaluate", {"expression": "1"}, timeout=2.0)
    assert err is None, err
    assert msg["result"] == {"value": 42}


def test_call_surfaces_cdp_error(pair):
    import _cdp

    client, server = pair
    payload = {"id": 3, "error": {"code": -32000, "message": "Object couldn't be returned by value"}}
    _feed(server, _frame(json.dumps(payload).encode()))
    msg, err = _cdp.call(client, 3, "Runtime.evaluate", {}, timeout=2.0)
    assert msg is None
    assert err["reason"] == "cdp_error"
    assert "couldn't be returned by value" in err["message"]


def test_call_times_out_without_response(pair):
    """`call(timeout=…)` 必须真的按自己的预算返回。

    这里给 socket 设 2s 默认超时：如果 `call` 只在外层判 deadline、不把剩余预算落到
    socket 上，它就会阻塞到 2s —— 用例以"耗时 < 1s"快速失败（而不是把整个套件挂死）。
    """
    import time as _time

    import _cdp

    client, _server = pair          # 对端什么都不发
    client.settimeout(2.0)
    started = _time.monotonic()
    msg, err = _cdp.call(client, 5, "Runtime.evaluate", {}, timeout=0.2)
    elapsed = _time.monotonic() - started
    assert msg is None
    assert err["reason"] == "cdp_timeout"
    assert elapsed < 1.0, f"call() blocked {elapsed:.2f}s despite timeout=0.2 — budget not applied to the socket"
    assert client.gettimeout() == 2.0, "原始 socket 超时没有被恢复"


# --- connect_browser：预算必须传到 probe/握手，而不是各用默认超时 ----------

def test_connect_browser_propagates_budget(monkeypatch):
    """`connect_browser(udd, 2.0)` 里每次 probe/握手都不许超过 2.0s。

    否则 probe 用 3s、握手用 5s，实际耗时能到 8s —— 与真机 "eval 偶发 9.3s" 吻合。
    """
    import _cdp

    seen: list[float] = []

    def fake_read_port(udd):
        return 51392

    def fake_probe(port, opener=None, timeout=None):
        seen.append(float(timeout))
        return {"Browser": "Chrome/1", "webSocketDebuggerUrl": "ws://127.0.0.1:1/x"}, None

    def fake_ws(url, timeout=None):
        seen.append(float(timeout))
        return object()

    monkeypatch.setattr(_cdp, "read_port_once", fake_read_port)
    monkeypatch.setattr(_cdp, "probe_version", fake_probe)
    monkeypatch.setattr(_cdp, "ws_connect", fake_ws)

    sock, port = _cdp.connect_browser("/tmp/whatever", 2.0, opener=lambda *a, **k: None,
                                      _sleep=lambda s: None)
    assert sock is not None and port == 51392
    assert seen, "probe/握手都没被调用"
    assert all(0 < t <= 2.0 for t in seen), f"有调用超出了一次性预算: {seen}"


def test_connect_browser_gives_up_within_budget(monkeypatch):
    """端口一直探不通时，必须在预算内返回 (None, None)，而不是无限轮。"""
    import time as _time

    import _cdp

    monkeypatch.setattr(_cdp, "read_port_once", lambda udd: None)
    started = _time.monotonic()
    sock, port = _cdp.connect_browser("/tmp/whatever", 0.3, opener=lambda *a, **k: None,
                                      _sleep=lambda s: _time.sleep(min(s, 0.01)))
    assert (sock, port) == (None, None)
    assert _time.monotonic() - started < 1.0
