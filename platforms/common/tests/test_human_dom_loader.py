"""_loader.py: CDP Extensions.loadUnpacked 装扩展(纯 stdlib ws 客户端)。
用一个独立实现的最小 ws 假浏览器验 _loader 的客户端，无需真 Chrome。"""
import base64, hashlib, json, socket, struct, sys, threading, time
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capabilities.human_dom import _loader


# ---------- 独立(非 _loader)的假浏览器: /json/version + browser ws loadUnpacked ----------

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _make_handler(state):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            host = self.headers.get("Host", "127.0.0.1")
            if self.path == "/json/version":
                body = json.dumps({
                    "webSocketDebuggerUrl": f"ws://{host}/devtools/browser/fake"
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/devtools/browser/fake" and \
                    self.headers.get("Upgrade", "").lower() == "websocket":
                # 记录 client 是否带 Origin(网页会带→真 Chrome 会 403; 我方 no-Origin)
                state["origin_seen"] = self.headers.get("Origin")
                k = self.headers.get("Sec-WebSocket-Key")
                acc = base64.b64encode(hashlib.sha1((k + _WS_GUID).encode()).digest()).decode()
                self.connection.sendall((
                    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                    "Connection: Upgrade\r\nSec-WebSocket-Accept: " + acc + "\r\n\r\n"
                ).encode())
                # 读一帧(client→server 掩码)
                b = self.rfile.read(2)
                ln = b[1] & 0x7f
                if ln == 126:
                    ln = struct.unpack(">H", self.rfile.read(2))[0]
                elif ln == 127:
                    ln = struct.unpack(">Q", self.rfile.read(8))[0]
                mask = self.rfile.read(4)
                data = self.rfile.read(ln)
                msg = json.loads(bytes(c ^ mask[i % 4] for i, c in enumerate(data)).decode())
                state["request"] = msg
                # 回一帧(server→client 不掩码)
                if msg.get("method") == "Extensions.loadUnpacked":
                    reply = json.dumps({"id": msg["id"], "result": {"id": "fakeextid123"}}).encode()
                else:
                    reply = json.dumps({"id": msg["id"], "error": {"message": "unknown"}}).encode()
                out = bytearray([0x81])
                n = len(reply)
                if n < 126:
                    out.append(n)
                else:
                    out.append(126); out += struct.pack(">H", n)
                out += reply
                self.connection.sendall(bytes(out))
                return
            self.send_response(404)
            self.end_headers()
    return H


class _FakeBrowser:
    def __init__(self):
        self.state = {}
        ThreadingTCPServer.allow_reuse_address = True
        self.srv = ThreadingTCPServer(("127.0.0.1", 0), _make_handler(self.state))
        self.port = self.srv.server_address[1]
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)

    def __enter__(self):
        self.th.start()
        return self

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()


# ---------------------------- tests ----------------------------

def test_read_devtools_port_reads_first_line(tmp_path):
    udd = tmp_path / "udd"
    udd.mkdir()
    (udd / "DevToolsActivePort").write_text("65123\n/devtools/browser/abc\n")
    assert _loader._read_devtools_port(str(udd), timeout=1.0) == 65123


def test_read_devtools_port_absent_returns_none_fast(tmp_path):
    calls = []
    port = _loader._read_devtools_port(str(tmp_path / "nope"), timeout=0.6,
                                       _sleep=lambda s: calls.append(s))
    assert port is None
    assert calls, "应有轮询 sleep(未阻塞真实时间)"


def test_load_dom_extension_happy_path(tmp_path):
    udd = tmp_path / "udd"
    udd.mkdir()
    ext = tmp_path / "ext"
    ext.mkdir()
    with _FakeBrowser() as fb:
        (udd / "DevToolsActivePort").write_text(f"{fb.port}\n/devtools/browser/fake\n")
        r = _loader.load_dom_extension(str(udd), str(ext), timeout=5.0)
        assert r["ok"] is True and r["id"] == "fakeextid123"
        assert fb.state["request"]["params"]["path"] == str(ext)
        assert fb.state["request"]["method"] == "Extensions.loadUnpacked"
        # 我方客户端 no-Origin(不给网页开 CDP 口子)
        assert fb.state["origin_seen"] is None
        # 装成功写 loaded.json 标记(installed 的即时可靠信号)
        marker = json.loads((ext / "loaded.json").read_text(encoding="utf-8"))
        assert marker["loaded"] is True and marker["extid"] == "fakeextid123"


def test_load_dom_extension_no_port_degrades(tmp_path):
    # 无 DevToolsActivePort → 返回 ok:False, 不抛(不阻断开浏览器)
    r = _loader.load_dom_extension(str(tmp_path / "udd"), "/x", timeout=0.4,
                                   _sleep=lambda s: None)
    assert r["ok"] is False and "error" in r


# --- moat 回归护栏(architect 评审条件1): 锁死「零自动化痕迹」不变量 ---
# 这三条是 moat 最脆弱点: 后人若给 loader 加 Runtime.enable(触发控制台 getter 侧信道)、
# 让 CDP client 常驻不 detach、或误加 --enable-automation(navigator.webdriver→true),
# moat 会【静默破裂】。下面测试红即告警。

def test_moat_launch_never_enables_automation():
    from capabilities.browser._human_browser import _human_launch_args
    for rd in (True, False):
        args = _human_launch_args("/c", "/udd", None, "http://x", remote_debug=rd)
        assert not any("enable-automation" in a for a in args), "moat: 绝不加 --enable-automation"


def test_moat_loader_never_enables_cdp_domains():
    # 只扫 CDP domain enable 的方法调用(会挂 domain/触发 Runtime.enable 控制台侧信道)。
    # --enable-automation 是启动 flag, 由 test_moat_launch_never_enables_automation 覆盖;
    # loader moat 注释里出现「不加 --enable-automation」是文档、不算违规。
    import inspect
    src = inspect.getsource(_loader)
    for forbidden in ("Runtime.enable", "Page.enable", "Network.enable", "DOM.enable"):
        assert forbidden not in src, (
            f"moat 护栏: loader 出现 {forbidden} —— 会挂着 CDP domain/触发侧信道, 破零自动化痕迹。"
            "确定性装扩展只该发 Extensions.loadUnpacked + Page.navigate 后立即 detach。")


def test_moat_loader_detaches_after_load():
    # loader 装完必须关连接(不常驻 CDP client): 源码里 load_dom_extension 有 sock.close()
    import inspect
    src = inspect.getsource(_loader.load_dom_extension)
    assert "close()" in src, "moat: load_dom_extension 必须装完 detach(sock.close)"
