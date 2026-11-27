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

import json
import time
import urllib.request
from pathlib import Path
from typing import Optional

# 底层 CDP 原语已抽到平台共享的 `_cdp`（human_dom 与 devtools 能力共用）。
# 这里沿用旧的私有名做**模块级别名**：既有调用方与单测（monkeypatch `_loader._http_json`
# 等）语义保持不变；`_http_json` / `_connect_browser` / `_navigate` 仍在本模块，
# 因为它们要接受测试注入的 opener。
from _cdp import (  # noqa: E402  (与下方既有 import 同属模块级)
    HTTP_TIMEOUT as _HTTP_TIMEOUT,
    WS_OP_TIMEOUT as _WS_OP_TIMEOUT,
    cdp_call as _cdp_call,
    read_devtools_port as _read_devtools_port,
    read_port_once as _read_port_once,
    ws_connect as _ws_connect,
    ws_recv_text as _ws_recv_text,
    ws_send as _ws_send,
)


def _http_json(url: str, _open, timeout: float = _HTTP_TIMEOUT):
    with _open(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _connect_browser(udd, overall_timeout, _open, _sleep):
    """轮询 DevToolsActivePort + /json/version 直到 browser ws 连上, 返回 (sock, port)。
    兼容: (a)全新 profile 冷启动慢(要建目录/first-run); (b)上次 Chrome 崩溃留下的【陈旧端口】——
    新 Chrome 会改写 DevToolsActivePort, 死端口的 /json/version 失败故继续轮直到读到活端口。
    连不上返回 (None, None)。"""
    end = time.time() + overall_timeout
    while True:
        port = _read_port_once(udd)
        if port is not None:
            try:
                ws_url = _http_json(f"http://127.0.0.1:{port}/json/version", _open)["webSocketDebuggerUrl"]
                return _ws_connect(ws_url), port
            except Exception:
                pass  # 端口未就绪/已死 → 等新 Chrome 改写后再试
        if time.time() >= end:
            return None, None
        _sleep(0.3)


def _navigate(port, url, _open):
    """装完扩展后把当前 page 导航到 url。**必须 load 之后再 navigate**: content script 只在
    【新导航】时注入; 若启动就带 url, 扩展装好前页面已加载→脚本不注入→桥连不上(真机实证)。"""
    try:
        pages = _http_json(f"http://127.0.0.1:{port}/json", _open)
        page = [t for t in pages if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if not page:
            return False
        ps = _ws_connect(page[0]["webSocketDebuggerUrl"])
        try:
            _cdp_call(ps, 2, "Page.navigate", {"url": url})
            return True
        finally:
            try:
                ps.close()
            except Exception:
                pass
    except Exception:
        return False


def _write_loaded_marker(ext_dir, extid):
    """装成功后写 <ext_dir>/loaded.json —— human_dom_status 判 installed 的可靠即时信号。
    不用 Chrome 的 Secure Preferences: 它 flush 惰性(真机实证 open 后数秒仍空), 即时查盘不可靠;
    这个标记由我方在装成功那刻写。best-effort, 失败不影响装扩展。"""
    try:
        Path(ext_dir, "loaded.json").write_text(
            json.dumps({"loaded": True, "extid": extid}), encoding="utf-8")
    except Exception:
        pass


def load_dom_extension(udd: str, ext_dir, navigate_url=None, timeout: float = 20.0,
                       _open=urllib.request.urlopen, _sleep=time.sleep) -> dict:
    """在【已起、带 --remote-debugging-port=0 的】Chrome(该 udd)里经 CDP
    Extensions.loadUnpacked 装 ext_dir; 装完(可选)navigate 到 navigate_url 让 content script 注入。
    timeout 是【连上 debug 端口】的整体预算(冷启动新 profile 可能数秒); 单步 ws/CDP 另有上限。
    返回 {ok:True,id[,navigated]} 或 {ok:False,error}。永不抛。"""
    sock, port = _connect_browser(udd, timeout, _open, _sleep)
    if sock is None:
        return {"ok": False, "error": "chrome debug 端口未就绪(DevToolsActivePort/json 未响应)"}
    try:
        reply = _cdp_call(sock, 1, "Extensions.loadUnpacked", {"path": str(ext_dir)})
        if reply is None:
            return {"ok": False, "error": "loadUnpacked 无响应"}
        if "error" in reply:
            return {"ok": False, "error": f"loadUnpacked 报错: {reply['error'].get('message', '?')}"}
        result = {"ok": True, "id": reply.get("result", {}).get("id")}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            sock.close()
        except Exception:
            pass
    _write_loaded_marker(ext_dir, result.get("id"))
    if navigate_url:
        result["navigated"] = _navigate(port, navigate_url, _open)
    return result
