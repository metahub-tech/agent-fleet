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
